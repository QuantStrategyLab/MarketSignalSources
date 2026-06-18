from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.consumer_contracts import (
    SignalConsumerContractError,
    consumer_contract_registry_payload,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = consumer_contract_registry_payload(
            consumers=args.consumer,
        )
    except SignalConsumerContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print JSON-safe signal bundle consumer contracts."
    )
    parser.add_argument(
        "--consumer",
        action="append",
        help="Limit output to a known consumer. Can be provided multiple times.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
