from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from market_signal_sources.artifacts.publication import (
    publish_platform_signal_handoff,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = publish_platform_signal_handoff(
            args.publication_dir,
            signal_bundle_manifest=args.signal_bundle_manifest,
            consumer=args.consumer,
            index_path=args.index_path,
            lookup_as_of=args.lookup_as_of,
            strategy=args.strategy,
            accepted_freshness_statuses=tuple(args.accepted_freshness_status),
            require_all_known_families=not args.allow_partial_source_catalog,
            require_all_known_consumers=not args.allow_partial_consumer_registry,
            require_runtime_consumer_coverage=not args.allow_partial_runtime_coverage,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish one already-built market signal bundle as a platform "
            "handoff directory with registry, catalog, index, audit, and "
            "runtime adapter config artifacts."
        )
    )
    parser.add_argument("--publication-dir", required=True, type=Path)
    parser.add_argument("--signal-bundle-manifest", required=True, type=Path)
    parser.add_argument("--consumer", required=True)
    parser.add_argument(
        "--index-path",
        type=Path,
        help="Platform handoff index to upsert. Defaults to publication_dir/../index.json.",
    )
    parser.add_argument(
        "--lookup-as-of",
        help="As-of date for validating the handoff index. Defaults to bundle as_of.",
    )
    parser.add_argument(
        "--strategy",
        help="Optional platform strategy profile for the runtime adapter config.",
    )
    parser.add_argument(
        "--accepted-freshness-status",
        action="append",
        default=["fresh"],
        help="Freshness status accepted by runtime validation. Can be repeated.",
    )
    parser.add_argument(
        "--allow-partial-source-catalog",
        action="store_true",
        help="Do not require the source catalog to include every known family.",
    )
    parser.add_argument(
        "--allow-partial-consumer-registry",
        action="store_true",
        help="Do not require the consumer registry to include every known consumer.",
    )
    parser.add_argument(
        "--allow-partial-runtime-coverage",
        action="store_true",
        help="Do not require every runtime consumer to map to a source family.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
