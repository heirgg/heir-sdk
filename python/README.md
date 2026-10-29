# heir-sdk

The official Python client for the [Heir public API](https://api.heir.gg/public/v1/openapi.json): League players, ratings, Rosters, schedules, results and shop inventory, fixture eligibility checks, and stat submission. Python 3.10 or later, synchronous and asyncio clients, every type a pydantic model generated from the API's own OpenAPI document.

Status: pre-release, not yet published to PyPI.

```bash
pip install heir-sdk
```

```python
from heir import Heir, AsyncHeir
```

## Read a League

Reads need no key. Without one, each address may make 120 requests a minute across every League.

```python
heir = Heir()
nacl = heir.league("nacl")  # vanity name or Discord server ID

answer = nacl.player("mordhau", "A1B2C3D4E5F67890")
if answer.player:
    print(answer.player.display_name, answer.player.mmr, answer.player.rank)

lookup = nacl.lookup_players("steam", ["76561198000000000"])
inventory = nacl.inventory("mordhau", "A1B2C3D4E5F67890")
config = nacl.config()
```

Models use snake_case fields (`display_name`) for what the API spells in camelCase (`displayName`); both spellings construct a model, and unknown fields in an answer are ignored, as the API asks. Answers the API marks cacheable are kept for the minute it allows and revalidated with `ETag` after that, so asking on every join or every event costs one request a minute per question. `Heir(cache=False)`, or `options=RequestOptions(no_cache=True)` on one call, always asks.

## Use a developer key

A League Organizer creates a developer key under Manage League, Developer. With it, reads of that League draw on the plan's allowance instead of the per-address limit, eligibility checks work, and stat submission is available. Call from your server. Never put a key in a game client or a browser.

```python
heir = Heir(api_key=os.environ["HEIR_API_KEY"])

verdicts = heir.league("nacl").check_eligibility(
    "mordhau", playfab_ids, fixture_id=fixture_id, roster_id=roster_id, gamemode="SKM"
)
```

## Lists

A list call returns a `Page`: its rows in `.items`, the whole answer in `.body`, and `.next()` for the page after. Iterating a page walks it and every page after it, with the same filters.

```python
first = nacl.rosters(category="competitive", page_size=50)
print(len(first.items), first.has_more)

for roster in first:
    print(roster.name, roster.team_mmr)

board = nacl.leaderboard(metric="heirRating")
print(board.body.snapshot_at, board.items[0])
```

## Async

`AsyncHeir` has the same methods, awaited, and pages are walked with `async for`. It runs on asyncio or any anyio backend.

```python
async with AsyncHeir(api_key=os.environ["HEIR_API_KEY"]) as heir:
    page = await heir.league("nacl").rosters()
    async for roster in page:
        print(roster.name)
```

## Submit stats

Requires a key whose gamemode permissions include the gamemode. Any gamemode a League plays can be sent as one finished `heir-match-v1` document, as a model or a plain dict. Set `reference` to your own id for the match: a repeat with the same contents is a no-op, and the client will then also resend it after a connection failure. Datetimes are sent in UTC at millisecond precision, which is what the API accepts.

```python
from heir import HeirMatchFile, HeirMatchGamemode, HeirMatchMap, HeirMatchPlayer, HeirMatchScore

receipt = heir.stats.submit_match(
    HeirMatchFile(
        format="heir-match-v1",
        gamemode=HeirMatchGamemode(key="SKM"),
        type="pug",
        reference="lobby-42-2026-10-16-1900",
        started_at=datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc),
        maps=[
            HeirMatchMap(
                map="Camp",
                winner="a",
                score=HeirMatchScore(a=7, b=4),
                players=[
                    HeirMatchPlayer(
                        identity="A1B2C3D4E5F67890",
                        name="Ada",
                        side="a",
                        stats={"kills": 18, "deaths": 9, "score": 2140},
                    ),
                    HeirMatchPlayer(
                        identity="0F1E2D3C4B5A6978",
                        name="Brann",
                        side="b",
                        stats={"kills": 11, "deaths": 15, "score": 1310},
                    ),
                ],
            )
        ],
    )
)
print(receipt.status, receipt.problems)
```

Team matches can also be tracked live, a round at a time. Every tracking write carries an `Idempotency-Key`. The client generates one per call so its own retries never write twice; pass `idempotency_key=` when your code may send the same request again later.

```python
begun = heir.stats.begin_match({"match_id": "lobby-42", "started_at": int(time.time() * 1000)})
heir.stats.append_units(
    "lobby-42",
    {"games": [{"schema_ref": "mordhau.skirmish@1", "game_id": "map-1", "rounds": [round]}]},
    idempotency_key="lobby-42:map-1:round-0",
)
heir.stats.heartbeat("lobby-42")
done = heir.stats.finalize("lobby-42")

# Or check a request without storing anything:
heir.stats.append_units("lobby-42", units, dry_run=True)
```

`heir.stats.gamemodes()` lists the gamemodes a key may submit with their stat keys and an empty document to fill in; `heir.stats.schemas()` lists the tracking schemas and every counter a Player line may carry.

## Errors

Everything the SDK raises extends `HeirError`.

```python
from heir import HeirAPIError, HeirConnectionError, HeirTimeoutError

try:
    nacl.player("mordhau", identifier)
except HeirAPIError as error:
    # error.code is the stable code to branch on; error.message is a sentence for a person.
    if error.code == "league-not-found":
        ...
    if error.is_rate_limited:
        print("wait", error.retry_after, "seconds")
    print(error.status_code, error.issues)
except HeirTimeoutError:
    ...  # no answer within the timeout
except HeirConnectionError as error:
    ...  # could not reach the API; error.__cause__ has the underlying failure
```

The client retries a 429 or 503 up to `max_retries` times (default 2), waiting as `Retry-After` says or with increasing backoff. Reads, and writes that carry an idempotency key, are also retried after a connection failure or a gateway error. A `Retry-After` longer than `max_retry_delay` (default 30 s) is not waited for: the error is raised with `retry_after` set so your code can decide.

## Options

```python
Heir(
    api_key=key,  # a League developer key; leave out to read without one
    base_url="https://api.heir.gg",
    http_client=httpx.Client(),  # your own client: proxy, transport, fake; you then own its timeout
    max_retries=2,
    max_retry_delay=30.0,
    timeout=30.0,  # per attempt, in seconds
    cache=True,  # honour Cache-Control and ETag on League reads
    user_agent="my-server/1.0",
)
```

Every call also takes `options=RequestOptions(headers=..., no_cache=...)`. The client owns the `httpx` client it makes; close it with `heir.close()` or a `with` block.

## Developing

```bash
uv venv && uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
python scripts/generate.py               # src/heir/models from ../spec
pytest
ruff check . && ruff format --check . && mypy
```

`src/heir/models/public.py` and `stats.py` are written from `../spec` by `scripts/generate.py`, which uses datamodel-code-generator and first names the document's inline shapes with the table in `../spec/type-names.json`, shared with the other SDKs; CI fails when they are out of date.
