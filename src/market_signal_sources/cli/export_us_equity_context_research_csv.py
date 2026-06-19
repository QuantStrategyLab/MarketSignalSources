from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.research_export import write_research_export_manifest
from market_signal_sources.derived.us_equity import (
    NASDAQ_SP500_CONTEXT_ARTIFACT_TYPE,
    NASDAQ_SP500_CONTEXT_TRANSFORM,
    build_nasdaq_sp500_context_frame,
    write_nasdaq_sp500_context_availability_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        input_frame = pd.read_csv(args.input_csv)
        quality_report = None
        if args.quality_report is not None:
            quality_report = write_nasdaq_sp500_context_availability_report(
                args.quality_report,
                args.input_csv,
                as_of=args.as_of,
                date_column=args.date_column,
                cape_percentile_column=args.cape_percentile_column,
                vix_percentile_column=args.vix_percentile_column,
                breadth_column=args.breadth_column,
                provider_timestamp_column=args.provider_timestamp_column,
                breadth_universe_snapshot_column=(
                    args.breadth_universe_snapshot_column
                ),
                breadth_universe_as_of_column=args.breadth_universe_as_of_column,
                require_point_in_time_metadata=args.require_point_in_time_metadata,
                min_history_rows=args.min_history,
                max_allowed_gap_days=args.max_allowed_gap_days,
            )
            if (
                args.require_point_in_time_metadata
                and quality_report["quality_status"] == "fail"
            ):
                raise ValueError(
                    "US equity context availability report failed: "
                    + ",".join(quality_report["failure_reasons"])
                )
        output = build_nasdaq_sp500_context_frame(
            input_frame,
            as_of=args.as_of,
            date_column=args.date_column,
            cape_percentile_column=args.cape_percentile_column,
            vix_percentile_column=args.vix_percentile_column,
            breadth_column=args.breadth_column,
            provider_timestamp_column=args.provider_timestamp_column,
            passthrough_columns=_split_columns(args.passthrough_columns),
            min_history=args.min_history,
        )
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
        manifest_path = args.manifest_path or args.output_csv.with_suffix(
            ".manifest.json"
        )
        manifest = write_research_export_manifest(
            manifest_path,
            output_csv_path=args.output_csv,
            output_frame=output,
            input_csv_path=args.input_csv,
            artifact_type=NASDAQ_SP500_CONTEXT_ARTIFACT_TYPE,
            transform=NASDAQ_SP500_CONTEXT_TRANSFORM,
            source_version=args.source_version,
            as_of=args.as_of,
            min_history=args.min_history,
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
        "manifest": str(manifest_path),
        "artifact_type": manifest["artifact_type"],
        "transform": manifest["transform"],
        "output_sha256": manifest["output_csv"]["sha256"],
        "row_count": int(len(output)),
        "first_date": str(output.iloc[0]["date"]),
        "last_date": str(output.iloc[-1]["date"]),
        "columns": list(output.columns),
    }
    if args.quality_report is not None and quality_report is not None:
        summary["quality_report"] = str(args.quality_report)
        summary["quality_status"] = quality_report["quality_status"]
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export a Nasdaq/S&P external context CSV for offline smart-DCA research."
        )
    )
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--min-history", type=int, default=1)
    parser.add_argument("--max-allowed-gap-days", type=int, default=7)
    parser.add_argument("--quality-report", type=Path)
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--cape-percentile-column", default="cape_percentile")
    parser.add_argument("--vix-percentile-column", default="vix_percentile")
    parser.add_argument(
        "--breadth-column",
        default="breadth_above_sma200_pct",
    )
    parser.add_argument("--provider-timestamp-column", default="provider_timestamp")
    parser.add_argument(
        "--breadth-universe-snapshot-column",
        default="breadth_universe_snapshot_id",
    )
    parser.add_argument(
        "--breadth-universe-as-of-column",
        default="breadth_universe_as_of",
    )
    parser.add_argument(
        "--require-point-in-time-metadata",
        action="store_true",
        help=(
            "Fail the availability report when provider timestamp or breadth "
            "universe point-in-time metadata is missing."
        ),
    )
    parser.add_argument(
        "--passthrough-columns",
        default="QQQ,SPY",
        help="Comma-separated optional passthrough price columns for research joins.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def _split_columns(value: str) -> tuple[str, ...]:
    return tuple(column.strip() for column in str(value or "").split(",") if column.strip())


if __name__ == "__main__":
    raise SystemExit(main())
