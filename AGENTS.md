# Heir SDK working rules

This repository contains the TypeScript, Python, and Go clients for Heir's public API. Treat each language's public exports, options, models, errors, serialization, and transport behavior as a supported interface.

## Documentation is part of the change

For an SDK API, behavior, model, dependency/runtime requirement, example, or version change, read [docs/documentation.md](docs/documentation.md) before editing. Update the affected language guides in the adjacent `../docs/content/docs/sdk/` checkout in the same task. A code change is complete only after the corresponding documentation is accurate and the checks below pass.

- Account for every changed public method, option/default, model field/alias, return shape, error, and compatibility constraint. Document authentication, side effects, retries, cancellation, caching, pagination, and idempotency where they affect the caller.
- Regenerate the affected source-derived reference in `docs/reference/`, then synchronize it into the docs site. Generated references are inventories, not substitutes for updating usage guides and examples.
- Source fingerprints include implementation and shared API specifications. A changed fingerprint requires reviewing the handwritten guides even when signatures are unchanged. Record why guide prose is unchanged when a change has no observable effect.
- If the docs checkout is unavailable, locate or obtain an authorized checkout and continue there. Report the concrete missing access if that is impossible; do not describe documentation work as complete while the site changes remain outstanding.
- External contributors can include proposed guide edits with their SDK pull request. A maintainer with access to the private docs repository applies and verifies the site update before merging the SDK change.
- Keep examples free of credentials and private user data. Test examples against local fake transports; live stat writes require an explicit user request.
- Verify release availability before writing install instructions. Distinguish a source snapshot, a registry placeholder, and a published SDK release.

## Verification

Run the affected package's generation, typing/lint, tests, and installed-consumer checks from its manifest or contribution guide. Run the documentation generation checks and the docs site's source-comparison, content, and production-build checks described in [docs/documentation.md](docs/documentation.md). Include both repositories' changes and verification results in the handoff or linked pull requests.

Use the Go skills for Go code and documentation changes. Preserve the public SDK's supported runtime separately from its development-tool requirements. Follow [CONTRIBUTING.md](CONTRIBUTING.md), [RELEASING.md](RELEASING.md), and [docs/contributor-security.md](docs/contributor-security.md) for their respective workflows.

`spec/` is a backend snapshot. Refresh it with the sync script rather than editing generated contracts or models by hand. Keep publishing on the protected, tag-triggered OIDC workflows; documentation work does not authorize a package release.
