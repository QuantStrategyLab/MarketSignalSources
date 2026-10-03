from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.research_export import write_research_export_manifest
from market_signal_sources.derived.us_equity import (
    NASDAQ_SP500_PRICE_PROXY_ARTIFACT_TYPE,
    NASDAQ_SP500_PRICE_PROXY_TRANSFORM,
    build_nasdaq_sp500_price_proxy_frame,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        input_paths = (
            (args.fred_nasdaq100_csv, "fred.nasdaq100"),
            (args.fred_sp500_csv, "fred.sp500"),
        )
        snapshots: dict[Path, bytes] = {}
        snapshot_paths: list[tuple[Path, Path, bytes, str]] = []
        for path, source_id in input_paths:
            resolved_path = path.resolve(strict=True)
            if resolved_path not in snapshots:
                snapshot = path.read_bytes()
                if path.resolve(strict=True) != resolved_path:
                    raise ValueError(f"input source path changed while reading: {path}")
                snapshots[resolved_path] = snapshot
            snapshot_paths.append(
                (path, resolved_path, snapshots[resolved_path], source_id)
            )
        nasdaq100_frame = pd.read_csv(BytesIO(snapshot_paths[0][2]))
        sp500_frame = pd.read_csv(BytesIO(snapshot_paths[1][2]))
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
        for path, resolved_path, _, _ in snapshot_paths:
            if path.resolve(strict=True) != resolved_path:
                raise ValueError(f"input source changed during export: {path}")
        for resolved_path, snapshot in snapshots.items():
            if resolved_path.read_bytes() != snapshot:
                raise ValueError(f"input source changed during export: {resolved_path}")

        manifest_path = args.manifest_path or args.output_csv.with_suffix(
            ".manifest.json"
        )
        input_sources = tuple(
            _input_source_record(path, source_id=source_id, input_bytes=snapshot)
            for path, _, snapshot, source_id in snapshot_paths
        )
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
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
            input_csv_bytes=snapshot_paths[0][2],
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


def _input_source_record(
    path: Path,
    *,
    source_id: str,
    input_bytes: bytes,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "path": str(path),
        "sha256": sha256(input_bytes).hexdigest(),
        "size_bytes": len(input_bytes),
    }


if __name__ == "__main__":
    raise SystemExit(main())
