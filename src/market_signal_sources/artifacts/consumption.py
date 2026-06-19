from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

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
_ARTIFACT_TYPE = "market_signal_consumption_audit"
_INJECTION_PLAN_ARTIFACT_TYPE = "market_signal_runtime_injection_plan"
_PLAN_AUDIT_MATCH_ARTIFACT_TYPE = "market_signal_runtime_plan_audit_match"
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
        )
        return _runtime_consumption_audit(
            summary,
            handoff_source=selected_source,
        )

    assert research_handoff_manifest is not None
    summary = validate_research_signal_handoff_manifest(
        research_handoff_manifest,
        consumer=target_consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
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
        "sha256": _sha256_file(audit_path),
        "size_bytes": audit_path.stat().st_size,
    }


def _runtime_consumption_audit(
    summary: dict[str, Any],
    *,
    handoff_source: str,
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
