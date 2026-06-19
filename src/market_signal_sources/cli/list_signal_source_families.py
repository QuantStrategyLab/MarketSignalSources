from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.source_catalog import (
    signal_source_family_catalog_payload,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = signal_source_family_catalog_payload(families=args.family)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print JSON-safe signal source family catalog metadata."
    )
    parser.add_argument(
        "--family",
        action="append",
        help="Limit output to a known signal source family. Can be provided multiple times.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
