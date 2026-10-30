"""Walk public rosters: python examples/async_rosters.py nacl."""

import argparse

import anyio

from heir import AsyncHeir


async def main(league: str) -> None:
    async with AsyncHeir() as client:
        page = await client.league(league).rosters(page_size=50)
        async for roster in page:
            print(roster.name, roster.team_mmr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("league")
    args = parser.parse_args()
    anyio.run(main, args.league)
