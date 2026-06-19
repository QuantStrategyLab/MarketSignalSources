from __future__ import annotations

from collections.abc import Iterable
from os import PathLike
from typing import Any

from .platform_handoff import (
    validate_platform_signal_handoff_index,
    validate_platform_signal_handoff_manifest,
)
from .research_handoff import validate_research_signal_handoff_manifest
from .signal_bundle import CANONICAL_INPUT_DERIVED_INDICATORS, FRESHNESS_FRESH


MARKET_SIGNAL_CONSUMPTION_AUDIT_SCHEMA_VERSION = "market_signal_consumption_audit.v1"
_ARTIFACT_TYPE = "market_signal_consumption_audit"


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
