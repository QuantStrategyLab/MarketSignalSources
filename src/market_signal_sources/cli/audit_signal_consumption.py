from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.consumption import (
    audit_signal_consumption,
    runtime_signal_injection_plan,
    validate_consumption_audit_file,
    write_consumption_audit_artifact,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.validate_json is not None:
            if (
                args.consumer
                or args.platform_handoff_manifest
                or args.platform_handoff_index
                or args.research_handoff_manifest
                or args.as_of
                or args.output_json
                or args.runtime_injection_plan
                or args.require_all_known_families
                or args.require_all_known_consumers
            ):
                raise ValueError(
                    "provide --validate-json without consumer, handoff, output, "
                    "runtime-plan, or require-all options"
                )
            payload = validate_consumption_audit_file(args.validate_json)
        else:
            if args.output_json and args.runtime_injection_plan:
                raise ValueError(
                    "provide --output-json only for full consumption audit summaries"
                )
            payload = audit_signal_consumption(
                consumer=args.consumer,
                platform_handoff_manifest=args.platform_handoff_manifest,
                platform_handoff_index=args.platform_handoff_index,
                research_handoff_manifest=args.research_handoff_manifest,
                as_of=args.as_of,
                require_all_known_families=args.require_all_known_families,
                require_all_known_consumers=args.require_all_known_consumers,
            )
            if args.output_json:
                payload = write_consumption_audit_artifact(args.output_json, payload)
            elif args.runtime_injection_plan:
                payload = runtime_signal_injection_plan(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit one platform or research signal handoff for consumption."
    )
    parser.add_argument("--platform-handoff-manifest")
    parser.add_argument("--platform-handoff-index")
    parser.add_argument("--research-handoff-manifest")
    parser.add_argument(
        "--consumer",
        help="Explicit runtime or research consumer id to validate.",
    )
    parser.add_argument(
        "--output-json",
        help="Write the full consumption audit summary as a validated JSON artifact.",
    )
    parser.add_argument(
        "--validate-json",
        help="Validate a saved market_signal_consumption_audit.v1 JSON artifact.",
    )
    parser.add_argument(
        "--as-of",
        help="With --platform-handoff-index, select the latest handoff at or before this date.",
    )
    parser.add_argument(
        "--require-all-known-families",
        action="store_true",
        help="Require the source family catalog to include every known family.",
    )
    parser.add_argument(
        "--require-all-known-consumers",
        action="store_true",
        help="Require the consumer contract registry to include every known consumer.",
    )
    parser.add_argument(
        "--runtime-injection-plan",
        action="store_true",
        help=(
            "Print the minimal runtime injection plan instead of the full audit "
            "summary. Requires a runtime platform handoff."
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
