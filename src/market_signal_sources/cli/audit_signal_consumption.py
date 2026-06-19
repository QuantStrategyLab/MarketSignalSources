from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from market_signal_sources.artifacts.consumption import (
    audit_signal_consumption,
    runtime_signal_injection_plan,
    validate_consumption_audit_file,
    validate_runtime_adapter_config_file,
    validate_runtime_signal_injection_plan_file,
    validate_runtime_signal_injection_plan_matches_audit,
    write_consumption_audit_artifact,
    write_runtime_signal_injection_plan_artifact,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        validation_modes = (
            args.validate_json,
            args.validate_runtime_adapter_config_json,
            args.validate_runtime_plan_json,
            args.validate_runtime_plan_with_audit,
        )
        if any(value is not None for value in validation_modes):
            if sum(value is not None for value in validation_modes) != 1:
                raise ValueError(
                    "provide only one validation mode"
                )
            if (
                args.consumer
                or args.platform_handoff_manifest
                or args.platform_handoff_index
                or args.research_handoff_manifest
                or args.as_of
                or args.output_json
                or args.output_runtime_plan_json
                or args.runtime_injection_plan
                or args.require_all_known_families
                or args.require_all_known_consumers
            ):
                raise ValueError(
                    "provide validation without consumer, handoff, output, "
                    "runtime-plan, or require-all options"
            )
            if args.validate_json is not None:
                if args.audit_json is not None:
                    raise ValueError(
                        "--audit-json requires --validate-runtime-plan-with-audit"
                    )
                payload = validate_consumption_audit_file(args.validate_json)
            elif args.validate_runtime_adapter_config_json is not None:
                if args.audit_json is not None:
                    raise ValueError(
                        "--audit-json requires --validate-runtime-plan-with-audit"
                    )
                payload = validate_runtime_adapter_config_file(
                    args.validate_runtime_adapter_config_json
                )
            elif args.validate_runtime_plan_json is not None:
                if args.audit_json is not None:
                    raise ValueError(
                        "--audit-json requires --validate-runtime-plan-with-audit"
                    )
                payload = validate_runtime_signal_injection_plan_file(
                    args.validate_runtime_plan_json
                )
            else:
                if args.audit_json is None:
                    raise ValueError(
                        "--validate-runtime-plan-with-audit requires --audit-json"
                    )
                payload = validate_runtime_signal_injection_plan_matches_audit(
                    args.validate_runtime_plan_with_audit,
                    args.audit_json,
                )
        else:
            if args.audit_json is not None:
                raise ValueError(
                    "--audit-json requires --validate-runtime-plan-with-audit"
                )
            if args.output_json and args.runtime_injection_plan:
                raise ValueError(
                    "provide --output-json only for full consumption audit summaries"
                )
            if args.output_json and args.output_runtime_plan_json:
                raise ValueError(
                    "provide either --output-json or --output-runtime-plan-json, not both"
                )
            if args.output_runtime_plan_json and args.runtime_injection_plan:
                raise ValueError(
                    "provide either --runtime-injection-plan or "
                    "--output-runtime-plan-json, not both"
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
            elif args.output_runtime_plan_json:
                payload = write_runtime_signal_injection_plan_artifact(
                    args.output_runtime_plan_json,
                    runtime_signal_injection_plan(payload),
                )
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
        "--validate-runtime-adapter-config-json",
        help="Validate a saved market_signal_runtime_adapter_config.v1 JSON file.",
    )
    parser.add_argument(
        "--output-runtime-plan-json",
        help=(
            "Write the minimal runtime injection plan as a validated JSON artifact. "
            "Requires a runtime platform handoff."
        ),
    )
    parser.add_argument(
        "--validate-runtime-plan-json",
        help="Validate a saved market_signal_runtime_injection_plan.v1 JSON artifact.",
    )
    parser.add_argument(
        "--validate-runtime-plan-with-audit",
        help=(
            "Validate a saved runtime injection plan and confirm it matches a "
            "saved consumption audit artifact."
        ),
    )
    parser.add_argument(
        "--audit-json",
        help=(
            "Saved market_signal_consumption_audit.v1 JSON artifact for plan "
            "matching."
        ),
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
