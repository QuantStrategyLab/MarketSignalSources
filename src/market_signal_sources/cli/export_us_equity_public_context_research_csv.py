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
    NASDAQ_SP500_CONTEXT_ARTIFACT_TYPE,
    NASDAQ_SP500_CONTEXT_TRANSFORM,
    build_nasdaq_sp500_public_context_frame,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        fred_frame = pd.read_csv(args.fred_vixcls_csv)
        shiller_frame = pd.read_csv(args.shiller_cape_csv)
        output = build_nasdaq_sp500_public_context_frame(
            fred_vixcls_frame=fred_frame,
            shiller_cape_frame=shiller_frame,
            as_of=args.as_of,
            fred_date_column=args.fred_date_column,
            fred_vix_column=args.fred_vix_column,
            shiller_date_column=args.shiller_date_column,
            shiller_cape_column=args.shiller_cape_column,
            provider_timestamp=args.provider_timestamp,
            min_history=args.min_history,
        )
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
        manifest_path = args.manifest_path or args.output_csv.with_suffix(
            ".manifest.json"
        )
        input_sources = (
            _input_source_record(args.fred_vixcls_csv, source_id="fred.vixcls"),
            _input_source_record(
                args.shiller_cape_csv,
                source_id="shiller.cape_monthly",
            ),
        )
        manifest = write_research_export_manifest(
            manifest_path,
            output_csv_path=args.output_csv,
            output_frame=output,
            input_csv_path=args.fred_vixcls_csv,
            artifact_type=NASDAQ_SP500_CONTEXT_ARTIFACT_TYPE,
            transform=NASDAQ_SP500_CONTEXT_TRANSFORM,
            source_version=args.source_version,
            as_of=args.as_of,
            min_history=args.min_history,
            input_sources=input_sources,
            transform_parameters={
                "fred_date_column": args.fred_date_column,
                "fred_vix_column": args.fred_vix_column,
                "shiller_date_column": args.shiller_date_column,
                "shiller_cape_column": args.shiller_cape_column,
                "percentile_method": "expanding_rank_percentile",
                "cape_alignment": "asof_backward",
            },
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "fred_vixcls_csv": str(args.fred_vixcls_csv),
        "shiller_cape_csv": str(args.shiller_cape_csv),
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
            "Export CAPE/VIX-only Nasdaq/S&P public context for offline smart-DCA research."
        )
    )
    parser.add_argument("--fred-vixcls-csv", required=True, type=Path)
    parser.add_argument("--shiller-cape-csv", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--min-history", type=int, default=1)
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument("--fred-date-column", default="DATE")
    parser.add_argument("--fred-vix-column", default="VIXCLS")
    parser.add_argument("--shiller-date-column", default="date")
    parser.add_argument("--shiller-cape-column", default="cape")
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
