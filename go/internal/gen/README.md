# Generator dependencies

This module isolates build tooling from the SDK. It requires Go 1.26 or newer; the published SDK remains standard-library-only and supports Go 1.23.

The October 30, 2026 refresh selected the latest compatible dependencies. Both direct libraries were already current: `kin-openapi` v0.152.0 and `oapi-codegen/v2` v2.8.1. Three transitive dependencies must remain on the same YAML node API as that stable generator:

| Module | Latest compatible version | Upgrade constraint |
| --- | --- | --- |
| `github.com/speakeasy-api/openapi` | v1.25.6 | v1.26.0 changed public node types from `gopkg.in/yaml.v3` to `go.yaml.in/yaml/v3`. `oapi-codegen` v2.8.1 still passes the former type to its overlay helpers. |
| `github.com/speakeasy-api/jsonpath` | v0.6.3 | v0.7.0 makes the same YAML module migration and does not compile with the compatible OpenAPI library. |
| `github.com/dprotaso/go-yit` | v0.0.0-20250513224043-18a80f8f6df4 | This is the final revision before the YAML import migration. Later revisions change node types, first to `go.yaml.in/yaml/v3`, then to YAML v4 release candidates, while `vmware-labs/yaml-jsonpath` still uses `gopkg.in/yaml.v3`. |

The [OpenAPI v1.26.0 release notes](https://github.com/speakeasy-api/openapi/releases/tag/v1.26.0) document the breaking node-type change. The corresponding go-yit changes are [the YAML v3 import migration](https://github.com/dprotaso/go-yit/commit/24b2776f92ab9582f62d220d9ff4148c9b9e7360) and [the YAML v4 migration](https://github.com/dprotaso/go-yit/commit/199e8b87007e1f21a165bcf37f7d64b2d3d6a482). Upgrade these together after a compatible stable generator release; a blanket `go get -u ./...` currently breaks compilation.

From this directory, validate an upgrade with:

```bash
go mod tidy
go mod verify
go run . -check
go test ./...
go vet ./...
govulncheck ./...
go list -m -u all
```

`go list -m -u all` also reports modules referenced only by upstream module metadata. Check `go mod why -m <module>` before treating those as dependencies to retain: `go mod tidy` removes unnecessary overrides. Keep generated files unchanged when the selected upgrades produce identical models, then run the SDK's tests and lint from `../..`.
