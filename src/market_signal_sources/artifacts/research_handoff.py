from __future__ import annotations

from collections.abc import Mapping
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import validate_consumer_contract_registry_manifest
from .signal_bundle import sha256_file
from .source_catalog import validate_signal_source_family_catalog_manifest
from .validation import validate_research_export_manifest


MARKET_SIGNAL_RESEARCH_HANDOFF_SCHEMA_VERSION = "market_signal_research_handoff.v1"
_ARTIFACT_TYPE = "market_signal_research_handoff"
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


def write_research_signal_handoff_manifest(
    path: str | PathLike[str],
    *,
    research_export_manifest: str | PathLike[str],
    source_family_catalog_manifest: str | PathLike[str],
    consumer_contract_registry_manifest: str | PathLike[str],
    consumer: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
    require_runtime_consumer_coverage: bool = False,
) -> dict[str, Any]:
    """Write a handoff manifest that pins one research CSV export and contracts."""

    handoff_path = Path(path)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    root = handoff_path.parent.resolve()
    target_consumer = _normalize_consumer(consumer)
    research_export_manifest_path = _resolve_existing_input_path(
        research_export_manifest,
        root=root,
        field="research_export_manifest",
    )
    source_catalog_manifest_path = _resolve_existing_input_path(
        source_family_catalog_manifest,
        root=root,
        field="source_family_catalog_manifest",
    )
    consumer_registry_manifest_path = _resolve_existing_input_path(
        consumer_contract_registry_manifest,
        root=root,
        field="consumer_contract_registry_manifest",
    )

    research_summary = validate_research_export_manifest(research_export_manifest_path)
    source_catalog_summary = validate_signal_source_family_catalog_manifest(
        source_catalog_manifest_path,
        require_all_known_families=require_all_known_families,
    )
    _require_runtime_consumer_coverage(
        source_catalog_summary,
        required=require_runtime_consumer_coverage,
    )
    consumer_registry_summary = validate_consumer_contract_registry_manifest(
        consumer_registry_manifest_path,
        require_all_known_consumers=require_all_known_consumers,
    )
    matched_source_families = _matching_source_families(
        source_catalog_manifest_path,
        transform=str(research_summary["transform"]),
        consumer=target_consumer,
    )
    _validate_matching_source_families(
        matched_source_families,
        consumer=target_consumer,
        transform=str(research_summary["transform"]),
    )
    _validate_registry_consumer(
        consumer_registry_summary,
        consumer=target_consumer,
    )
    payload = _research_handoff_manifest(
        root=root,
        research_export_manifest_path=research_export_manifest_path,
        research_summary=research_summary,
        source_catalog_manifest_path=source_catalog_manifest_path,
        source_catalog_summary=source_catalog_summary,
        consumer_registry_manifest_path=consumer_registry_manifest_path,
        consumer_registry_summary=consumer_registry_summary,
        consumer=target_consumer,
        matched_source_families=matched_source_families,
    )
    handoff_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_research_signal_handoff_manifest(
        handoff_path,
        consumer=target_consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        require_runtime_consumer_coverage=require_runtime_consumer_coverage,
    )


def validate_research_signal_handoff_manifest(
    path: str | PathLike[str],
    *,
    consumer: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
    require_runtime_consumer_coverage: bool = False,
) -> dict[str, Any]:
    """Validate a research handoff manifest and each linked manifest."""

    handoff_path = Path(path)
    payload = _read_json_mapping(handoff_path, label="research handoff manifest")
    _validate_research_handoff_shape(payload)
    root = handoff_path.parent.resolve()
    research_export_manifest_path = _resolve_linked_manifest_path(
        root,
        payload["research_export_manifest_path"],
        field="research_export_manifest_path",
    )
    source_catalog_manifest_path = _resolve_linked_manifest_path(
        root,
        payload["source_family_catalog_manifest_path"],
        field="source_family_catalog_manifest_path",
    )
    consumer_registry_manifest_path = _resolve_linked_manifest_path(
        root,
        payload["consumer_contract_registry_manifest_path"],
        field="consumer_contract_registry_manifest_path",
    )
    _validate_linked_sha256(
        research_export_manifest_path,
        payload["research_export_manifest_sha256"],
        field="research_export_manifest_sha256",
    )
    _validate_linked_sha256(
        source_catalog_manifest_path,
        payload["source_family_catalog_manifest_sha256"],
        field="source_family_catalog_manifest_sha256",
    )
    _validate_linked_sha256(
        consumer_registry_manifest_path,
        payload["consumer_contract_registry_manifest_sha256"],
        field="consumer_contract_registry_manifest_sha256",
    )

    target_consumer = _normalize_consumer(consumer or payload.get("consumer", ""))
    research_summary = validate_research_export_manifest(research_export_manifest_path)
    source_catalog_summary = validate_signal_source_family_catalog_manifest(
        source_catalog_manifest_path,
        require_all_known_families=require_all_known_families,
    )
    _require_runtime_consumer_coverage(
        source_catalog_summary,
        required=require_runtime_consumer_coverage,
    )
    consumer_registry_summary = validate_consumer_contract_registry_manifest(
        consumer_registry_manifest_path,
        require_all_known_consumers=require_all_known_consumers,
    )
    matched_source_families = _matching_source_families(
        source_catalog_manifest_path,
        transform=str(research_summary["transform"]),
        consumer=target_consumer,
    )
    _validate_matching_source_families(
        matched_source_families,
        consumer=target_consumer,
        transform=str(research_summary["transform"]),
    )
    _validate_registry_consumer(
        consumer_registry_summary,
        consumer=target_consumer,
    )
    expected_summary = _research_handoff_summary(
        handoff_path=handoff_path,
        payload=payload,
        research_export_manifest_path=research_export_manifest_path,
        research_summary=research_summary,
        source_catalog_manifest_path=source_catalog_manifest_path,
        source_catalog_summary=source_catalog_summary,
        consumer_registry_manifest_path=consumer_registry_manifest_path,
        consumer_registry_summary=consumer_registry_summary,
        consumer=target_consumer,
        matched_source_families=matched_source_families,
    )
    _validate_summary_consistency(payload, expected_summary)
    return expected_summary


def _research_handoff_manifest(
    *,
    root: Path,
    research_export_manifest_path: Path,
    research_summary: Mapping[str, Any],
    source_catalog_manifest_path: Path,
    source_catalog_summary: Mapping[str, Any],
    consumer_registry_manifest_path: Path,
    consumer_registry_summary: Mapping[str, Any],
    consumer: str | None,
    matched_source_families: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_RESEARCH_HANDOFF_SCHEMA_VERSION,
        "artifact_type": _ARTIFACT_TYPE,
        "consumer": str(consumer or ""),
        "research_export_manifest_path": research_export_manifest_path.relative_to(
            root
        ).as_posix(),
        "research_export_manifest_sha256": sha256_file(research_export_manifest_path),
        "research_artifact_type": research_summary["artifact_type"],
        "research_transform": research_summary["transform"],
        "research_as_of": research_summary["as_of"],
        "research_output_csv_sha256": research_summary["output_csv_sha256"],
        "research_quality_report_sha256": research_summary.get(
            "quality_report_sha256",
            "",
        ),
        "source_family_catalog_manifest_path": source_catalog_manifest_path.relative_to(
            root
        ).as_posix(),
        "source_family_catalog_manifest_sha256": sha256_file(
            source_catalog_manifest_path
        ),
        "source_families": list(matched_source_families),
        "source_family_count": len(matched_source_families),
        "all_known_source_families_present": source_catalog_summary[
            "all_known_families_present"
        ],
        "all_consumer_contracts_satisfied": source_catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": source_catalog_summary[
            "all_runtime_consumers_covered"
        ],
        "consumer_contract_registry_manifest_path": (
            consumer_registry_manifest_path.relative_to(root).as_posix()
        ),
        "consumer_contract_registry_manifest_sha256": sha256_file(
            consumer_registry_manifest_path
        ),
        "consumer_contracts": list(consumer_registry_summary["consumers"]),
        "consumer_contract_count": consumer_registry_summary["consumer_count"],
        "all_known_consumers_present": consumer_registry_summary[
            "all_known_consumers_present"
        ],
        "canonical_registry_payload_sha256": consumer_registry_summary[
            "canonical_registry_payload_sha256"
        ],
        "local_registry_payload_sha256": consumer_registry_summary[
            "local_registry_payload_sha256"
        ],
        "local_contract_registry_verified": consumer_registry_summary[
            "local_contract_registry_verified"
        ],
    }


def _research_handoff_summary(
    *,
    handoff_path: Path,
    payload: Mapping[str, Any],
    research_export_manifest_path: Path,
    research_summary: Mapping[str, Any],
    source_catalog_manifest_path: Path,
    source_catalog_summary: Mapping[str, Any],
    consumer_registry_manifest_path: Path,
    consumer_registry_summary: Mapping[str, Any],
    consumer: str | None,
    matched_source_families: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "path": str(handoff_path.resolve()),
        "schema_version": MARKET_SIGNAL_RESEARCH_HANDOFF_SCHEMA_VERSION,
        "artifact_type": _ARTIFACT_TYPE,
        "sha256": sha256_file(handoff_path),
        "size_bytes": handoff_path.stat().st_size,
        "consumer": str(consumer or ""),
        "research_export_manifest_path": str(research_export_manifest_path.resolve()),
        "research_export_manifest_sha256": sha256_file(research_export_manifest_path),
        "research_artifact_type": research_summary["artifact_type"],
        "research_transform": research_summary["transform"],
        "research_as_of": research_summary["as_of"],
        "research_output_csv_sha256": research_summary["output_csv_sha256"],
        "research_quality_report_sha256": research_summary.get(
            "quality_report_sha256",
            "",
        ),
        "source_family_catalog_manifest_path": str(
            source_catalog_manifest_path.resolve()
        ),
        "source_family_catalog_manifest_sha256": sha256_file(
            source_catalog_manifest_path
        ),
        "source_families": tuple(matched_source_families),
        "source_family_count": len(matched_source_families),
        "all_known_source_families_present": source_catalog_summary[
            "all_known_families_present"
        ],
        "all_consumer_contracts_satisfied": source_catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": source_catalog_summary[
            "all_runtime_consumers_covered"
        ],
        "consumer_contract_registry_manifest_path": str(
            consumer_registry_manifest_path.resolve()
        ),
        "consumer_contract_registry_manifest_sha256": sha256_file(
            consumer_registry_manifest_path
        ),
        "consumer_contracts": tuple(consumer_registry_summary["consumers"]),
        "consumer_contract_count": consumer_registry_summary["consumer_count"],
        "all_known_consumers_present": consumer_registry_summary[
            "all_known_consumers_present"
        ],
        "canonical_registry_payload_sha256": consumer_registry_summary[
            "canonical_registry_payload_sha256"
        ],
        "local_registry_payload_sha256": consumer_registry_summary[
            "local_registry_payload_sha256"
        ],
        "local_contract_registry_verified": consumer_registry_summary[
            "local_contract_registry_verified"
        ],
        "summary_verified": True,
        "payload_consumer": str(payload.get("consumer", "")),
    }


def _matching_source_families(
    source_catalog_manifest_path: Path,
    *,
    transform: str,
    consumer: str | None,
) -> tuple[str, ...]:
    manifest = _read_json_mapping(
        source_catalog_manifest_path,
        label="source family catalog manifest",
    )
    catalog_path = _resolve_linked_manifest_path(
        source_catalog_manifest_path.parent.resolve(),
        manifest["catalog_path"],
        field="catalog_path",
    )
    catalog = _read_json_mapping(catalog_path, label="source family catalog")
    families = catalog.get("families")
    if not isinstance(families, list):
        raise ValueError("source family catalog families must be a list")
    matched: list[str] = []
    for record in families:
        if not isinstance(record, Mapping):
            raise ValueError("source family catalog records must be mappings")
        if str(record.get("transform", "")).strip() != transform:
            continue
        compatible_profiles = {
            str(profile).strip()
            for profile in record.get("compatible_profiles", ()) or ()
            if str(profile).strip()
        }
        if consumer is not None and consumer not in compatible_profiles:
            continue
        family = str(record.get("family", "")).strip()
        if family:
            matched.append(family)
    return tuple(sorted(matched))


def _validate_registry_consumer(
    consumer_registry_summary: Mapping[str, Any],
    *,
    consumer: str | None,
) -> None:
    if consumer is None:
        return
    consumers = {str(item) for item in consumer_registry_summary["consumers"]}
    if consumer not in consumers:
        raise ValueError(
            "research handoff consumer contract registry missing consumer: "
            f"{consumer}"
        )


def _require_runtime_consumer_coverage(
    source_catalog_summary: Mapping[str, Any],
    *,
    required: bool,
) -> None:
    if (
        required
        and source_catalog_summary.get("all_runtime_consumers_covered") is not True
    ):
        raise ValueError("source family catalog runtime consumer coverage is incomplete")


def _validate_matching_source_families(
    matched_source_families: tuple[str, ...],
    *,
    consumer: str | None,
    transform: str,
) -> None:
    if matched_source_families:
        return
    if consumer is not None:
        raise ValueError(
            "research handoff source catalog missing family for consumer and "
            f"transform: {consumer}, {transform}"
        )
    raise ValueError(
        "research handoff source catalog missing family for transform: "
        f"{transform}"
    )


def _validate_research_handoff_shape(payload: Mapping[str, Any]) -> None:
    _validate_no_sensitive_fields(payload, path="research_handoff")
    if payload.get("schema_version") != MARKET_SIGNAL_RESEARCH_HANDOFF_SCHEMA_VERSION:
        raise ValueError(
            "unsupported research handoff schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("artifact_type") != _ARTIFACT_TYPE:
        raise ValueError(
            "research handoff artifact_type mismatch: "
            f"{payload.get('artifact_type')!r}"
        )
    for field in (
        "research_export_manifest_path",
        "research_export_manifest_sha256",
        "source_family_catalog_manifest_path",
        "source_family_catalog_manifest_sha256",
        "consumer_contract_registry_manifest_path",
        "consumer_contract_registry_manifest_sha256",
        "research_artifact_type",
        "research_transform",
        "research_output_csv_sha256",
        "source_families",
        "consumer_contracts",
    ):
        if field in {"source_families", "consumer_contracts"}:
            if not isinstance(payload.get(field), list):
                raise ValueError(f"research handoff {field} must be a list")
            continue
        if not str(payload.get(field, "")).strip():
            raise ValueError(f"research handoff missing field: {field}")
    if "all_runtime_consumers_covered" in payload and not isinstance(
        payload["all_runtime_consumers_covered"],
        bool,
    ):
        raise ValueError(
            "research handoff all_runtime_consumers_covered must be a bool"
        )


def _validate_summary_consistency(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    expected_values = {
        "consumer": summary["consumer"],
        "research_artifact_type": summary["research_artifact_type"],
        "research_transform": summary["research_transform"],
        "research_as_of": summary["research_as_of"],
        "research_output_csv_sha256": summary["research_output_csv_sha256"],
        "research_quality_report_sha256": summary["research_quality_report_sha256"],
        "source_families": list(summary["source_families"]),
        "source_family_count": summary["source_family_count"],
        "all_known_source_families_present": summary[
            "all_known_source_families_present"
        ],
        "all_consumer_contracts_satisfied": summary[
            "all_consumer_contracts_satisfied"
        ],
        "consumer_contracts": list(summary["consumer_contracts"]),
        "consumer_contract_count": summary["consumer_contract_count"],
        "all_known_consumers_present": summary["all_known_consumers_present"],
    }
    for field, expected in expected_values.items():
        if payload.get(field) != expected:
            raise ValueError(
                f"research handoff {field} mismatch: "
                f"{payload.get(field)!r} != {expected!r}"
            )
    optional_expected_values = {
        "all_runtime_consumers_covered": summary["all_runtime_consumers_covered"],
        "canonical_registry_payload_sha256": summary[
            "canonical_registry_payload_sha256"
        ],
        "local_registry_payload_sha256": summary["local_registry_payload_sha256"],
        "local_contract_registry_verified": summary["local_contract_registry_verified"],
    }
    for field, expected in optional_expected_values.items():
        if field in payload and payload.get(field) != expected:
            raise ValueError(
                f"research handoff {field} mismatch: "
                f"{payload.get(field)!r} != {expected!r}"
            )


def _resolve_existing_input_path(
    value: str | PathLike[str],
    *,
    root: Path,
    field: str,
) -> Path:
    path = Path(value).resolve()
    if not path.exists():
        raise ValueError(f"{field} does not exist: {value}")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} must stay inside handoff directory tree") from exc
    return path


def _resolve_linked_manifest_path(root: Path, value: object, *, field: str) -> Path:
    relative_path = Path(str(value).strip())
    if not str(value).strip():
        raise ValueError(f"research handoff {field} must not be empty")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"research handoff {field} must stay inside manifest directory")
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"research handoff {field} escapes manifest directory") from exc
    if not path.exists():
        raise ValueError(f"research handoff {field} does not exist: {value}")
    return path


def _validate_linked_sha256(path: Path, expected: object, *, field: str) -> None:
    expected_sha256 = str(expected).strip().lower()
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"research handoff {field} mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} JSON root must be a mapping")
    return dict(payload)


def _validate_no_sensitive_fields(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            raw_key = str(key)
            normalized = raw_key.lower()
            if any(
                fragment in normalized
                for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS
            ):
                raise ValueError(f"sensitive field is not allowed in {path}: {raw_key}")
            _validate_no_sensitive_fields(nested, path=f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_sensitive_fields(item, path=f"{path}[{index}]")


def _normalize_consumer(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
