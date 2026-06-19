from __future__ import annotations

from collections.abc import Iterable
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import write_consumer_contract_registry_artifacts
from .consumption import (
    audit_signal_consumption,
    runtime_signal_injection_plan,
    validate_runtime_adapter_deployment_config_file,
    write_consumption_audit_artifact,
    write_runtime_signal_injection_plan_artifact,
)
from .platform_handoff import (
    upsert_platform_signal_handoff_index,
    write_platform_signal_handoff_manifest,
)
from .source_catalog import write_signal_source_family_catalog_artifacts


MARKET_SIGNAL_PLATFORM_PUBLICATION_SCHEMA_VERSION = (
    "market_signal_platform_publication.v1"
)


def publish_platform_signal_handoff(
    publication_dir: str | PathLike[str],
    *,
    signal_bundle_manifest: str | PathLike[str],
    consumer: str,
    index_path: str | PathLike[str] | None = None,
    lookup_as_of: str | None = None,
    strategy: str | None = None,
    accepted_freshness_statuses: Iterable[str] = ("fresh",),
    require_all_known_families: bool = True,
    require_all_known_consumers: bool = True,
    require_runtime_consumer_coverage: bool = True,
) -> dict[str, Any]:
    """Publish one already-built signal bundle as a platform handoff directory."""

    root = Path(publication_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target_consumer = str(consumer or "").strip()
    if not target_consumer:
        raise ValueError("consumer is required")

    bundle_manifest_path = Path(signal_bundle_manifest).resolve()
    _require_inside(root, bundle_manifest_path, field="signal_bundle_manifest")

    consumer_contract_summary = write_consumer_contract_registry_artifacts(
        root / "consumer_contracts"
    )
    source_catalog_summary = write_signal_source_family_catalog_artifacts(
        root / "source_catalog"
    )
    freshness_statuses = tuple(
        str(status or "").strip()
        for status in accepted_freshness_statuses
        if str(status or "").strip()
    )
    if not freshness_statuses:
        raise ValueError("accepted_freshness_statuses must include at least one value")

    handoff_path = root / "platform_handoff.json"
    handoff_summary = write_platform_signal_handoff_manifest(
        handoff_path,
        signal_bundle_manifest=bundle_manifest_path,
        source_family_catalog_manifest=source_catalog_summary["manifest_path"],
        consumer_contract_registry_manifest=consumer_contract_summary["manifest_path"],
        consumer=target_consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
        accepted_freshness_statuses=freshness_statuses,
    )

    resolved_index_path = (
        Path(index_path).resolve()
        if index_path is not None
        else root.parent / "index.json"
    )
    index_summary = upsert_platform_signal_handoff_index(
        resolved_index_path,
        handoff_path,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
    )
    resolved_lookup_as_of = str(
        lookup_as_of
        or handoff_summary.get("as_of")
        or index_summary.get("as_of")
        or ""
    ).strip()
    if not resolved_lookup_as_of:
        raise ValueError("lookup_as_of could not be resolved from handoff")

    audit = audit_signal_consumption(
        consumer=target_consumer,
        platform_handoff_index=resolved_index_path,
        as_of=resolved_lookup_as_of,
        accepted_freshness_statuses=freshness_statuses,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
    )
    audit_path = root / f"{_safe_consumer_filename(target_consumer)}.audit.json"
    audit_summary = write_consumption_audit_artifact(audit_path, audit)

    plan_path = root / f"{_safe_consumer_filename(target_consumer)}.runtime_plan.json"
    plan_summary = write_runtime_signal_injection_plan_artifact(
        plan_path,
        runtime_signal_injection_plan(audit),
    )

    adapter_config_path = root / f"{_safe_consumer_filename(target_consumer)}.adapter.json"
    adapter_config = _runtime_adapter_config(
        consumer=target_consumer,
        strategy=strategy,
        index_path=resolved_index_path,
        lookup_as_of=resolved_lookup_as_of,
        accepted_freshness_statuses=freshness_statuses,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
        audit_path=audit_path,
        plan_path=plan_path,
    )
    adapter_config_path.write_text(
        json.dumps(adapter_config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    adapter_deployment_summary = validate_runtime_adapter_deployment_config_file(
        adapter_config_path
    )

    return {
        "schema_version": MARKET_SIGNAL_PLATFORM_PUBLICATION_SCHEMA_VERSION,
        "artifact_type": "market_signal_platform_publication",
        "publication_dir": str(root),
        "consumer": target_consumer,
        "strategy": adapter_deployment_summary.get("strategy", ""),
        "as_of": handoff_summary["as_of"],
        "lookup_as_of": resolved_lookup_as_of,
        "signal_bundle_manifest_path": str(bundle_manifest_path),
        "consumer_contract_registry_manifest_path": consumer_contract_summary[
            "manifest_path"
        ],
        "source_family_catalog_manifest_path": source_catalog_summary[
            "manifest_path"
        ],
        "platform_handoff_manifest_path": str(handoff_path),
        "platform_handoff_index_path": str(resolved_index_path),
        "consumption_audit_path": str(audit_path),
        "runtime_plan_path": str(plan_path),
        "runtime_adapter_config_path": str(adapter_config_path),
        "handoff": handoff_summary,
        "index": index_summary,
        "audit": audit_summary,
        "runtime_plan": plan_summary,
        "runtime_adapter_deployment": adapter_deployment_summary,
    }


def _runtime_adapter_config(
    *,
    consumer: str,
    strategy: str | None,
    index_path: Path,
    lookup_as_of: str,
    accepted_freshness_statuses: tuple[str, ...],
    require_all_known_families: bool,
    require_all_known_consumers: bool,
    require_runtime_consumer_coverage: bool,
    audit_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "market_signal_runtime_adapter_config.v1",
        "strategy": strategy or _default_strategy_for_consumer(consumer),
        "signal_consumer": consumer,
        "signal_handoff_index": str(index_path),
        "signal_as_of": lookup_as_of,
        "accepted_freshness_statuses": list(accepted_freshness_statuses),
        "require_all_known_families": require_all_known_families,
        "require_all_known_consumers": require_all_known_consumers,
        "require_runtime_consumer_coverage": require_runtime_consumer_coverage,
        "saved_consumption_audit_json": str(audit_path),
        "saved_runtime_plan_json": str(plan_path),
    }


def _default_strategy_for_consumer(consumer: str) -> str:
    _, _, suffix = consumer.partition(":")
    return suffix or consumer


def _safe_consumer_filename(consumer: str) -> str:
    return (
        consumer.strip()
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _require_inside(root: Path, path: Path, *, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} must stay inside publication_dir") from exc
    if not path.exists():
        raise ValueError(f"{field} does not exist: {path}")
