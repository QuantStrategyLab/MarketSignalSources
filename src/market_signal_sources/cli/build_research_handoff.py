from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.research_handoff import (
    validate_research_signal_handoff_manifest,
    write_research_signal_handoff_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_manifest is not None:
            if (
                args.output_manifest is not None
                or args.research_export_manifest is not None
                or args.source_family_catalog_manifest is not None
                or args.consumer_contract_registry_manifest is not None
            ):
                raise ValueError(
                    "provide --validate-manifest without --output-manifest or "
                    "source manifest inputs"
                )
            payload = validate_research_signal_handoff_manifest(
                args.validate_manifest,
                consumer=args.consumer,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
        else:
            if (
                args.output_manifest is None
                or args.research_export_manifest is None
                or args.source_family_catalog_manifest is None
                or args.consumer_contract_registry_manifest is None
            ):
                raise ValueError(
                    "--output-manifest, --research-export-manifest, "
                    "--source-family-catalog-manifest, and "
                    "--consumer-contract-registry-manifest are required"
                )
            payload = write_research_signal_handoff_manifest(
                args.output_manifest,
                research_export_manifest=args.research_export_manifest,
                source_family_catalog_manifest=args.source_family_catalog_manifest,
                consumer_contract_registry_manifest=(
                    args.consumer_contract_registry_manifest
                ),
                consumer=args.consumer,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate a research signal handoff manifest."
    )
    parser.add_argument("--research-export-manifest")
    parser.add_argument("--source-family-catalog-manifest")
    parser.add_argument("--consumer-contract-registry-manifest")
    parser.add_argument("--output-manifest")
    parser.add_argument(
        "--validate-manifest",
        help="Validate an existing research signal handoff manifest.",
    )
    parser.add_argument(
        "--consumer",
        help=(
            "Require source catalog and consumer registry coverage for this "
            "consumer profile."
        ),
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
    parser.add_argument(
        "--require-runtime-consumer-coverage",
        action="store_true",
        help="Require the source family catalog to cover every runtime consumer.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
