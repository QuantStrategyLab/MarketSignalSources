from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.platform_handoff import (
    upsert_platform_signal_handoff_index,
    validate_platform_signal_handoff_index,
    validate_platform_signal_handoff_manifest,
    write_platform_signal_handoff_index,
    write_platform_signal_handoff_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_index is not None:
            if (
                args.validate_manifest is not None
                or _has_single_manifest_inputs(args)
                or _has_index_write_inputs(args)
            ):
                raise ValueError(
                    "provide --validate-index without output or source inputs"
                )
            payload = validate_platform_signal_handoff_index(
                args.validate_index,
                consumer=args.consumer,
                as_of=args.as_of,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
        elif args.output_index is not None:
            if (
                _has_single_manifest_inputs(args)
                or args.validate_manifest is not None
                or args.upsert_index is not None
            ):
                raise ValueError(
                    "provide --output-index with --handoff-manifest only"
                )
            if not args.handoff_manifests:
                raise ValueError("--output-index requires at least one --handoff-manifest")
            payload = write_platform_signal_handoff_index(
                args.output_index,
                args.handoff_manifests,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
        elif args.upsert_index is not None:
            if _has_single_manifest_inputs(args) or args.validate_manifest is not None:
                raise ValueError(
                    "provide --upsert-index with exactly one --handoff-manifest"
                )
            if len(args.handoff_manifests or ()) != 1:
                raise ValueError(
                    "--upsert-index requires exactly one --handoff-manifest"
                )
            payload = upsert_platform_signal_handoff_index(
                args.upsert_index,
                args.handoff_manifests[0],
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
        elif args.validate_manifest is not None:
            if (
                args.output_manifest is not None
                or args.signal_bundle_manifest is not None
                or args.source_family_catalog_manifest is not None
                or args.consumer_contract_registry_manifest is not None
                or args.handoff_manifests
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
                require_runtime_consumer_coverage=(
                    args.require_runtime_consumer_coverage
                ),
            )
        else:
            if args.handoff_manifests:
                raise ValueError(
                    "provide --handoff-manifest only with --output-index or --upsert-index"
                )
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
        description="Build or validate a platform signal handoff manifest."
    )
    parser.add_argument("--signal-bundle-manifest")
    parser.add_argument("--source-family-catalog-manifest")
    parser.add_argument("--consumer-contract-registry-manifest")
    parser.add_argument("--output-manifest")
    parser.add_argument(
        "--handoff-manifest",
        action="append",
        dest="handoff_manifests",
        help=(
            "Platform handoff manifest to include in --output-index or "
            "--upsert-index. May be provided multiple times for --output-index."
        ),
    )
    parser.add_argument(
        "--output-index",
        help="Write a platform handoff index from one or more --handoff-manifest values.",
    )
    parser.add_argument(
        "--upsert-index",
        help="Add or replace exactly one --handoff-manifest in a platform handoff index.",
    )
    parser.add_argument(
        "--validate-manifest",
        help="Validate an existing platform signal handoff manifest.",
    )
    parser.add_argument(
        "--validate-index",
        help="Validate and resolve an existing platform signal handoff index.",
    )
    parser.add_argument(
        "--as-of",
        help="With --validate-index, select the latest handoff at or before this date.",
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
    parser.add_argument(
        "--require-runtime-consumer-coverage",
        action="store_true",
        help="Require the source family catalog to cover every runtime consumer.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def _has_single_manifest_inputs(args: argparse.Namespace) -> bool:
    return any(
        value is not None
        for value in (
            args.output_manifest,
            args.signal_bundle_manifest,
            args.source_family_catalog_manifest,
            args.consumer_contract_registry_manifest,
        )
    )


def _has_index_write_inputs(args: argparse.Namespace) -> bool:
    return (
        args.output_index is not None
        or args.upsert_index is not None
        or bool(args.handoff_manifests)
    )


if __name__ == "__main__":
    raise SystemExit(main())
