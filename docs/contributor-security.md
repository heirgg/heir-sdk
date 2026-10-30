# Contributor and release protections

Outside contributors submit fork pull requests. Repository write/admin access and package ownership are reserved for maintainers; contributing does not require either.

## Protected main branch

Require the `CI` check from GitHub Actions, an up-to-date branch, a pull request, resolved review conversations, and a code-owner approval. Dismiss stale approvals and require approval after the latest push. Block branch deletion and force pushes.

`.github/CODEOWNERS` assigns review to `@ethanzs`, including workflows, generation and publishing scripts, dependency manifests, contract snapshots, and the ownership file itself. While there is one release owner, keep any owner review bypass restricted to pull requests. Put mandatory CI and branch integrity in a separate ruleset with no bypass so that this review exception cannot skip checks or permit a direct push.

## Release tags and environments

Restrict creation of `typescript/v*`, `python/v*`, and `go/v*` to the release owner. Use a separate ruleset with no bypass to prevent updates or deletion of those tags. The Go module becomes discoverable when its public tag exists, before Actions can validate it.

| Environment | Allowed ref type | Pattern | Reviewer |
| --- | --- | --- | --- |
| `npm` | Tag | `typescript/v*` | `ethanzs` |
| `pypi` | Tag | `python/v*` | `ethanzs` |

Permit the reviewer to approve their own deployment while there is only one release owner. Configure additional independent reviewers before preventing self-review.

Every release workflow fetches complete history and checks that its tag resolves to the checked-out commit and that the commit belongs to `origin/main`. This is an additional safeguard, not a substitute for remote tag restrictions: a tag can also modify workflow code. Spec provenance and version checks still apply.

## Contributor workflows

Use the `pull_request` trigger on GitHub-hosted runners with read-only tokens and no publishing secrets. Require approval for workflow runs from outside collaborators. Do not run contributor code in privileged `pull_request_target` or artifact-consuming `workflow_run` jobs.

Keep “Actions may create and approve pull requests” disabled. Allow only the Actions repositories used by these workflows, and require full commit-SHA pins. Activate mandatory pinning after the pinned workflows reach `main`, so older unpinned workflows are not unexpectedly disabled. New third-party Actions require maintainer review and an allowlist update.

## Account and security settings

Enable Dependabot alerts/security updates, secret scanning and push protection, CodeQL for JavaScript/TypeScript, Python and Go, and private vulnerability reporting. Configure required organization 2FA through GitHub's organization authentication settings; the organization-level requirement has no documented REST or GraphQL setter. Keep registry publishing on OIDC and review package-owner membership periodically.

GitHub plan and repository visibility affect availability. On the Free plan, a private repository cannot use the full set of rulesets, required deployment reviewers, and scanning available to public repositories. A local configuration file or a prepared API payload does not activate a rejected protection. Verify settings through GitHub after applying them; making the repository public is a separate disclosure decision.
