# Maintain SDK documentation

SDK changes and their documentation belong in the same task. Handwritten guides live in the private `heirgg/docs` repository and are published at `docs.heir.gg/sdk`. Source-derived references live here so this repository's CI can check them without access to the private docs repository.

| Language | Site guide directory | Generated reference | Generation command, from this repository |
| --- | --- | --- | --- |
| TypeScript | `../docs/content/docs/sdk/typescript/` | `docs/reference/typescript.mdx` | `node typescript/scripts/generate-docs.mjs` |
| Python | `../docs/content/docs/sdk/python/` | `docs/reference/python.mdx` | `python3 python/scripts/generate_docs.py` |
| Go | `../docs/content/docs/sdk/go/` | `docs/reference/go.mdx` | `go run scripts/generate-go-docs.go` |

Each generator also accepts `--check`, which reports stale output without writing it. The generated reference records a fingerprint of the SDK source and shared specs. The reference includes public declarations and model details; it excludes implementation bodies and private members.

## Update a language

1. Read the current implementation and existing guides. List the public methods, options, defaults, models, errors, and behavior affected by the change.
2. Update every affected handwritten page in the matching site directory. Keep method signatures and returned types grounded in source. Include runnable or clearly scoped examples, required permissions, null/omitted behavior, and recovery steps.
3. Run that language's reference generator. Review its diff, including every added or removed export or model field. Treat fingerprint-only changes as a prompt to review behavioral prose, not as proof that it remains correct.
4. In the docs checkout, run `npm run sdk:sync -- --sdk ../heir-sdk`. This copies the canonical references into the site and records their hashes in `sdk-reference.json`.
5. Run the checks below. Include a link to the companion docs change when opening an SDK pull request. If the SDK change is internal-only, document that assessment and still refresh/check its source fingerprint.

Do not edit the site's copied `reference.mdx` pages directly. Change source comments/declarations or the corresponding generator here, then regenerate and synchronize. Handwritten guides remain the authoritative place for workflows and explanations.

## Verify both repositories

From this repository, after installing the TypeScript development dependencies:

```bash
node typescript/scripts/generate-docs.mjs --check
python3 python/scripts/generate_docs.py --check
go run scripts/generate-go-docs.go --check
```

From the docs checkout:

```bash
npm run check:sdk-source -- --sdk ../heir-sdk
npm run check
npm run build
```

Use `npm run build -- --webpack` if the local environment cannot run Turbopack. Inspect the SDK landing page, each language's navigation, one method guide, and generated references on desktop and mobile. Run the site's rendered-route checker against the preview.

The site's ordinary snapshot check works without a sibling SDK checkout, as required for an isolated deployment. `check:sdk-source` requires the source checkout and compares the copied references directly; agents must run it before declaring a cross-repository update complete. Snapshot validation alone does not prove parity with the current SDK or a deployed API.

These checks and agent instructions enforce documentation maintenance during development. Deploying the docs site continues to use that repository's existing publishing process; no registry credentials or cross-repository write tokens are needed for reference generation.
