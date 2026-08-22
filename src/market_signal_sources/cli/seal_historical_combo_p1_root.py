"""Seal supplied local historical-combo P1 members into a private root."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from market_signal_sources.artifacts.historical_combo_p1_root import (
    HistoricalComboP1RootError,
    publish_historical_combo_p1_root,
)


def _universe_source(value: str) -> tuple[str, Path]:
    decision_at, separator, source_path = value.partition("=")
    if not separator or not decision_at or not source_path:
        raise argparse.ArgumentTypeError("universe source must be DECISION_AT=PATH")
    return decision_at, Path(source_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seal already-acquired historical-combo P1 data into a new local immutable root. "
            "This command never downloads data or contacts a broker."
        )
    )
    parser.add_argument("--input", required=True, type=Path, help="validated historical-combo P1 input JSON")
    parser.add_argument("--price-panel", required=True, type=Path, help="already-acquired raw price-panel file")
    parser.add_argument("--quality-report", required=True, type=Path, help="quality-report file bound by the P1 input")
    parser.add_argument(
        "--universe-source",
        action="append",
        default=[],
        type=_universe_source,
        metavar="DECISION_AT=PATH",
        help="raw source file for one P1 rebalance decision; repeat for every decision",
    )
    parser.add_argument("--output-root", required=True, type=Path, help="fresh private root to create")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sources: dict[str, bytes] = {}
    try:
        for decision_at, path in args.universe_source:
            if decision_at in sources:
                raise HistoricalComboP1RootError("duplicate universe source decision")
            sources[decision_at] = path.read_bytes()
        result = publish_historical_combo_p1_root(
            combo_p1_input=json.loads(args.input.read_bytes()),
            price_panel_bytes=args.price_panel.read_bytes(),
            quality_report_bytes=args.quality_report.read_bytes(),
            universe_source_bytes=sources,
            output_root=args.output_root,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"historical combo P1 root was not published: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
