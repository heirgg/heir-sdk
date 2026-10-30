"""Read public player information: python examples/read_league.py nacl mordhau PLAYER_ID."""

import argparse

from heir import Heir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("league")
    parser.add_argument("credential")
    parser.add_argument("identifier")
    args = parser.parse_args()
    with Heir() as client:
        answer = client.league(args.league).player(args.credential, args.identifier)
        print(answer.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    main()
