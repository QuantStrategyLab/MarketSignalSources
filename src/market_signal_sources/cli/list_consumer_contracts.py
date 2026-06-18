from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.consumer_contracts import (
    SignalConsumerContractError,
    consumer_contract_registry_payload,
    validate_consumer_contract_registry_file,
    validate_consumer_contract_registry_manifest,
    write_consumer_contract_registry,
    write_consumer_contract_registry_artifacts,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_manifest is not None:
            if (
                args.validate_json is not None
                or args.output_json is not None
                or args.output_dir is not None
                or args.consumer
            ):
                raise SignalConsumerContractError(
                    "provide --validate-manifest without --validate-json, --consumer, "
                    "--output-json, or --output-dir"
                )
            payload = validate_consumer_contract_registry_manifest(
                args.validate_manifest,
                require_all_known_consumers=args.require_all_known_consumers,
            )
        elif args.validate_json is not None:
            if (
                args.output_json is not None
                or args.output_dir is not None
                or args.consumer
            ):
                raise SignalConsumerContractError(
                    "provide --validate-json without --consumer, --output-json, "
                    "or --output-dir"
                )
            payload = validate_consumer_contract_registry_file(
                args.validate_json,
                require_all_known_consumers=args.require_all_known_consumers,
            )
        elif args.require_all_known_consumers:
            raise SignalConsumerContractError(
                "--require-all-known-consumers is only valid with --validate-json "
                "or --validate-manifest"
            )
        elif args.output_json is not None and args.output_dir is not None:
            raise SignalConsumerContractError(
                "provide either --output-json or --output-dir, not both"
            )
        elif args.output_dir is not None:
            payload = write_consumer_contract_registry_artifacts(
                args.output_dir,
                consumers=args.consumer,
            )
        elif args.output_json is not None:
            payload = write_consumer_contract_registry(
                args.output_json,
                consumers=args.consumer,
            )
        else:
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
    parser.add_argument(
        "--output-json",
        help="Write the registry JSON artifact and print hash metadata.",
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Write market_signal_consumers.json and "
            "market_signal_consumers.manifest.json under this directory."
        ),
    )
    parser.add_argument(
        "--validate-json",
        help="Validate a registry JSON artifact and print hash metadata.",
    )
    parser.add_argument(
        "--validate-manifest",
        help="Validate a registry manifest and its linked registry artifact.",
    )
    parser.add_argument(
        "--require-all-known-consumers",
        action="store_true",
        help="Require a validated registry to cover every known consumer.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
