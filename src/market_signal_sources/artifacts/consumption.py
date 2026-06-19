from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import known_signal_consumers
from .platform_handoff import (
    validate_platform_signal_handoff_index,
    validate_platform_signal_handoff_manifest,
)
from .research_handoff import validate_research_signal_handoff_manifest
from .signal_bundle import CANONICAL_INPUT_DERIVED_INDICATORS, FRESHNESS_FRESH


MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION = "market_signal_consumption_audit.v1"
MARKET_SIGNAL_RUNTIME_INJECTION_PLAN_SCHEMA_VERSION = (
    "market_signal_runtime_injection_plan.v1"
)
MARKET_SIGNAL_RUNTIME_PLAN_AUDIT_MATCH_SCHEMA_VERSION = (
    "market_signal_runtime_plan_audit_match.v1"
)
MARKET_SIGNAL_RUNTIME_ADAPTER_CONFIG_SCHEMA_VERSION = (
    "market_signal_runtime_adapter_config.v1"
)
MARKET_SIGNAL_RUNTIME_ADAPTER_CONFIG_SET_SCHEMA_VERSION = (
    "market_signal_runtime_adapter_config_set.v1"
)
MARKET_SIGNAL_RUNTIME_ADAPTER_DEPLOYMENT_SCHEMA_VERSION = (
    "market_signal_runtime_adapter_deployment.v1"
)
MARKET_SIGNAL_RUNTIME_ADAPTER_DEPLOYMENT_SET_SCHEMA_VERSION = (
    "market_signal_runtime_adapter_deployment_set.v1"
)
_ARTIFACT_TYPE = "market_signal_consumption_audit"
_INJECTION_PLAN_ARTIFACT_TYPE = "market_signal_runtime_injection_plan"
_PLAN_AUDIT_MATCH_ARTIFACT_TYPE = "market_signal_runtime_plan_audit_match"
_ADAPTER_CONFIG_VALIDATION_ARTIFACT_TYPE = (
    "market_signal_runtime_adapter_config_validation"
)
_ADAPTER_CONFIG_SET_VALIDATION_ARTIFACT_TYPE = (
    "market_signal_runtime_adapter_config_set_validation"
)
_ADAPTER_DEPLOYMENT_VALIDATION_ARTIFACT_TYPE = (
    "market_signal_runtime_adapter_deployment_validation"
)
_ADAPTER_DEPLOYMENT_SET_VALIDATION_ARTIFACT_TYPE = (
    "market_signal_runtime_adapter_deployment_set_validation"
)
_FORBIDDEN_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "signed_url",
        "token",
    }
)
_RUNTIME_AUDIT_IDENTITY_FIELDS = (
    "handoff_source",
    "consumer",
    "canonical_input",
    "bundle_id",
    "as_of",
    "freshness_status",
    "runtime_market_data_key",
    "runtime_payload_field",
    "handoff_manifest_sha256",
    "signal_bundle_manifest_sha256",
    "source_family_catalog_manifest_sha256",
    "consumer_contract_registry_manifest_sha256",
    "source_families",
    "matched_source_families",
    "consumer_contracts",
    "all_runtime_consumers_covered",
)


def audit_signal_consumption(
    *,
    consumer: str,
    platform_handoff_manifest: str | PathLike[str] | None = None,
    platform_handoff_index: str | PathLike[str] | None = None,
    research_handoff_manifest: str | PathLike[str] | None = None,
    as_of: str | None = None,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
    require_runtime_consumer_coverage: bool = False,
) -> dict[str, Any]:
    """Validate exactly one handoff source for an explicit downstream consumer."""

    target_consumer = str(consumer or "").strip()
    if not target_consumer:
        raise ValueError("consumer is required for signal consumption audit")
    sources = {
        "platform_handoff_manifest": platform_handoff_manifest,
        "platform_handoff_index": platform_handoff_index,
        "research_handoff_manifest": research_handoff_manifest,
    }
    selected_sources = tuple(name for name, value in sources.items() if value is not None)
    if len(selected_sources) != 1:
        raise ValueError(
            "provide exactly one of platform_handoff_manifest, "
            "platform_handoff_index, or research_handoff_manifest"
        )

    selected_source = selected_sources[0]
    if selected_source == "platform_handoff_manifest":
        assert platform_handoff_manifest is not None
        summary = validate_platform_signal_handoff_manifest(
            platform_handoff_manifest,
            consumer=target_consumer,
            require_all_known_families=require_all_known_families,
            require_all_known_consumers=require_all_known_consumers,
            require_runtime_consumer_coverage=require_runtime_consumer_coverage,
            expected_canonical_input=expected_canonical_input,
            accepted_freshness_statuses=accepted_freshness_statuses,
        )
        return _runtime_consumption_audit(
            summary,
            handoff_source=selected_source,
        )

    if selected_source == "platform_handoff_index":
        assert platform_handoff_index is not None
        summary = validate_platform_signal_handoff_index(
            platform_handoff_index,
            consumer=target_consumer,
            expected_canonical_input=expected_canonical_input,
            as_of=as_of,
            accepted_freshness_statuses=accepted_freshness_statuses,
            require_all_known_families=require_all_known_families,
            require_all_known_consumers=require_all_known_consumers,
            require_runtime_consumer_coverage=require_runtime_consumer_coverage,
        )
        return _runtime_consumption_audit(
            summary,
            handoff_source=selected_source,
            lookup_as_of=as_of,
        )

    assert research_handoff_manifest is not None
    summary = validate_research_signal_handoff_manifest(
        research_handoff_manifest,
        consumer=target_consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
    )
    return _research_consumption_audit(summary)


def runtime_signal_injection_plan(audit_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Build the minimal platform injection plan from a runtime audit summary."""

    if (
        str(audit_summary.get("schema_version", ""))
        != MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION
    ):
        raise ValueError(
            "runtime injection plan requires a market_signal_consumption_audit.v1 "
            "summary"
        )
    if (
        audit_summary.get("ready_for_runtime_injection") is not True
        or audit_summary.get("runtime_injection_allowed") is not True
    ):
        raise ValueError("consumption audit is not runtime-injectable")
    market_data_key = _required_string(audit_summary, "runtime_market_data_key")
    payload_field = _required_string(audit_summary, "runtime_payload_field")
    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_INJECTION_PLAN_SCHEMA_VERSION,
        "artifact_type": _INJECTION_PLAN_ARTIFACT_TYPE,
        "consumer": _required_string(audit_summary, "consumer"),
        "injection_allowed": True,
        "market_data_key": market_data_key,
        "payload_field": payload_field,
        "target_path": f"market_data.{market_data_key}",
        "canonical_input": _required_string(audit_summary, "canonical_input"),
        "bundle_id": _required_string(audit_summary, "bundle_id"),
        "as_of": _required_string(audit_summary, "as_of"),
        "freshness_status": _required_string(audit_summary, "freshness_status"),
        "signal_bundle_manifest_path": _required_string(
            audit_summary,
            "signal_bundle_manifest_path",
        ),
        "signal_bundle_manifest_sha256": _required_string(
            audit_summary,
            "signal_bundle_manifest_sha256",
        ),
        "handoff_manifest_path": _required_string(
            audit_summary,
            "handoff_manifest_path",
        ),
        "handoff_manifest_sha256": _required_string(
            audit_summary,
            "handoff_manifest_sha256",
        ),
        "source_family_catalog_manifest_sha256": _required_string(
            audit_summary,
            "source_family_catalog_manifest_sha256",
        ),
        "consumer_contract_registry_manifest_sha256": _required_string(
            audit_summary,
            "consumer_contract_registry_manifest_sha256",
        ),
        "source_families": tuple(audit_summary.get("source_families", ())),
        "matched_source_families": tuple(
            audit_summary.get("matched_source_families", ())
        ),
        "consumer_contracts": tuple(audit_summary.get("consumer_contracts", ())),
    }


def validate_runtime_adapter_config(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a platform runtime signal adapter configuration mapping."""

    _reject_sensitive_keys(config)
    schema_version = str(config.get("schema_version", "")).strip()
    if schema_version and schema_version != MARKET_SIGNAL_RUNTIME_ADAPTER_CONFIG_SCHEMA_VERSION:
        raise ValueError("runtime adapter config schema_version mismatch")
    consumer = _required_config_string(config, "signal_consumer")
    if consumer.startswith("research:"):
        raise ValueError("runtime adapter config cannot use research consumer")
    handoff_index = _optional_config_string(config, "signal_handoff_index")
    handoff_manifest = _optional_config_string(config, "signal_handoff_manifest")
    if bool(handoff_index) == bool(handoff_manifest):
        raise ValueError(
            "runtime adapter config must provide exactly one handoff lookup"
        )
    as_of = _optional_config_string(config, "signal_as_of")
    if handoff_index and not as_of:
        raise ValueError("runtime adapter config index lookup requires signal_as_of")
    freshness_statuses = _freshness_statuses_from_config(config)
    saved_audit = _optional_config_string(config, "saved_consumption_audit_json")
    saved_plan = _optional_config_string(config, "saved_runtime_plan_json")
    if saved_plan and not saved_audit:
        raise ValueError(
            "runtime adapter config saved_runtime_plan_json requires "
            "saved_consumption_audit_json"
        )
    handoff_source = (
        "platform_handoff_index"
        if handoff_index
        else "platform_handoff_manifest"
    )
    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_ADAPTER_CONFIG_SCHEMA_VERSION,
        "artifact_type": _ADAPTER_CONFIG_VALIDATION_ARTIFACT_TYPE,
        "valid": True,
        "strategy": _optional_config_string(config, "strategy"),
        "consumer": consumer,
        "handoff_source": handoff_source,
        "handoff_path": handoff_index or handoff_manifest,
        "as_of": as_of,
        "accepted_freshness_statuses": freshness_statuses,
        "saved_consumption_audit_json": saved_audit,
        "saved_runtime_plan_json": saved_plan,
        "runtime_plan_requires_audit_match": bool(saved_plan),
    }


def validate_runtime_adapter_config_file(
    path: str | PathLike[str],
) -> dict[str, Any]:
    """Validate a saved market_signal_runtime_adapter_config.v1 JSON config."""

    config_path = Path(path)
    payload = _load_json_mapping(
        config_path,
        artifact_name="runtime adapter config",
    )
    summary = validate_runtime_adapter_config(payload)
    return {
        **summary,
        "path": str(config_path),
        "sha256": _sha256_file(config_path),
        "size_bytes": config_path.stat().st_size,
    }


def validate_runtime_adapter_config_set_files(
    paths: Iterable[str | PathLike[str]],
    *,
    require_all_known_runtime_consumers: bool = False,
) -> dict[str, Any]:
    """Validate a platform runtime adapter config set and consumer coverage."""

    config_paths = tuple(Path(path) for path in paths)
    if not config_paths:
        raise ValueError("runtime adapter config set requires at least one config")
    summaries = tuple(
        validate_runtime_adapter_config_file(config_path)
        for config_path in config_paths
    )
    consumers = tuple(str(summary["consumer"]) for summary in summaries)
    duplicates = sorted(
        consumer for consumer in set(consumers) if consumers.count(consumer) > 1
    )
    if duplicates:
        raise ValueError(
            "runtime adapter config set duplicate consumers: "
            + ", ".join(duplicates)
        )
    known_runtime_consumers = _known_runtime_signal_consumers()
    missing_known_runtime_consumers = sorted(
        set(known_runtime_consumers) - set(consumers)
    )
    if require_all_known_runtime_consumers and missing_known_runtime_consumers:
        raise ValueError(
            "runtime adapter config set missing known runtime consumers: "
            + ", ".join(missing_known_runtime_consumers)
        )
    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_ADAPTER_CONFIG_SET_SCHEMA_VERSION,
        "artifact_type": _ADAPTER_CONFIG_SET_VALIDATION_ARTIFACT_TYPE,
        "valid": True,
        "config_count": len(summaries),
        "consumers": consumers,
        "known_runtime_consumer_count": len(known_runtime_consumers),
        "known_runtime_consumers": known_runtime_consumers,
        "missing_known_runtime_consumers": tuple(missing_known_runtime_consumers),
        "all_known_runtime_consumers_present": not missing_known_runtime_consumers,
        "configs": summaries,
    }


def validate_runtime_adapter_deployment_config_file(
    path: str | PathLike[str],
) -> dict[str, Any]:
    """Validate runtime adapter config plus its saved deployment artifacts."""

    config_path = Path(path)
    payload = _load_json_mapping(
        config_path,
        artifact_name="runtime adapter config",
    )
    config_summary = validate_runtime_adapter_config(payload)
    saved_audit = str(config_summary.get("saved_consumption_audit_json", "")).strip()
    if not saved_audit:
        raise ValueError(
            "runtime adapter deployment requires saved_consumption_audit_json"
        )
    audit_path = _config_relative_path(config_path, saved_audit)
    audit_summary = validate_consumption_audit_file(audit_path)
    audit_payload = _load_json_mapping(
        audit_path,
        artifact_name="consumption audit",
    )
    if config_summary["consumer"] != audit_summary["consumer"]:
        raise ValueError("runtime adapter deployment consumer mismatch")
    if config_summary["handoff_source"] != audit_payload.get("handoff_source"):
        raise ValueError("runtime adapter deployment handoff_source mismatch")
    config_handoff_path = _config_relative_path(
        config_path,
        str(config_summary["handoff_path"]),
    )
    audit_handoff_path = _audit_handoff_path(
        config_path,
        str(config_summary["handoff_source"]),
        audit_payload,
    )
    if _normalized_path(config_handoff_path) != _normalized_path(audit_handoff_path):
        raise ValueError("runtime adapter deployment handoff path mismatch")
    saved_lookup_as_of = str(audit_payload.get("lookup_as_of", "") or "").strip()
    if saved_lookup_as_of and config_summary["as_of"] != saved_lookup_as_of:
        raise ValueError("runtime adapter deployment lookup_as_of mismatch")
    if audit_payload.get("freshness_status") not in config_summary[
        "accepted_freshness_statuses"
    ]:
        raise ValueError("runtime adapter deployment freshness_status mismatch")
    current_audit = _current_runtime_consumption_audit(
        config_path=config_path,
        config_summary=config_summary,
    )
    current_audit_mismatches = _runtime_audit_identity_mismatches(
        saved_audit=audit_payload,
        current_audit=current_audit,
    )
    if current_audit_mismatches:
        raise ValueError(
            "runtime adapter deployment current audit mismatch: "
            + ", ".join(current_audit_mismatches)
        )

    saved_plan = str(config_summary.get("saved_runtime_plan_json", "")).strip()
    plan_match_summary: dict[str, Any] | None = None
    if saved_plan:
        plan_path = _config_relative_path(config_path, saved_plan)
        plan_match_summary = validate_runtime_signal_injection_plan_matches_audit(
            plan_path,
            audit_path,
        )

    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_ADAPTER_DEPLOYMENT_SCHEMA_VERSION,
        "artifact_type": _ADAPTER_DEPLOYMENT_VALIDATION_ARTIFACT_TYPE,
        "valid": True,
        "config_path": str(config_path),
        "config_sha256": _sha256_file(config_path),
        "strategy": config_summary.get("strategy", ""),
        "consumer": config_summary["consumer"],
        "handoff_source": config_summary["handoff_source"],
        "handoff_path": str(config_handoff_path),
        "audit_handoff_path": str(audit_handoff_path),
        "as_of": audit_payload["as_of"],
        "freshness_status": audit_payload["freshness_status"],
        "accepted_freshness_statuses": config_summary[
            "accepted_freshness_statuses"
        ],
        "audit_path": str(audit_path),
        "audit_sha256": audit_summary["sha256"],
        "current_audit_matched": True,
        "current_handoff_manifest_sha256": current_audit[
            "handoff_manifest_sha256"
        ],
        "current_signal_bundle_manifest_sha256": current_audit[
            "signal_bundle_manifest_sha256"
        ],
        "runtime_plan_matched": bool(plan_match_summary),
        "runtime_plan_path": (
            str(_config_relative_path(config_path, saved_plan))
            if saved_plan
            else ""
        ),
        "runtime_plan_sha256": (
            str(plan_match_summary["plan_sha256"])
            if plan_match_summary is not None
            else ""
        ),
    }


def validate_runtime_adapter_deployment_config_set_files(
    paths: Iterable[str | PathLike[str]],
    *,
    require_all_known_runtime_consumers: bool = False,
) -> dict[str, Any]:
    """Validate runtime adapter deployment configs and consumer coverage."""

    config_paths = tuple(Path(path) for path in paths)
    if not config_paths:
        raise ValueError(
            "runtime adapter deployment config set requires at least one config"
        )
    summaries = tuple(
        validate_runtime_adapter_deployment_config_file(config_path)
        for config_path in config_paths
    )
    consumers = tuple(str(summary["consumer"]) for summary in summaries)
    duplicates = sorted(
        consumer for consumer in set(consumers) if consumers.count(consumer) > 1
    )
    if duplicates:
        raise ValueError(
            "runtime adapter deployment config set duplicate consumers: "
            + ", ".join(duplicates)
        )
    known_runtime_consumers = _known_runtime_signal_consumers()
    missing_known_runtime_consumers = sorted(
        set(known_runtime_consumers) - set(consumers)
    )
    if require_all_known_runtime_consumers and missing_known_runtime_consumers:
        raise ValueError(
            "runtime adapter deployment config set missing known runtime consumers: "
            + ", ".join(missing_known_runtime_consumers)
        )
    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_ADAPTER_DEPLOYMENT_SET_SCHEMA_VERSION,
        "artifact_type": _ADAPTER_DEPLOYMENT_SET_VALIDATION_ARTIFACT_TYPE,
        "valid": True,
        "config_count": len(summaries),
        "consumers": consumers,
        "known_runtime_consumer_count": len(known_runtime_consumers),
        "known_runtime_consumers": known_runtime_consumers,
        "missing_known_runtime_consumers": tuple(missing_known_runtime_consumers),
        "all_known_runtime_consumers_present": not missing_known_runtime_consumers,
        "deployments": summaries,
    }


def write_runtime_signal_injection_plan_artifact(
    path: str | PathLike[str],
    injection_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Write a validated runtime injection plan JSON artifact and return metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_runtime_injection_plan_payload(injection_plan)
    output_path.write_text(
        json.dumps(_json_safe_value(injection_plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_runtime_signal_injection_plan_file(output_path)


def validate_runtime_signal_injection_plan_file(
    path: str | PathLike[str],
) -> dict[str, Any]:
    """Validate a saved market_signal_runtime_injection_plan.v1 JSON artifact."""

    plan_path = Path(path)
    with plan_path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, Mapping):
        raise ValueError("runtime injection plan artifact must be a JSON object")
    _validate_runtime_injection_plan_payload(payload)
    return {
        "path": str(plan_path),
        "schema_version": payload["schema_version"],
        "artifact_type": payload["artifact_type"],
        "consumer": payload["consumer"],
        "injection_allowed": payload["injection_allowed"],
        "market_data_key": payload["market_data_key"],
        "payload_field": payload["payload_field"],
        "target_path": payload["target_path"],
        "canonical_input": payload["canonical_input"],
        "bundle_id": payload["bundle_id"],
        "as_of": payload["as_of"],
        "freshness_status": payload["freshness_status"],
        "sha256": _sha256_file(plan_path),
        "size_bytes": plan_path.stat().st_size,
    }


def validate_runtime_signal_injection_plan_matches_audit(
    plan_path: str | PathLike[str],
    audit_path: str | PathLike[str],
) -> dict[str, Any]:
    """Validate a runtime injection plan against its source consumption audit."""

    resolved_plan_path = Path(plan_path)
    resolved_audit_path = Path(audit_path)
    plan_summary = validate_runtime_signal_injection_plan_file(resolved_plan_path)
    audit_summary = validate_consumption_audit_file(resolved_audit_path)
    plan_payload = _load_json_mapping(
        resolved_plan_path,
        artifact_name="runtime injection plan",
    )
    audit_payload = _load_json_mapping(
        resolved_audit_path,
        artifact_name="consumption audit",
    )
    if (
        audit_payload.get("ready_for_runtime_injection") is not True
        or audit_payload.get("runtime_injection_allowed") is not True
    ):
        raise ValueError("consumption audit is not runtime-injectable")
    for plan_field, audit_field in _PLAN_AUDIT_MATCH_FIELDS:
        if plan_payload.get(plan_field) != audit_payload.get(audit_field):
            raise ValueError(
                "runtime injection plan audit mismatch: "
                f"{plan_field}!={audit_field}"
            )
    return {
        "schema_version": MARKET_SIGNAL_RUNTIME_PLAN_AUDIT_MATCH_SCHEMA_VERSION,
        "artifact_type": _PLAN_AUDIT_MATCH_ARTIFACT_TYPE,
        "matched": True,
        "plan_path": plan_summary["path"],
        "audit_path": audit_summary["path"],
        "plan_sha256": plan_summary["sha256"],
        "audit_sha256": audit_summary["sha256"],
        "consumer": plan_summary["consumer"],
        "market_data_key": plan_summary["market_data_key"],
        "payload_field": plan_summary["payload_field"],
        "target_path": plan_summary["target_path"],
        "canonical_input": plan_summary["canonical_input"],
        "bundle_id": plan_summary["bundle_id"],
        "as_of": plan_summary["as_of"],
        "freshness_status": plan_summary["freshness_status"],
    }


def write_consumption_audit_artifact(
    path: str | PathLike[str],
    audit_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Write a validated consumption audit JSON artifact and return metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_consumption_audit_payload(audit_summary)
    output_path.write_text(
        json.dumps(_json_safe_value(audit_summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_consumption_audit_file(output_path)


def validate_consumption_audit_file(
    path: str | PathLike[str],
) -> dict[str, Any]:
    """Validate a saved market_signal_consumption_audit.v1 JSON artifact."""

    audit_path = Path(path)
    with audit_path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, Mapping):
        raise ValueError("consumption audit artifact must be a JSON object")
    _validate_consumption_audit_payload(payload)
    return {
        "path": str(audit_path),
        "schema_version": payload["schema_version"],
        "artifact_type": payload["artifact_type"],
        "consumption_mode": payload["consumption_mode"],
        "consumer": payload["consumer"],
        "ready_for_consumption": payload["ready_for_consumption"],
        "ready_for_runtime_injection": payload["ready_for_runtime_injection"],
        "ready_for_research_consumption": payload[
            "ready_for_research_consumption"
        ],
        "runtime_injection_allowed": payload["runtime_injection_allowed"],
        "linked_manifest_sha256s_verified": payload[
            "linked_manifest_sha256s_verified"
        ],
        "lookup_as_of": str(payload.get("lookup_as_of", "") or ""),
        "all_runtime_consumers_covered": bool(
            payload.get("all_runtime_consumers_covered", False)
        ),
        "sha256": _sha256_file(audit_path),
        "size_bytes": audit_path.stat().st_size,
    }


def _runtime_consumption_audit(
    summary: dict[str, Any],
    *,
    handoff_source: str,
    lookup_as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION,
        "artifact_type": _ARTIFACT_TYPE,
        "consumption_mode": "runtime_platform",
        "handoff_source": handoff_source,
        "consumer": summary["consumer"],
        "consumer_role": "runtime",
        "ready_for_consumption": True,
        "ready_for_runtime_injection": True,
        "ready_for_research_consumption": False,
        "runtime_injection_allowed": True,
        "research_csv_runtime_injection_allowed": False,
        "runtime_market_data_key": _market_data_key_for_canonical_input(
            str(summary["canonical_input"])
        ),
        "runtime_payload_field": summary["canonical_input"],
        "canonical_input": summary["canonical_input"],
        "bundle_id": summary["bundle_id"],
        "as_of": summary["as_of"],
        "freshness_status": summary["freshness_status"],
        "handoff_manifest_path": summary.get("handoff_manifest_path", summary["path"]),
        "handoff_manifest_sha256": summary.get(
            "handoff_manifest_sha256",
            summary["sha256"],
        ),
        "index_path": summary.get("index_path", ""),
        "index_handoff_count": summary.get("index_handoff_count", 0),
        "lookup_as_of": str(lookup_as_of or ""),
        "signal_bundle_manifest_path": summary["signal_bundle_manifest_path"],
        "signal_bundle_manifest_sha256": summary["signal_bundle_manifest_sha256"],
        "source_family_catalog_manifest_path": summary[
            "source_family_catalog_manifest_path"
        ],
        "source_family_catalog_manifest_sha256": summary[
            "source_family_catalog_manifest_sha256"
        ],
        "consumer_contract_registry_manifest_path": summary[
            "consumer_contract_registry_manifest_path"
        ],
        "consumer_contract_registry_manifest_sha256": summary[
            "consumer_contract_registry_manifest_sha256"
        ],
        "source_family_count": summary["source_family_count"],
        "source_families": summary["source_families"],
        "matched_source_family_count": summary.get("matched_source_family_count", 0),
        "matched_source_families": summary.get("matched_source_families", ()),
        "all_known_source_families_present": summary[
            "all_known_source_families_present"
        ],
        "all_consumer_contracts_satisfied": summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": bool(
            summary.get("all_runtime_consumers_covered", False)
        ),
        "consumer_contract_count": summary["consumer_contract_count"],
        "consumer_contracts": summary["consumer_contracts"],
        "all_known_consumers_present": summary["all_known_consumers_present"],
        "linked_manifest_sha256s_verified": True,
        "consumer_contract_verified": True,
        "source_catalog_verified": True,
    }


def _research_consumption_audit(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION,
        "artifact_type": _ARTIFACT_TYPE,
        "consumption_mode": "offline_research",
        "handoff_source": "research_handoff_manifest",
        "consumer": summary["consumer"],
        "consumer_role": "research",
        "ready_for_consumption": True,
        "ready_for_runtime_injection": False,
        "ready_for_research_consumption": True,
        "runtime_injection_allowed": False,
        "research_csv_runtime_injection_allowed": False,
        "research_export_manifest_path": summary["research_export_manifest_path"],
        "research_export_manifest_sha256": summary[
            "research_export_manifest_sha256"
        ],
        "research_artifact_type": summary["research_artifact_type"],
        "research_transform": summary["research_transform"],
        "research_as_of": summary["research_as_of"],
        "research_output_csv_sha256": summary["research_output_csv_sha256"],
        "research_quality_report_sha256": summary[
            "research_quality_report_sha256"
        ],
        "handoff_manifest_path": summary["path"],
        "handoff_manifest_sha256": summary["sha256"],
        "source_family_catalog_manifest_path": summary[
            "source_family_catalog_manifest_path"
        ],
        "source_family_catalog_manifest_sha256": summary[
            "source_family_catalog_manifest_sha256"
        ],
        "consumer_contract_registry_manifest_path": summary[
            "consumer_contract_registry_manifest_path"
        ],
        "consumer_contract_registry_manifest_sha256": summary[
            "consumer_contract_registry_manifest_sha256"
        ],
        "source_family_count": summary["source_family_count"],
        "source_families": summary["source_families"],
        "all_known_source_families_present": summary[
            "all_known_source_families_present"
        ],
        "all_consumer_contracts_satisfied": summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": bool(
            summary.get("all_runtime_consumers_covered", False)
        ),
        "consumer_contract_count": summary["consumer_contract_count"],
        "consumer_contracts": summary["consumer_contracts"],
        "all_known_consumers_present": summary["all_known_consumers_present"],
        "linked_manifest_sha256s_verified": True,
        "consumer_contract_verified": True,
        "source_catalog_verified": True,
        "summary_verified": summary["summary_verified"],
    }


def _market_data_key_for_canonical_input(canonical_input: str) -> str:
    if canonical_input == CANONICAL_INPUT_DERIVED_INDICATORS:
        return "derived_indicators"
    return canonical_input


_PLAN_AUDIT_MATCH_FIELDS = (
    ("consumer", "consumer"),
    ("canonical_input", "canonical_input"),
    ("bundle_id", "bundle_id"),
    ("as_of", "as_of"),
    ("freshness_status", "freshness_status"),
    ("signal_bundle_manifest_path", "signal_bundle_manifest_path"),
    ("signal_bundle_manifest_sha256", "signal_bundle_manifest_sha256"),
    ("handoff_manifest_path", "handoff_manifest_path"),
    ("handoff_manifest_sha256", "handoff_manifest_sha256"),
    (
        "source_family_catalog_manifest_sha256",
        "source_family_catalog_manifest_sha256",
    ),
    (
        "consumer_contract_registry_manifest_sha256",
        "consumer_contract_registry_manifest_sha256",
    ),
    ("market_data_key", "runtime_market_data_key"),
    ("payload_field", "runtime_payload_field"),
    ("source_families", "source_families"),
    ("matched_source_families", "matched_source_families"),
    ("consumer_contracts", "consumer_contracts"),
)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValueError(f"consumption audit missing required field: {field}")
    return value


def _required_config_string(payload: Mapping[str, Any], field: str) -> str:
    value = _optional_config_string(payload, field)
    if not value:
        raise ValueError(f"runtime adapter config missing required field: {field}")
    return value


def _optional_config_string(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field, "") or "").strip()
    return value


def _freshness_statuses_from_config(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw_value = payload.get("accepted_freshness_statuses")
    if not isinstance(raw_value, list | tuple):
        raise ValueError(
            "runtime adapter config accepted_freshness_statuses must be a list"
        )
    statuses = tuple(str(value or "").strip() for value in raw_value)
    if not statuses or any(not value for value in statuses):
        raise ValueError(
            "runtime adapter config accepted_freshness_statuses must be non-empty"
        )
    return statuses


def _config_relative_path(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _current_runtime_consumption_audit(
    *,
    config_path: Path,
    config_summary: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_path = _config_relative_path(
        config_path,
        str(config_summary["handoff_path"]),
    )
    handoff_source = str(config_summary["handoff_source"])
    if handoff_source == "platform_handoff_index":
        return audit_signal_consumption(
            consumer=str(config_summary["consumer"]),
            platform_handoff_index=handoff_path,
            as_of=str(config_summary.get("as_of", "")),
            accepted_freshness_statuses=config_summary[
                "accepted_freshness_statuses"
            ],
        )
    if handoff_source == "platform_handoff_manifest":
        return audit_signal_consumption(
            consumer=str(config_summary["consumer"]),
            platform_handoff_manifest=handoff_path,
            accepted_freshness_statuses=config_summary[
                "accepted_freshness_statuses"
            ],
        )
    raise ValueError(f"unsupported runtime adapter handoff_source: {handoff_source}")


def _runtime_audit_identity_mismatches(
    *,
    saved_audit: Mapping[str, Any],
    current_audit: Mapping[str, Any],
) -> tuple[str, ...]:
    mismatches = [
        field
        for field in _RUNTIME_AUDIT_IDENTITY_FIELDS
        if _normalized_identity_value(saved_audit.get(field))
        != _normalized_identity_value(current_audit.get(field))
    ]
    return tuple(mismatches)


def _normalized_identity_value(value: object) -> object:
    if isinstance(value, list | tuple):
        return tuple(_normalized_identity_value(item) for item in value)
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _normalized_identity_value(nested))
            for key, nested in sorted(value.items())
        )
    return value


def _known_runtime_signal_consumers() -> tuple[str, ...]:
    return tuple(
        consumer
        for consumer in known_signal_consumers()
        if not consumer.startswith("research:")
    )


def _audit_handoff_path(
    config_path: Path,
    handoff_source: str,
    audit_payload: Mapping[str, Any],
) -> Path:
    audit_field = (
        "index_path"
        if handoff_source == "platform_handoff_index"
        else "handoff_manifest_path"
    )
    raw_path = str(audit_payload.get(audit_field, "") or "").strip()
    if not raw_path:
        raise ValueError("runtime adapter deployment audit handoff path missing")
    return _config_relative_path(config_path, raw_path)


def _normalized_path(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _validate_consumption_audit_payload(payload: Mapping[str, Any]) -> None:
    _reject_sensitive_keys(payload)
    if payload.get("schema_version") != MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION:
        raise ValueError("consumption audit schema_version mismatch")
    if payload.get("artifact_type") != _ARTIFACT_TYPE:
        raise ValueError("consumption audit artifact_type mismatch")
    mode = _required_string(payload, "consumption_mode")
    if mode == "runtime_platform":
        _validate_runtime_consumption_audit(payload)
    elif mode == "offline_research":
        _validate_research_consumption_audit(payload)
    else:
        raise ValueError(f"unknown consumption audit mode: {mode}")
    if payload.get("linked_manifest_sha256s_verified") is not True:
        raise ValueError("consumption audit linked manifest hashes are not verified")
    if payload.get("consumer_contract_verified") is not True:
        raise ValueError("consumption audit consumer contract is not verified")
    if payload.get("source_catalog_verified") is not True:
        raise ValueError("consumption audit source catalog is not verified")


def _validate_runtime_injection_plan_payload(payload: Mapping[str, Any]) -> None:
    _reject_sensitive_keys(payload)
    if (
        payload.get("schema_version")
        != MARKET_SIGNAL_RUNTIME_INJECTION_PLAN_SCHEMA_VERSION
    ):
        raise ValueError("runtime injection plan schema_version mismatch")
    if payload.get("artifact_type") != _INJECTION_PLAN_ARTIFACT_TYPE:
        raise ValueError("runtime injection plan artifact_type mismatch")
    if payload.get("injection_allowed") is not True:
        raise ValueError("runtime injection plan does not allow injection")
    for field in (
        "consumer",
        "market_data_key",
        "payload_field",
        "target_path",
        "canonical_input",
        "bundle_id",
        "as_of",
        "freshness_status",
        "signal_bundle_manifest_path",
        "handoff_manifest_path",
    ):
        _required_string(payload, field)
    for field in (
        "signal_bundle_manifest_sha256",
        "handoff_manifest_sha256",
        "source_family_catalog_manifest_sha256",
        "consumer_contract_registry_manifest_sha256",
    ):
        _required_sha256(payload, field)
    expected_target_path = f"market_data.{_required_string(payload, 'market_data_key')}"
    if payload.get("target_path") != expected_target_path:
        raise ValueError("runtime injection plan target_path mismatch")


def _validate_runtime_consumption_audit(payload: Mapping[str, Any]) -> None:
    for field in (
        "consumer",
        "canonical_input",
        "bundle_id",
        "as_of",
        "freshness_status",
        "handoff_manifest_path",
        "signal_bundle_manifest_path",
        "source_family_catalog_manifest_path",
        "consumer_contract_registry_manifest_path",
        "runtime_market_data_key",
        "runtime_payload_field",
    ):
        _required_string(payload, field)
    for field in (
        "handoff_manifest_sha256",
        "signal_bundle_manifest_sha256",
        "source_family_catalog_manifest_sha256",
        "consumer_contract_registry_manifest_sha256",
    ):
        _required_sha256(payload, field)
    if payload.get("ready_for_consumption") is not True:
        raise ValueError("runtime consumption audit is not ready for consumption")
    if payload.get("ready_for_runtime_injection") is not True:
        raise ValueError("runtime consumption audit is not ready for injection")
    if payload.get("runtime_injection_allowed") is not True:
        raise ValueError("runtime consumption audit does not allow injection")
    if payload.get("ready_for_research_consumption") is not False:
        raise ValueError("runtime consumption audit is marked research-ready")
    if int(payload.get("matched_source_family_count", 0)) <= 0:
        raise ValueError("runtime consumption audit has no matched source family")
    if "all_runtime_consumers_covered" in payload and not isinstance(
        payload["all_runtime_consumers_covered"],
        bool,
    ):
        raise ValueError(
            "runtime consumption audit all_runtime_consumers_covered must be a bool"
        )


def _validate_research_consumption_audit(payload: Mapping[str, Any]) -> None:
    for field in (
        "consumer",
        "research_export_manifest_path",
        "research_artifact_type",
        "research_transform",
        "research_as_of",
        "handoff_manifest_path",
        "source_family_catalog_manifest_path",
        "consumer_contract_registry_manifest_path",
    ):
        _required_string(payload, field)
    for field in (
        "handoff_manifest_sha256",
        "research_export_manifest_sha256",
        "research_output_csv_sha256",
        "source_family_catalog_manifest_sha256",
        "consumer_contract_registry_manifest_sha256",
    ):
        _required_sha256(payload, field)
    if payload.get("ready_for_consumption") is not True:
        raise ValueError("research consumption audit is not ready for consumption")
    if payload.get("ready_for_research_consumption") is not True:
        raise ValueError("research consumption audit is not research-ready")
    if payload.get("ready_for_runtime_injection") is not False:
        raise ValueError("research consumption audit is runtime-ready")
    if payload.get("runtime_injection_allowed") is not False:
        raise ValueError("research consumption audit allows runtime injection")
    if "all_runtime_consumers_covered" in payload and not isinstance(
        payload["all_runtime_consumers_covered"],
        bool,
    ):
        raise ValueError(
            "research consumption audit all_runtime_consumers_covered must be a bool"
        )


def _required_sha256(payload: Mapping[str, Any], field: str) -> str:
    value = _required_string(payload, field)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"consumption audit invalid sha256 field: {field}")
    return value


def _load_json_mapping(path: Path, *, artifact_name: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_name} artifact must be a JSON object")
    return payload


def _reject_sensitive_keys(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if any(fragment in normalized for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(f"consumption audit contains forbidden key: {path}{key_text}")
            _reject_sensitive_keys(item, path=f"{path}{key_text}.")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _reject_sensitive_keys(item, path=f"{path}{index}.")


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
