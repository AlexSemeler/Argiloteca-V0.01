"""Explicit administrative, atomic public metadata snapshot. Not an MCP write tool."""
import argparse
import json
import os
from pathlib import Path
from .invenio import Invenio


def main():
    p = argparse.ArgumentParser(); p.add_argument("--base-url", required=True)
    p.add_argument("--output", default="storage/records.jsonl"); p.add_argument("--maximum", type=int, default=5000)
    p.add_argument("--local-self-signed", action="store_true")
    args = p.parse_args()
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(".building.jsonl"); count = 0
    try:
        with staging.open("w") as stream:
            for row in Invenio(args.base_url, local_self_signed=args.local_self_signed).records(args.maximum):
                stream.write(json.dumps(row, ensure_ascii=False) + "\n"); count += 1
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    print(json.dumps({"public_records": count, "snapshot": str(target)}))


if __name__ == "__main__":
    main()
