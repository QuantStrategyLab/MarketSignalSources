from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.quality_report import write_ohlcv_quality_report
from market_signal_sources.artifacts.signal_bundle import (
    build_daily_technical_signal_bundle,
    upsert_signal_bundle_publication_index,
    write_signal_bundle_artifacts,
)
from market_signal_sources.providers import load_ohlcv_csv, local_csv_provider_metadata


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        ohlcv = load_ohlcv_csv(
            args.input_csv,
            date_column=args.date_column,
            close_column=args.close_column,
            high_column=args.high_column,
            low_column=args.low_column,
            volume_column=args.volume_column,
            as_of=args.as_of,
        )
        provider_metadata = local_csv_provider_metadata(
            args.input_csv,
            as_of=args.as_of,
            provider=args.provider,
            provider_dataset=args.provider_dataset,
            license_scope=args.license_scope,
        )
        bundle = build_daily_technical_signal_bundle(
            {args.symbol: ohlcv},
            domain=args.domain,
            bundle_id_prefix=args.bundle_id_prefix,
            as_of=args.as_of,
            provider=provider_metadata.provider,
            provider_dataset=provider_metadata.provider_dataset,
            raw_artifact_sha256=provider_metadata.raw_artifact_sha256,
            transform=args.transform,
            source_version=args.source_version,
            code_commit=args.code_commit,
            generated_at=args.generated_at,
            provider_timestamp=provider_metadata.provider_timestamp,
            freshness_status=args.freshness_status,
            freshness_policy=args.freshness_policy,
            license_scope=provider_metadata.license_scope,
            generated_by=provider_metadata.generated_by,
            compatible_profiles=tuple(args.compatible_profile),
            min_history=args.min_history,
        )
        output_dir = Path(args.output_dir)
        quality_report_path = output_dir / "quality_report.json"
        write_ohlcv_quality_report(
            quality_report_path,
            args.input_csv,
            date_column=args.date_column,
            close_column=args.close_column,
            high_column=args.high_column,
            low_column=args.low_column,
            volume_column=args.volume_column,
            as_of=args.as_of,
            min_history_rows=args.min_history,
            max_allowed_gap_days=args.max_allowed_gap_days,
        )
        artifact_paths = write_signal_bundle_artifacts(
            output_dir,
            bundle,
            quality_report_path=quality_report_path,
        )
        artifact_paths["quality_report"] = quality_report_path
        if args.publication_index is not None:
            artifact_paths["publication_index"] = upsert_signal_bundle_publication_index(
                args.publication_index,
                artifact_paths["manifest"],
                generated_at=args.generated_at,
            )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "bundle_id": bundle["bundle_id"],
        "as_of": bundle["as_of"],
        "symbol": args.symbol,
        "output_dir": str(args.output_dir),
        "artifacts": {
            name: str(path)
            for name, path in sorted(artifact_paths.items())
        },
    }
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a daily technical market_signal_bundle.v1 artifact from an OHLCV CSV."
        )
    )
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--domain", default="us_equity")
    parser.add_argument("--bundle-id-prefix", default="us_equity.technical.daily")
    parser.add_argument("--transform", default="technical.daily_ohlcv.v1")
    parser.add_argument("--provider", default="local_csv")
    parser.add_argument("--provider-dataset", default="daily_ohlcv")
    parser.add_argument("--license-scope", default="internal_runtime")
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument(
        "--code-commit",
        default="0000000000000000000000000000000000000000",
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--freshness-status", default="fresh")
    parser.add_argument("--freshness-policy", default="daily_close_t_plus_1")
    parser.add_argument("--min-history", type=int, default=252)
    parser.add_argument("--max-allowed-gap-days", type=int, default=5)
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--close-column", default="close")
    parser.add_argument("--high-column", default="high")
    parser.add_argument("--low-column", default="low")
    parser.add_argument("--volume-column", default="volume")
    parser.add_argument(
        "--compatible-profile",
        action="append",
        required=True,
        help="Consumer id compatible with this bundle. Can be provided multiple times.",
    )
    parser.add_argument(
        "--publication-index",
        type=Path,
        help="Optional root index to upsert with the generated manifest path.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
