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
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        input_frame = pd.read_csv(args.input_csv)
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
