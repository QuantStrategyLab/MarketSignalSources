from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

import pandas as pd

from market_signal_sources.derived.crypto import build_btc_cycle_indicator_frame
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
        output = build_btc_cycle_indicator_frame(
            ohlcv,
            as_of=args.as_of,
            min_history=args.min_history,
        )
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.output_csv, index=False)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "input_csv": str(args.input_csv),
        "output_csv": str(args.output_csv),
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
            "Export a daily BTC cycle indicator CSV for offline smart-DCA research."
        )
    )
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--min-history", type=int, default=200)
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--close-column", default="close")
    parser.add_argument("--high-column", default="high")
    parser.add_argument("--low-column", default="low")
    parser.add_argument("--volume-column", default="volume")
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
