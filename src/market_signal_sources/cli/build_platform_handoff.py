from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.platform_handoff import (
    validate_platform_signal_handoff_manifest,
    write_platform_signal_handoff_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_manifest is not None:
            if (
                args.output_manifest is not None
                or args.signal_bundle_manifest is not None
                or args.source_family_catalog_manifest is not None
                or args.consumer_contract_registry_manifest is not None
            ):
                raise ValueError(
                    "provide --validate-manifest without --output-manifest or "
                    "source manifest inputs"
                )
            payload = validate_platform_signal_handoff_manifest(
                args.validate_manifest,
                consumer=args.consumer,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
            )
        else:
            if (
                args.output_manifest is None
                or args.signal_bundle_manifest is None
                or args.source_family_catalog_manifest is None
                or args.consumer_contract_registry_manifest is None
            ):
                raise ValueError(
                    "--output-manifest, --signal-bundle-manifest, "
                    "--source-family-catalog-manifest, and "
                    "--consumer-contract-registry-manifest are required"
                )
            payload = write_platform_signal_handoff_manifest(
                args.output_manifest,
                signal_bundle_manifest=args.signal_bundle_manifest,
                source_family_catalog_manifest=args.source_family_catalog_manifest,
                consumer_contract_registry_manifest=(
                    args.consumer_contract_registry_manifest
                ),
                consumer=args.consumer,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate a platform signal handoff manifest."
    )
    parser.add_argument("--signal-bundle-manifest")
    parser.add_argument("--source-family-catalog-manifest")
    parser.add_argument("--consumer-contract-registry-manifest")
    parser.add_argument("--output-manifest")
    parser.add_argument(
        "--validate-manifest",
        help="Validate an existing platform signal handoff manifest.",
    )
    parser.add_argument(
        "--consumer",
        help="Validate the signal bundle against one consumer contract.",
    )
    parser.add_argument(
        "--require-all-known-families",
        action="store_true",
        help="Require the source family catalog to include every known family.",
    )
    parser.add_argument(
        "--require-all-known-consumers",
        action="store_true",
        help="Require the consumer contract registry to include every known consumer.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
