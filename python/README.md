# heir-sdk

The official Python client for the [Heir public API](https://api.heir.gg/public/v1/openapi.json): League players, ratings, rosters, schedules, results, inventory, fixture eligibility, and stat submission. Requires Python 3.10 or later. Includes synchronous and asynchronous clients with typed Pydantic models.

```bash
pip install heir-sdk
```

## Read a League

Public reads need no key. The unauthenticated limit is 120 requests per minute per address across Leagues.

```python
from heir import Heir

with Heir() as client:
    league = client.league("nacl")  # vanity name or Discord server ID
    answer = league.player("mordhau", "A1B2C3D4E5F67890")
    if answer.player:
        print(answer.player.display_name, answer.player.mmr, answer.player.rank)
    for roster in league.rosters(category="competitive", page_size=50):
        print(roster.name, roster.team_mmr)
```

Models use snake_case fields (`display_name`) for the API's camelCase (`displayName`); either spelling constructs a model. Unknown response fields are ignored. Use `model_dump(mode="json", by_alias=True)` when exporting a model in the API's spelling.

A list call returns a `Page`: `.items` contains the current page, `.body` contains the full response, and `.next()` fetches the following page. Iteration fetches subsequent pages with the same filters. Stop iteration when you have enough rows to avoid unnecessary requests. Leaderboard and standings bodies include snapshot timestamps.

## Use a developer key

A League Organizer creates a key under Manage League → Developer. With it, reads use that League's plan allowance, and permitted eligibility checks and stat submission become available. Keep keys on your server, outside browser and game-client bundles.

```python
import os

from heir import Heir

with Heir(api_key=os.environ["HEIR_API_KEY"]) as client:
    league = client.league(os.environ["HEIR_LEAGUE"])
    result = league.check_eligibility(
        "mordhau",
        [os.environ["HEIR_PLAYER_ID"]],
        fixture_id=os.environ["HEIR_FIXTURE_ID"],
        roster_id=os.environ["HEIR_ROSTER_ID"],
        gamemode="SKM",
    )
    for player in result.players:
        print(player.identifier, player.eligible, player.reasons)
```

Eligibility is advisory and does not reserve roster seats. The fixture and gamemode determine its scope; it has no category option.

## Async

`AsyncHeir` exposes the same operations, awaited. Use `async for` for pages. The SDK tests both asyncio and Trio; install Trio separately if it is your application's backend.

```python
import asyncio

from heir import AsyncHeir


async def main() -> None:
    async with AsyncHeir() as client:
        page = await client.league("nacl").rosters()
        async for roster in page:
            print(roster.name)


asyncio.run(main())
```

## Submit stats

`client.stats.submit_match(document)` accepts a completed `HeirMatchFile`, a dictionary using either field spelling, or the `MatchTemplate` returned by `client.stats.gamemodes()`. The key must permit the gamemode. Fill in actual player identities, scores, and match times before submitting. The catalog lists supported gamemodes and stat keys; `client.stats.schemas()` describes tracking counters.

Set `reference` to your application's stable match ID. An identical repeat with the same reference is a no-op, allowing safe retries after connection failures. Without a reference, ambiguous connection failures and gateway errors are not automatically retried. Datetimes serialize in UTC at millisecond precision. Optional fields you omit stay omitted; explicit `None` remains JSON `null`, so use it only where the API accepts null.

```python
import json
import os
from pathlib import Path

from heir import Heir

# match.json contains your completed heir-match-v1 document, including a stable reference.
document = json.loads(Path("match.json").read_text())
with Heir(api_key=os.environ["HEIR_API_KEY"]) as client:
    receipt = client.stats.submit_match(document)
    print(receipt.status, receipt.problems)
```

For live tracking, use `begin_match`, `append_units`, `heartbeat`, then `finalize`; `upload` submits a completed tracked match. Every tracking write receives one generated `Idempotency-Key` reused by internal retries. Pass `idempotency_key="your-stable-operation-id"` when your application may repeat the call later. `begin_match`, `append_units`, and `upload` accept `dry_run=True` to validate without storing. Heartbeats and finalization are writes and have no dry-run option.

Runnable examples with complete imports and command-line inputs:

- [Public player lookup](examples/read_league.py): `python examples/read_league.py nacl mordhau PLAYER_ID`
- [Async roster pagination](examples/async_rosters.py): `python examples/async_rosters.py nacl`
- [Completed match submission](examples/submit_match.py): set `HEIR_API_KEY`, then run `python examples/submit_match.py match.json`

## Errors and retries

SDK operations expose `HeirError` subclasses:

| Error | Meaning |
| --- | --- |
| `HeirInputError` | Invalid client configuration or a request that cannot be validated/encoded; inspect `__cause__` for details. |
| `HeirProtocolError` | A successful HTTP response could not be decoded as the expected model; `.body` preserves its bytes. |
| `HeirAPIError` | An HTTP error response; inspect `.code`, `.message`, `.status_code`, `.issues`, `.retry_after`, `.headers`, and `.body`. |
| `HeirTimeoutError` | An HTTPX operation timed out; also a `HeirConnectionError`. `.timeout` is the SDK's configured limit, or `None` when an injected HTTP client owns the limits. |
| `HeirConnectionError` | Another HTTP transport failure; `__cause__` contains the original exception. |

Directly constructing a Pydantic model may raise Pydantic's `ValidationError`. Cancellation and programming errors are allowed to propagate. An API error's `.code` is stable; its human-readable message may change. `.is_rate_limited` indicates status 429.

The SDK retries 429 and 503 responses up to `max_retries` times (default 2). Reads and idempotent writes also retry connection failures and 500/502/504 responses. Timeouts are not retried. Delays honor `Retry-After` or use exponential backoff with jitter. If any proposed delay exceeds `max_retry_delay` (default 30 seconds), the error is returned immediately. An API error retains `retry_after` so your application can schedule a later attempt.

## Configuration, caching, and lifetime

```python
from heir import Heir, RequestOptions

with Heir(timeout=30.0, max_retries=2, max_retry_delay=30.0, cache=True, user_agent="my-server/1.0") as client:
    answer = client.league("nacl").player("mordhau", "A1B2C3D4E5F67890", options=RequestOptions(no_cache=True))
    print(answer.player)
```

`timeout` is the HTTPX inactivity timeout for each connect, read, write, or connection-pool operation, **not an overall request deadline**. Set `None` to disable it. Async applications can impose an overall deadline with their own cancellation scope. Retry counts must be non-negative integers; delays must be finite and non-negative; timeouts must be finite and positive or `None`. Numeric delays and timeouts must fit the platform's `threading.TIMEOUT_MAX` seconds.

`base_url` defaults to `https://api.heir.gg` and accepts an absolute HTTP(S) URL without credentials, query, or fragment. An injected `http_client=httpx.Client(...)` or `httpx.AsyncClient(...)` supplies your own transport, proxy, and timeouts. You own that client's lifetime; the SDK closes only clients it creates. Keep an injected client's auth/header context stable, or disable SDK caching when changing it.

Cacheable League reads use `Cache-Control`, `Age`, `Date`, and `ETag`/`If-None-Match`. `no-cache` forces revalidation; `no-store` and responses with any `Vary` header are not retained. A 304 updates metadata while retaining the response body. Up to 1,000 responses are kept per client, evicting the least recently used entry. Concurrent misses may make separate requests.

`cache=False` disables caching. `RequestOptions(no_cache=True)` bypasses it for one call. Calls with custom `RequestOptions(headers=...)` also bypass caching so header-dependent responses cannot mix. Header names are case-insensitive; SDK-controlled headers, including a configured API key and generated idempotency key, take precedence. `client.clear_cache()` discards all retained responses.

## Developing

From this directory, activate the environment before using its commands:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]" -c requirements-dev.txt
python scripts/generate.py --check
pytest
ruff check .
ruff format --check .
mypy
```

Generated models come from `../spec` and the shared `type-names.json`; regenerate with `python scripts/generate.py`. Shared fixtures in `../tests/contracts.json` exercise all 24 operations through sync, asyncio, and Trio clients. Work from a repository checkout to run these contract tests and regenerate models.

Check the built distribution in a separate environment:

```bash
python -m build --no-isolation
python scripts/check_wheel.py
# On Python 3.10, also exercise the oldest declared runtime dependencies:
python scripts/check_wheel.py --minimum
```

The smoke test rejects editable installs and makes only mock HTTP calls. Test the minimum dependency range separately on Python 3.10 by installing the wheel with `anyio==4.14.2`, `httpx==0.27.0`, and `pydantic==2.7.0`, then running the smoke test and pytest with the development test tools installed. Keep that environment separate from generation/lint tooling so newer development-tool dependencies do not silently raise runtime minimums.

### Dependency maintenance

`requirements-dev.txt` records the exact runtime, test, generation, lint, and build dependency versions exercised by CI. It is a universal resolution with Python and platform markers, so Python 3.10 and newer and different operating systems can use the same file. Install it as a constraint alongside the editable development extra, as shown above. The published SDK retains compatible runtime ranges rather than requiring every application to use these exact development versions. Build with `--no-isolation` after that constrained installation to use the recorded build toolchain.

Refresh the constraints using the same resolver version, then run generation, lint, typing, tests, builds, and both installed-wheel checks:

```bash
uvx --from uv==0.13.6 uv pip compile pyproject.toml \
  --extra dev --universal --python-version 3.10 --upgrade \
  --output-file requirements-dev.txt
uv pip install --upgrade -e ".[dev]" -c requirements-dev.txt
```

Run the dependency advisory check on Python 3.11 or newer:

```bash
pip-audit -r requirements-dev.txt --no-deps --disable-pip --strict
```

The audit tool is a development dependency only on Python 3.11+, because its cache's patched `filelock` releases require that version. This keeps its vulnerable older dependency chain out of Python 3.10 environments; it does not change the SDK's Python 3.10 support. The SDK requires AnyIO 4.14.2 or newer to include the fixes for [GHSA-82r6-8w77-94w6](https://osv.dev/vulnerability/GHSA-82r6-8w77-94w6) and [GHSA-5p39-cfhj-2xmp](https://osv.dev/vulnerability/GHSA-5p39-cfhj-2xmp).

Some transitive development packages can be newer only after an upstream constraint changes. The generator currently requires `isort<9`. Python 3.10 uses the newest compatible `more-itertools`, `platformdirs`, and Windows `pycparser`; newer releases require Python 3.11. Python 3.10.0–3.10.1 also needs an older compatible `importlib-metadata`. These exceptions are represented by markers in the constraints, while newer Python environments receive the newer compatible releases.
