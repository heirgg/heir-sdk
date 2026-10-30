# Report a security vulnerability

Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/heirgg/heir-sdk/security/advisories/new). Include the affected package/version, impact, reproduction, and a suggested fix if available. Remove credentials and private data from attachments.

## Private reporting availability

Repository owners must enable private vulnerability reporting under **Settings → Code security → Private vulnerability reporting** before the public launch. This document does not mean that the setting is already enabled.

If the private report form is unavailable, open an issue asking maintainers to enable a private reporting channel. Include no exploit details or sensitive data in that public request. No separate security email address is designated here.

## Supported security fixes

Before 1.0, fixes target the latest release of each SDK. Older 0.x lines have no promised backports. The current checkout is a release candidate; consult [CHANGELOG.md](CHANGELOG.md) and the package's releases for published versions.

If a developer key is exposed, revoke it in the League's developer settings and replace it on your servers. Do not paste the key into an issue, pull request, crash log, or example. Credential rotation does not require waiting for an SDK patch.

## Scope and disclosure

Relevant reports include credential disclosure, unsafe request handling, dependency vulnerabilities that affect consumers, and publishing or artifact-integrity flaws. Ordinary integration errors belong in [support issues](SUPPORT.md).

Maintainers should confirm the affected versions, agree on disclosure with the reporter, and publish fixes before public exploit details. No response-time or bounty commitment is implied.
