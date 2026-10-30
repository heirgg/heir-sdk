"""Submit a real match document: HEIR_API_KEY=... python examples/submit_match.py match.json."""

import argparse
import json
import os
from pathlib import Path

from heir import Heir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="A completed heir-match-v1 JSON document")
    args = parser.parse_args()
    document = json.loads(args.document.read_text())
    with Heir(api_key=os.environ["HEIR_API_KEY"]) as client:
        receipt = client.stats.submit_match(document)
        print(receipt.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    main()
