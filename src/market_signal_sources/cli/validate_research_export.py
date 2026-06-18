from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from market_signal_sources.artifacts.validation import (
    SignalBundleValidationError,
    validate_research_export_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        summary = validate_research_export_manifest(
            args.manifest,
            expected_artifact_type=args.expected_artifact_type,
            expected_transform=args.expected_transform,
        )
    except (OSError, SignalBundleValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a local research_export.v1 manifest and its linked CSV hashes."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-artifact-type")
    parser.add_argument("--expected-transform")
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
