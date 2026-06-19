from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.research_export import write_research_export_manifest
from market_signal_sources.artifacts.signal_bundle import sha256_file
from market_signal_sources.derived.us_equity import (
    NASDAQ_SP500_PRICE_PROXY_ARTIFACT_TYPE,
    NASDAQ_SP500_PRICE_PROXY_TRANSFORM,
    build_nasdaq_sp500_price_proxy_frame,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        nasdaq100_frame = pd.read_csv(args.fred_nasdaq100_csv)
        sp500_frame = pd.read_csv(args.fred_sp500_csv)
        output = build_nasdaq_sp500_price_proxy_frame(
            fred_nasdaq100_frame=nasdaq100_frame,
            fred_sp500_frame=sp500_frame,
            as_of=args.as_of,
            nasdaq100_date_column=args.nasdaq100_date_column,
            nasdaq100_value_column=args.nasdaq100_value_column,
            sp500_date_column=args.sp500_date_column,
            sp500_value_column=args.sp500_value_column,
            provider_timestamp=args.provider_timestamp,
            min_history=args.min_history,
        )
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
        manifest_path = args.manifest_path or args.output_csv.with_suffix(
            ".manifest.json"
        )
        input_sources = (
            _input_source_record(args.fred_nasdaq100_csv, source_id="fred.nasdaq100"),
            _input_source_record(args.fred_sp500_csv, source_id="fred.sp500"),
        )
        manifest = write_research_export_manifest(
            manifest_path,
            output_csv_path=args.output_csv,
            output_frame=output,
            input_csv_path=args.fred_nasdaq100_csv,
            artifact_type=NASDAQ_SP500_PRICE_PROXY_ARTIFACT_TYPE,
            transform=NASDAQ_SP500_PRICE_PROXY_TRANSFORM,
            source_version=args.source_version,
            as_of=args.as_of,
            min_history=args.min_history,
            input_sources=input_sources,
            transform_parameters={
                "nasdaq100_date_column": args.nasdaq100_date_column,
                "nasdaq100_value_column": args.nasdaq100_value_column,
                "sp500_date_column": args.sp500_date_column,
                "sp500_value_column": args.sp500_value_column,
                "price_alignment": "exact_date_inner_join",
                "output_proxy_columns": {
                    "NASDAQ100": "QQQ",
                    "SP500": "SPY",
                },
            },
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "fred_nasdaq100_csv": str(args.fred_nasdaq100_csv),
        "fred_sp500_csv": str(args.fred_sp500_csv),
        "output_csv": str(args.output_csv),
        "manifest": str(manifest_path),
        "artifact_type": manifest["artifact_type"],
        "transform": manifest["transform"],
        "output_sha256": manifest["output_csv"]["sha256"],
        "row_count": int(len(output)),
        "first_date": str(output.iloc[0]["date"]),
        "last_date": str(output.iloc[-1]["date"]),
        "columns": list(output.columns),
        "input_sources": list(input_sources),
    }
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export Nasdaq/S&P index price proxies for offline smart-DCA research."
        )
    )
    parser.add_argument("--fred-nasdaq100-csv", required=True, type=Path)
    parser.add_argument("--fred-sp500-csv", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--min-history", type=int, default=1)
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument("--nasdaq100-date-column", default="DATE")
    parser.add_argument("--nasdaq100-value-column", default="NASDAQ100")
    parser.add_argument("--sp500-date-column", default="DATE")
    parser.add_argument("--sp500-value-column", default="SP500")
    parser.add_argument(
        "--provider-timestamp",
        help=(
            "Optional source snapshot timestamp to stamp on every output row. "
            "Defaults to each observation date at 00:00:00Z."
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def _input_source_record(path: Path, *, source_id: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


if __name__ == "__main__":
    raise SystemExit(main())
