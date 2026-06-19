from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.source_catalog import (
    signal_source_family_catalog_payload,
    validate_signal_source_family_catalog_file,
    validate_signal_source_family_catalog_manifest,
    write_signal_source_family_catalog,
    write_signal_source_family_catalog_artifacts,
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
                or args.family
                or args.domain
            ):
                raise ValueError(
                    "provide --validate-manifest without --validate-json, "
                    "--family, --domain, --output-json, or --output-dir"
                )
            payload = validate_signal_source_family_catalog_manifest(
                args.validate_manifest,
                require_all_known_families=args.require_all_known_families,
            )
        elif args.validate_json is not None:
            if (
                args.output_json is not None
                or args.output_dir is not None
                or args.family
                or args.domain
            ):
                raise ValueError(
                    "provide --validate-json without --family, --domain, "
                    "--output-json, or --output-dir"
                )
            payload = validate_signal_source_family_catalog_file(
                args.validate_json,
                require_all_known_families=args.require_all_known_families,
            )
        elif args.require_all_known_families:
            raise ValueError(
                "--require-all-known-families is only valid with --validate-json "
                "or --validate-manifest"
            )
        elif args.output_json is not None and args.output_dir is not None:
            raise ValueError("provide either --output-json or --output-dir, not both")
        elif args.family and args.domain:
            raise ValueError("provide either --family or --domain, not both")
        elif args.output_dir is not None:
            payload = write_signal_source_family_catalog_artifacts(
                args.output_dir,
                families=args.family,
                domains=args.domain,
            )
        elif args.output_json is not None:
            payload = write_signal_source_family_catalog(
                args.output_json,
                families=args.family,
                domains=args.domain,
            )
        else:
            payload = signal_source_family_catalog_payload(
                families=args.family,
                domains=args.domain,
            )
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
    parser.add_argument(
        "--domain",
        action="append",
        help=(
            "Limit output to implemented families for a known market domain "
            "such as crypto, us_equity, or hk_equity. Can be provided multiple times."
        ),
    )
    parser.add_argument(
        "--validate-json",
        help="Validate a signal source family catalog JSON artifact.",
    )
    parser.add_argument(
        "--validate-manifest",
        help="Validate a signal source family catalog manifest and linked catalog.",
    )
    parser.add_argument(
        "--output-json",
        help="Write the catalog JSON artifact and print hash metadata.",
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Write signal_source_families.json and "
            "signal_source_families.manifest.json under this directory."
        ),
    )
    parser.add_argument(
        "--require-all-known-families",
        action="store_true",
        help="Require a validated catalog to cover every known signal source family.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
