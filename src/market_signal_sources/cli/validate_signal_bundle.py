from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from market_signal_sources.artifacts.validation import (
    SignalBundleValidationError,
    validate_signal_bundle_index,
    validate_signal_bundle_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.index is not None and args.manifest is not None:
            raise SignalBundleValidationError("provide either manifest or --index, not both")
        if args.index is not None:
            summary = validate_signal_bundle_index(
                args.index,
                as_of=args.as_of,
                bundle_id=args.bundle_id,
                expected_canonical_input=args.canonical_input,
            )
        elif args.manifest is not None:
            summary = validate_signal_bundle_manifest(
                args.manifest,
                expected_canonical_input=args.canonical_input,
            )
        else:
            raise SignalBundleValidationError("provide a manifest path or --index")
    except (OSError, SignalBundleValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a local market_signal_bundle.v1 manifest or index and "
            "print non-sensitive audit metadata."
        )
    )
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--index", type=Path, help="Resolve a manifest from a local bundle index.")
    parser.add_argument("--as-of", help="Select the latest index entry at or before this as_of date.")
    parser.add_argument("--bundle-id", help="Require a specific bundle_id from the index.")
    parser.add_argument("--canonical-input", default="derived_indicators")
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
