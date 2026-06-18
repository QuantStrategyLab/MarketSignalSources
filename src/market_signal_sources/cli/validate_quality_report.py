from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from market_signal_sources.artifacts.quality_report import (
    QualityReportValidationError,
    validate_ohlcv_quality_report_file,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        summary = validate_ohlcv_quality_report_file(
            args.quality_report,
            reject_fail_status=not args.allow_fail_status,
        )
    except (OSError, QualityReportValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a local market_signal_quality_report.v1 JSON artifact "
            "and print non-sensitive audit metadata."
        )
    )
    parser.add_argument("quality_report", type=Path)
    parser.add_argument(
        "--allow-fail-status",
        action="store_true",
        help="Allow quality_status=fail for offline inspection instead of publish gating.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
