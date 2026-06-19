from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import validate_consumer_contract_registry_manifest
from .signal_bundle import (
    CANONICAL_INPUT_DERIVED_INDICATORS,
    FRESHNESS_FRESH,
    sha256_file,
)
from .source_catalog import validate_signal_source_family_catalog_manifest
from .validation import (
    validate_signal_bundle_manifest,
    validate_signal_bundle_manifest_for_consumer,
)


MARKET_SIGNAL_PLATFORM_HANDOFF_SCHEMA_VERSION = "market_signal_platform_handoff.v1"
MARKET_SIGNAL_PLATFORM_HANDOFF_INDEX_SCHEMA_VERSION = (
    "market_signal_platform_handoff_index.v1"
)
_ARTIFACT_TYPE = "market_signal_platform_handoff"
_INDEX_ARTIFACT_TYPE = "market_signal_platform_handoff_index"
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


def write_platform_signal_handoff_index(
    index_path: str | PathLike[str],
    handoff_manifests: Iterable[str | PathLike[str]],
    *,
    generated_at: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
) -> dict[str, Any]:
    """Write a platform handoff index for selecting dated handoff manifests."""

    target_path = Path(index_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    index_root = target_path.parent.resolve()
    entries = [
        _platform_handoff_index_entry(
            Path(handoff_manifest),
            index_root=index_root,
            require_all_known_families=require_all_known_families,
            require_all_known_consumers=require_all_known_consumers,
        )
        for handoff_manifest in handoff_manifests
    ]
    if not entries:
        raise ValueError("handoff_manifests must include at least one manifest")
    payload = {
        "schema_version": MARKET_SIGNAL_PLATFORM_HANDOFF_INDEX_SCHEMA_VERSION,
        "artifact_type": _INDEX_ARTIFACT_TYPE,
        "generated_at": generated_at or _default_index_generated_at(entries),
        "handoffs": sorted(
            entries,
            key=lambda entry: (
                str(entry.get("as_of", "")),
                str(entry.get("bundle_id", "")),
                str(entry.get("consumer", "")),
                str(entry.get("handoff_manifest_path", "")),
            ),
        ),
    }
    target_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_platform_signal_handoff_index(
        target_path,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
    )


def upsert_platform_signal_handoff_index(
    index_path: str | PathLike[str],
    handoff_manifest: str | PathLike[str],
    *,
    generated_at: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
) -> dict[str, Any]:
    """Add or replace one handoff manifest entry in a platform handoff index."""

    target_path = Path(index_path)
    index_root = target_path.parent.resolve()
    entries: dict[tuple[str, str, str], Path] = {}
    if target_path.exists():
        existing = _read_json_mapping(target_path, label="platform handoff index")
        for raw_entry in existing.get("handoffs", ()) or ():
            if not isinstance(raw_entry, Mapping):
                continue
            resolved_path = _resolve_handoff_index_manifest_path(
                index_root,
                raw_entry.get("handoff_manifest_path"),
            )
            entries[_index_entry_identity(raw_entry)] = resolved_path

    new_entry = _platform_handoff_index_entry(
        Path(handoff_manifest),
        index_root=index_root,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
    )
    entries[_index_entry_identity(new_entry)] = Path(handoff_manifest)
    return write_platform_signal_handoff_index(
        target_path,
        entries.values(),
        generated_at=generated_at,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
    )


def validate_platform_signal_handoff_index(
    path: str | PathLike[str],
    *,
    consumer: str | None = None,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    as_of: str | None = None,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
) -> dict[str, Any]:
    """Validate a platform handoff index and resolve the latest matching entry."""

    index_path = Path(path)
    index = _read_json_mapping(index_path, label="platform handoff index")
    _validate_platform_handoff_index_shape(index)
    handoff_manifest_path = _resolve_platform_handoff_manifest_from_index(
        index_path,
        index,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        as_of=as_of,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    handoff_summary = validate_platform_signal_handoff_manifest(
        handoff_manifest_path,
        consumer=consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    selected_entry = _selected_index_entry(
        index_path,
        index,
        handoff_manifest_path=handoff_manifest_path,
    )
    _validate_index_entry_summary_consistency(selected_entry, handoff_summary)
    return {
        **handoff_summary,
        "index_path": str(index_path.resolve()),
        "index_schema_version": str(index["schema_version"]),
        "index_artifact_type": str(index["artifact_type"]),
        "index_handoff_count": len(index["handoffs"]),
        "handoff_manifest_path": str(handoff_manifest_path.resolve()),
        "handoff_manifest_sha256": sha256_file(handoff_manifest_path),
    }


def resolve_platform_signal_handoff_manifest_from_index(
    path: str | PathLike[str],
    *,
    consumer: str | None = None,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    as_of: str | None = None,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> Path:
    """Resolve the latest matching handoff manifest path from an index."""

    index_path = Path(path)
    index = _read_json_mapping(index_path, label="platform handoff index")
    _validate_platform_handoff_index_shape(index)
    return _resolve_platform_handoff_manifest_from_index(
        index_path,
        index,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        as_of=as_of,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )


def write_platform_signal_handoff_manifest(
    path: str | PathLike[str],
    *,
    signal_bundle_manifest: str | PathLike[str],
    source_family_catalog_manifest: str | PathLike[str],
    consumer_contract_registry_manifest: str | PathLike[str],
    consumer: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Write a platform handoff manifest that pins all strategy-facing inputs."""

    handoff_path = Path(path)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    root = handoff_path.parent.resolve()
    signal_bundle_manifest_path = _resolve_existing_input_path(
        signal_bundle_manifest,
        root=root,
        field="signal_bundle_manifest",
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

    signal_bundle_summary = _validate_signal_bundle_manifest_for_handoff(
        signal_bundle_manifest_path,
        consumer=consumer,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    source_catalog_summary = validate_signal_source_family_catalog_manifest(
        source_catalog_manifest_path,
        require_all_known_families=require_all_known_families,
    )
    consumer_registry_summary = validate_consumer_contract_registry_manifest(
        consumer_registry_manifest_path,
        require_all_known_consumers=require_all_known_consumers,
    )
    matched_source_families = _matching_source_families(
        source_catalog_manifest_path,
        signal_bundle_summary=signal_bundle_summary,
        consumer=consumer,
    )
    _validate_matching_source_families(
        matched_source_families,
        consumer=consumer,
        transform=str(signal_bundle_summary["transform"]),
    )

    payload = _platform_handoff_manifest(
        root=root,
        signal_bundle_manifest_path=signal_bundle_manifest_path,
        signal_bundle_summary=signal_bundle_summary,
        source_catalog_manifest_path=source_catalog_manifest_path,
        source_catalog_summary=source_catalog_summary,
        consumer_registry_manifest_path=consumer_registry_manifest_path,
        consumer_registry_summary=consumer_registry_summary,
        consumer=consumer,
        matched_source_families=matched_source_families,
    )
    handoff_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_platform_signal_handoff_manifest(
        handoff_path,
        consumer=consumer,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )


def validate_platform_signal_handoff_manifest(
    path: str | PathLike[str],
    *,
    consumer: str | None = None,
    require_all_known_families: bool = False,
    require_all_known_consumers: bool = False,
    expected_canonical_input: str = CANONICAL_INPUT_DERIVED_INDICATORS,
    accepted_freshness_statuses: Iterable[str] = (FRESHNESS_FRESH,),
) -> dict[str, Any]:
    """Validate a platform handoff manifest and each linked manifest."""

    handoff_path = Path(path)
    with handoff_path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    _validate_platform_handoff_shape(payload)
    root = handoff_path.parent.resolve()
    signal_bundle_manifest_path = _resolve_linked_manifest_path(
        root,
        str(payload["signal_bundle_manifest_path"]),
        field="signal_bundle_manifest_path",
    )
    source_catalog_manifest_path = _resolve_linked_manifest_path(
        root,
        str(payload["source_family_catalog_manifest_path"]),
        field="source_family_catalog_manifest_path",
    )
    consumer_registry_manifest_path = _resolve_linked_manifest_path(
        root,
        str(payload["consumer_contract_registry_manifest_path"]),
        field="consumer_contract_registry_manifest_path",
    )
    _validate_linked_sha256(
        signal_bundle_manifest_path,
        str(payload["signal_bundle_manifest_sha256"]),
        field="signal_bundle_manifest_sha256",
    )
    _validate_linked_sha256(
        source_catalog_manifest_path,
        str(payload["source_family_catalog_manifest_sha256"]),
        field="source_family_catalog_manifest_sha256",
    )
    _validate_linked_sha256(
        consumer_registry_manifest_path,
        str(payload["consumer_contract_registry_manifest_sha256"]),
        field="consumer_contract_registry_manifest_sha256",
    )

    target_consumer = str(consumer or payload.get("consumer", "")).strip() or None
    signal_bundle_summary = _validate_signal_bundle_manifest_for_handoff(
        signal_bundle_manifest_path,
        consumer=target_consumer,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
    )
    source_catalog_summary = validate_signal_source_family_catalog_manifest(
        source_catalog_manifest_path,
        require_all_known_families=require_all_known_families,
    )
    consumer_registry_summary = validate_consumer_contract_registry_manifest(
        consumer_registry_manifest_path,
        require_all_known_consumers=require_all_known_consumers,
    )
    matched_source_families = _matching_source_families(
        source_catalog_manifest_path,
        signal_bundle_summary=signal_bundle_summary,
        consumer=target_consumer,
    )
    _validate_matching_source_families(
        matched_source_families,
        consumer=target_consumer,
        transform=str(signal_bundle_summary["transform"]),
    )
    expected_summary = _platform_handoff_summary(
        handoff_path=handoff_path,
        payload=payload,
        signal_bundle_manifest_path=signal_bundle_manifest_path,
        signal_bundle_summary=signal_bundle_summary,
        source_catalog_manifest_path=source_catalog_manifest_path,
        source_catalog_summary=source_catalog_summary,
        consumer_registry_manifest_path=consumer_registry_manifest_path,
        consumer_registry_summary=consumer_registry_summary,
        consumer=target_consumer,
        matched_source_families=matched_source_families,
    )
    _validate_summary_consistency(payload, expected_summary)
    return expected_summary


def _platform_handoff_index_entry(
    handoff_manifest_path: Path,
    *,
    index_root: Path,
    require_all_known_families: bool,
    require_all_known_consumers: bool,
) -> dict[str, Any]:
    resolved_handoff_path = handoff_manifest_path.resolve()
    try:
        relative_handoff_path = resolved_handoff_path.relative_to(index_root)
    except ValueError as exc:
        raise ValueError(
            "handoff_manifest_path must stay inside index directory tree"
        ) from exc
    summary = validate_platform_signal_handoff_manifest(
        resolved_handoff_path,
        require_all_known_families=require_all_known_families,
        require_all_known_consumers=require_all_known_consumers,
    )
    return {
        "handoff_manifest_path": relative_handoff_path.as_posix(),
        "handoff_manifest_sha256": sha256_file(resolved_handoff_path),
        "consumer": summary["consumer"],
        "canonical_input": summary["canonical_input"],
        "bundle_id": summary["bundle_id"],
        "as_of": summary["as_of"],
        "freshness_status": summary["freshness_status"],
        "source_families": list(summary["source_families"]),
        "matched_source_families": list(summary["matched_source_families"]),
        "matched_source_family_count": summary["matched_source_family_count"],
        "consumer_contracts": list(summary["consumer_contracts"]),
        "all_known_source_families_present": summary[
            "all_known_source_families_present"
        ],
        "all_consumer_contracts_satisfied": summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_known_consumers_present": summary["all_known_consumers_present"],
    }


def _validate_platform_handoff_index_shape(index: Mapping[str, Any]) -> None:
    _validate_no_sensitive_fields(index, path="platform_handoff_index")
    if index.get("schema_version") != MARKET_SIGNAL_PLATFORM_HANDOFF_INDEX_SCHEMA_VERSION:
        raise ValueError(
            "unsupported platform handoff index schema_version: "
            f"{index.get('schema_version')!r}"
        )
    if index.get("artifact_type") != _INDEX_ARTIFACT_TYPE:
        raise ValueError(
            "platform handoff index artifact_type mismatch: "
            f"{index.get('artifact_type')!r}"
        )
    handoffs = index.get("handoffs")
    if not isinstance(handoffs, list) or not handoffs:
        raise ValueError("platform handoff index handoffs must be a non-empty list")
    for raw_entry in handoffs:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("platform handoff index entries must be mappings")
        for field in (
            "handoff_manifest_path",
            "handoff_manifest_sha256",
            "canonical_input",
            "bundle_id",
            "as_of",
            "freshness_status",
            "source_families",
            "consumer_contracts",
        ):
            if not str(raw_entry.get(field, "")).strip() and field not in {
                "source_families",
                "consumer_contracts",
            }:
                raise ValueError(f"platform handoff index entry missing field: {field}")
        for field in ("source_families", "consumer_contracts"):
            if not isinstance(raw_entry.get(field), list):
                raise ValueError(
                    f"platform handoff index entry {field} must be a list"
                )
        if "matched_source_families" in raw_entry and not isinstance(
            raw_entry.get("matched_source_families"),
            list,
        ):
            raise ValueError(
                "platform handoff index entry matched_source_families must be a list"
            )


def _resolve_platform_handoff_manifest_from_index(
    index_path: Path,
    index: Mapping[str, Any],
    *,
    consumer: str | None,
    expected_canonical_input: str,
    as_of: str | None,
    accepted_freshness_statuses: Iterable[str],
) -> Path:
    accepted = {str(item).strip().lower() for item in accepted_freshness_statuses}
    target_consumer = str(consumer or "").strip()
    target_as_of = str(as_of).strip() if as_of is not None else None
    candidates: list[Mapping[str, Any]] = []
    for raw_entry in index["handoffs"]:
        entry = dict(raw_entry)
        canonical_input = str(entry.get("canonical_input", "")).strip()
        freshness = str(entry.get("freshness_status", "")).strip().lower()
        entry_as_of = str(entry.get("as_of", "")).strip()
        if canonical_input != expected_canonical_input:
            continue
        if freshness not in accepted:
            continue
        if target_as_of is not None and entry_as_of > target_as_of:
            continue
        if target_consumer and not _index_entry_matches_consumer(
            entry,
            consumer=target_consumer,
        ):
            continue
        candidates.append(entry)
    if not candidates:
        raise ValueError("platform handoff index has no matching handoff entry")
    selected = max(
        candidates,
        key=lambda entry: (
            str(entry.get("as_of", "")),
            str(entry.get("bundle_id", "")),
            str(entry.get("consumer", "")),
            str(entry.get("handoff_manifest_path", "")),
        ),
    )
    handoff_path = _resolve_handoff_index_manifest_path(
        index_path.parent.resolve(),
        selected["handoff_manifest_path"],
    )
    expected_sha256 = str(selected["handoff_manifest_sha256"]).strip().lower()
    actual_sha256 = sha256_file(handoff_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "platform handoff index handoff_manifest_sha256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    return handoff_path


def _selected_index_entry(
    index_path: Path,
    index: Mapping[str, Any],
    *,
    handoff_manifest_path: Path,
) -> Mapping[str, Any]:
    relative = handoff_manifest_path.resolve().relative_to(index_path.parent.resolve())
    for raw_entry in index["handoffs"]:
        if str(raw_entry.get("handoff_manifest_path", "")) == relative.as_posix():
            return raw_entry
    raise ValueError("platform handoff index selected entry is missing")


def _validate_index_entry_summary_consistency(
    entry: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    expected_values = {
        "consumer": summary["consumer"],
        "canonical_input": summary["canonical_input"],
        "bundle_id": summary["bundle_id"],
        "as_of": summary["as_of"],
        "freshness_status": summary["freshness_status"],
        "source_families": list(summary["source_families"]),
        "consumer_contracts": list(summary["consumer_contracts"]),
        "all_known_source_families_present": summary[
            "all_known_source_families_present"
        ],
        "all_consumer_contracts_satisfied": summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_known_consumers_present": summary["all_known_consumers_present"],
    }
    for field, expected in expected_values.items():
        if entry.get(field) != expected:
            raise ValueError(
                f"platform handoff index {field} mismatch: "
                f"{entry.get(field)!r} != {expected!r}"
            )
    optional_expected_values = {
        "matched_source_families": list(summary["matched_source_families"]),
        "matched_source_family_count": summary["matched_source_family_count"],
    }
    for field, expected in optional_expected_values.items():
        if field in entry and entry.get(field) != expected:
            raise ValueError(
                f"platform handoff index {field} mismatch: "
                f"{entry.get(field)!r} != {expected!r}"
            )


def _index_entry_matches_consumer(
    entry: Mapping[str, Any],
    *,
    consumer: str,
) -> bool:
    entry_consumer = str(entry.get("consumer", "")).strip()
    if entry_consumer == consumer:
        return True
    contracts = entry.get("consumer_contracts")
    return isinstance(contracts, list) and consumer in {str(item) for item in contracts}


def _resolve_handoff_index_manifest_path(index_root: Path, value: object) -> Path:
    relative_path = Path(str(value).strip())
    if not str(value).strip():
        raise ValueError("platform handoff index handoff_manifest_path must not be empty")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(
            "platform handoff index handoff_manifest_path must stay inside index directory"
        )
    resolved = (index_root / relative_path).resolve()
    try:
        resolved.relative_to(index_root)
    except ValueError as exc:
        raise ValueError(
            "platform handoff index handoff_manifest_path escapes index directory"
        ) from exc
    return resolved


def _read_json_mapping(path: Path, *, label: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} JSON root must be a mapping")
    return dict(payload)


def _default_index_generated_at(entries: Iterable[Mapping[str, Any]]) -> str:
    latest_as_of = max(str(entry.get("as_of", "")) for entry in entries)
    return f"{latest_as_of}T00:15:00Z"


def _index_entry_identity(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("bundle_id", "")).strip(),
        str(entry.get("as_of", "")).strip(),
        str(entry.get("canonical_input", "")).strip(),
    )


def _platform_handoff_manifest(
    *,
    root: Path,
    signal_bundle_manifest_path: Path,
    signal_bundle_summary: Mapping[str, Any],
    source_catalog_manifest_path: Path,
    source_catalog_summary: Mapping[str, Any],
    consumer_registry_manifest_path: Path,
    consumer_registry_summary: Mapping[str, Any],
    consumer: str | None,
    matched_source_families: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_PLATFORM_HANDOFF_SCHEMA_VERSION,
        "artifact_type": _ARTIFACT_TYPE,
        "consumer": str(consumer or ""),
        "canonical_input": signal_bundle_summary["canonical_input"],
        "bundle_id": signal_bundle_summary["bundle_id"],
        "as_of": signal_bundle_summary["as_of"],
        "freshness_status": signal_bundle_summary["freshness_status"],
        "signal_bundle_manifest_path": signal_bundle_manifest_path.relative_to(root).as_posix(),
        "signal_bundle_manifest_sha256": sha256_file(signal_bundle_manifest_path),
        "source_family_catalog_manifest_path": source_catalog_manifest_path.relative_to(root).as_posix(),
        "source_family_catalog_manifest_sha256": sha256_file(source_catalog_manifest_path),
        "consumer_contract_registry_manifest_path": consumer_registry_manifest_path.relative_to(root).as_posix(),
        "consumer_contract_registry_manifest_sha256": sha256_file(consumer_registry_manifest_path),
        "source_family_count": source_catalog_summary["family_count"],
        "source_families": list(source_catalog_summary["families"]),
        "matched_source_family_count": len(matched_source_families),
        "matched_source_families": list(matched_source_families),
        "all_known_source_families_present": source_catalog_summary[
            "all_known_families_present"
        ],
        "all_consumer_contracts_satisfied": source_catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "consumer_contract_count": consumer_registry_summary["consumer_count"],
        "consumer_contracts": list(consumer_registry_summary["consumers"]),
        "all_known_consumers_present": consumer_registry_summary[
            "all_known_consumers_present"
        ],
    }


def _platform_handoff_summary(
    *,
    handoff_path: Path,
    payload: Mapping[str, Any],
    signal_bundle_manifest_path: Path,
    signal_bundle_summary: Mapping[str, Any],
    source_catalog_manifest_path: Path,
    source_catalog_summary: Mapping[str, Any],
    consumer_registry_manifest_path: Path,
    consumer_registry_summary: Mapping[str, Any],
    consumer: str | None,
    matched_source_families: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "path": str(handoff_path),
        "schema_version": payload["schema_version"],
        "artifact_type": payload["artifact_type"],
        "sha256": sha256_file(handoff_path),
        "size_bytes": handoff_path.stat().st_size,
        "consumer": str(consumer or ""),
        "canonical_input": signal_bundle_summary["canonical_input"],
        "bundle_id": signal_bundle_summary["bundle_id"],
        "as_of": signal_bundle_summary["as_of"],
        "freshness_status": signal_bundle_summary["freshness_status"],
        "signal_bundle_manifest_path": str(signal_bundle_manifest_path),
        "signal_bundle_manifest_sha256": sha256_file(signal_bundle_manifest_path),
        "source_family_catalog_manifest_path": str(source_catalog_manifest_path),
        "source_family_catalog_manifest_sha256": sha256_file(source_catalog_manifest_path),
        "consumer_contract_registry_manifest_path": str(consumer_registry_manifest_path),
        "consumer_contract_registry_manifest_sha256": sha256_file(
            consumer_registry_manifest_path
        ),
        "source_family_count": source_catalog_summary["family_count"],
        "source_families": source_catalog_summary["families"],
        "matched_source_family_count": len(matched_source_families),
        "matched_source_families": matched_source_families,
        "all_known_source_families_present": source_catalog_summary[
            "all_known_families_present"
        ],
        "all_consumer_contracts_satisfied": source_catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "consumer_contract_count": consumer_registry_summary["consumer_count"],
        "consumer_contracts": consumer_registry_summary["consumers"],
        "all_known_consumers_present": consumer_registry_summary[
            "all_known_consumers_present"
        ],
    }


def _matching_source_families(
    source_catalog_manifest_path: Path,
    *,
    signal_bundle_summary: Mapping[str, Any],
    consumer: str | None,
) -> tuple[str, ...]:
    manifest = _read_json_mapping(
        source_catalog_manifest_path,
        label="source family catalog manifest",
    )
    catalog_path = _resolve_linked_manifest_path(
        source_catalog_manifest_path.parent.resolve(),
        str(manifest["catalog_path"]),
        field="catalog_path",
    )
    catalog = _read_json_mapping(catalog_path, label="source family catalog")
    families = catalog.get("families")
    if not isinstance(families, list):
        raise ValueError("source family catalog families must be a list")

    transform = str(signal_bundle_summary["transform"]).strip()
    freshness_policy = str(signal_bundle_summary["freshness_policy"]).strip()
    bundle_symbols = {
        str(symbol).strip()
        for symbol in signal_bundle_summary.get("symbols", ()) or ()
        if str(symbol).strip()
    }
    indicator_fields_by_symbol = signal_bundle_summary.get(
        "indicator_fields_by_symbol",
        {},
    )
    target_consumer = str(consumer or "").strip() or None

    matched: list[str] = []
    for record in families:
        if not isinstance(record, Mapping):
            raise ValueError("source family catalog records must be mappings")
        if str(record.get("transform", "")).strip() != transform:
            continue
        if str(record.get("freshness_policy", "")).strip() != freshness_policy:
            continue
        compatible_profiles = {
            str(profile).strip()
            for profile in record.get("compatible_profiles", ()) or ()
            if str(profile).strip()
        }
        if target_consumer is not None and target_consumer not in compatible_profiles:
            continue
        catalog_symbols = {
            str(symbol).strip()
            for symbol in record.get("symbols", ()) or ()
            if str(symbol).strip()
        }
        if not bundle_symbols.issubset(catalog_symbols):
            continue
        catalog_fields = {
            str(field).strip()
            for field in record.get("derived_indicator_fields", ()) or ()
            if str(field).strip()
        }
        if not _bundle_indicator_fields_supported(
            indicator_fields_by_symbol,
            symbols=bundle_symbols,
            catalog_fields=catalog_fields,
        ):
            continue
        family = str(record.get("family", "")).strip()
        if family:
            matched.append(family)
    return tuple(sorted(matched))


def _bundle_indicator_fields_supported(
    indicator_fields_by_symbol: object,
    *,
    symbols: set[str],
    catalog_fields: set[str],
) -> bool:
    if not isinstance(indicator_fields_by_symbol, Mapping):
        return False
    for symbol in symbols:
        raw_fields = indicator_fields_by_symbol.get(symbol, ())
        fields = {
            str(field).strip()
            for field in raw_fields or ()
            if str(field).strip()
        }
        if not fields.issubset(catalog_fields):
            return False
    return True


def _validate_matching_source_families(
    matched_source_families: tuple[str, ...],
    *,
    consumer: str | None,
    transform: str,
) -> None:
    if matched_source_families:
        return
    target_consumer = str(consumer or "").strip()
    if target_consumer:
        raise ValueError(
            "platform handoff source catalog missing family for consumer and "
            f"transform: {target_consumer}, {transform}"
        )
    raise ValueError(
        "platform handoff source catalog missing family for transform: "
        f"{transform}"
    )


def _validate_signal_bundle_manifest_for_handoff(
    path: Path,
    *,
    consumer: str | None,
    expected_canonical_input: str,
    accepted_freshness_statuses: Iterable[str],
) -> dict[str, Any]:
    if consumer:
        return validate_signal_bundle_manifest_for_consumer(
            path,
            consumer=consumer,
            expected_canonical_input=expected_canonical_input,
            accepted_freshness_statuses=accepted_freshness_statuses,
        )
    return validate_signal_bundle_manifest(
        path,
        expected_canonical_input=expected_canonical_input,
        accepted_freshness_statuses=accepted_freshness_statuses,
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
        raise ValueError(f"{field} must stay inside handoff manifest directory") from exc
    return path


def _resolve_linked_manifest_path(root: Path, value: str, *, field: str) -> Path:
    raw_path = Path(value.strip())
    if not value.strip():
        raise ValueError(f"platform handoff {field} must not be empty")
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(f"platform handoff {field} must stay inside handoff directory")
    path = (root / raw_path).resolve()
    if not path.exists():
        raise ValueError(f"platform handoff {field} does not exist: {value}")
    return path


def _validate_platform_handoff_shape(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("platform handoff manifest must be an object")
    _validate_no_sensitive_fields(payload)
    if payload.get("schema_version") != MARKET_SIGNAL_PLATFORM_HANDOFF_SCHEMA_VERSION:
        raise ValueError(
            "unsupported platform handoff schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("artifact_type") != _ARTIFACT_TYPE:
        raise ValueError(
            "platform handoff artifact_type mismatch: "
            f"{payload.get('artifact_type')!r}"
        )
    for field in (
        "signal_bundle_manifest_path",
        "signal_bundle_manifest_sha256",
        "source_family_catalog_manifest_path",
        "source_family_catalog_manifest_sha256",
        "consumer_contract_registry_manifest_path",
        "consumer_contract_registry_manifest_sha256",
    ):
        if not str(payload.get(field, "")).strip():
            raise ValueError(f"platform handoff missing field: {field}")
    if "matched_source_families" in payload and not isinstance(
        payload["matched_source_families"],
        list,
    ):
        raise ValueError("platform handoff matched_source_families must be a list")


def _validate_linked_sha256(path: Path, expected: str, *, field: str) -> None:
    normalized_expected = expected.strip().lower()
    actual = sha256_file(path)
    if actual != normalized_expected:
        raise ValueError(f"platform handoff {field} mismatch: {actual} != {expected}")


def _validate_summary_consistency(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    expected_values = {
        "consumer": summary["consumer"],
        "canonical_input": summary["canonical_input"],
        "bundle_id": summary["bundle_id"],
        "as_of": summary["as_of"],
        "freshness_status": summary["freshness_status"],
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
    }
    for field, expected in expected_values.items():
        if payload.get(field) != expected:
            raise ValueError(
                f"platform handoff {field} mismatch: {payload.get(field)!r} != {expected!r}"
            )
    optional_expected_values = {
        "matched_source_family_count": summary["matched_source_family_count"],
        "matched_source_families": list(summary["matched_source_families"]),
    }
    for field, expected in optional_expected_values.items():
        if field in payload and payload.get(field) != expected:
            raise ValueError(
                f"platform handoff {field} mismatch: {payload.get(field)!r} != {expected!r}"
            )


def _validate_no_sensitive_fields(value: object, *, path: str = "platform_handoff") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(
                    f"platform handoff contains forbidden sensitive key at {path}.{key}"
                )
            _validate_no_sensitive_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_no_sensitive_fields(nested, path=f"{path}[{index}]")
