# SDK build tools

This private npm project generates OpenAPI types and bundles declarations for the TypeScript SDK. It has its own lockfile and never becomes a runtime dependency or part of the published tarball.

The SDK uses TypeScript 7 for type checking. The latest `openapi-typescript` release, 7.13.0, requires TypeScript `^5.x` and uses the older JavaScript compiler API. tsup uses that API for declaration bundling too. Keeping these tools in a separate project allows the SDK checker to advance without bypassing peer requirements. TypeScript 5.9.3 is the latest compatible compiler for this toolchain.

From `typescript/`, install both projects and run the shared commands:

```bash
npm ci
npm --prefix tools/codegen ci
npm run generate:check
npm run typecheck
npm run test:package
```

Use Node 22.18+, 24.11+, or 26+ on the supported development release lines. The generated SDK still targets Node 20; `npm run test:runtime` exercises an already-built package on that runtime.

Dependabot has a separate entry for this directory. Only this project's TypeScript major upgrades are held while the generator requires `^5.x`; the primary checker and other tools continue receiving updates. Remove that constraint when upstream tools support the newer compiler API, then run generation freshness, declaration consumers, and package checks before consolidating the projects.
