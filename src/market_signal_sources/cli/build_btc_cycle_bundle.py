from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.artifacts.signal_bundle import (
    build_btc_cycle_signal_bundle,
    sha256_file,
    write_signal_bundle_artifacts,
)
from market_signal_sources.providers import load_ohlcv_csv


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
        bundle = build_btc_cycle_signal_bundle(
            ohlcv,
            as_of=args.as_of,
            symbol=args.symbol,
            provider=args.provider,
            provider_dataset=args.provider_dataset,
            raw_artifact_sha256=sha256_file(args.input_csv),
            source_version=args.source_version,
            code_commit=args.code_commit,
            generated_at=args.generated_at,
            freshness_status=args.freshness_status,
        )
        artifact_paths = write_signal_bundle_artifacts(args.output_dir, bundle)
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
            "Build a local BTC cycle market_signal_bundle.v1 artifact from an OHLCV CSV."
        )
    )
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--provider", default="local_csv")
    parser.add_argument("--provider-dataset", default="btc_usd_daily_ohlcv")
    parser.add_argument("--source-version", default="0.1.0")
    parser.add_argument(
        "--code-commit",
        default="0000000000000000000000000000000000000000",
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--freshness-status", default="fresh")
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--close-column", default="close")
    parser.add_argument("--high-column", default="high")
    parser.add_argument("--low-column", default="low")
    parser.add_argument("--volume-column", default="volume")
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
