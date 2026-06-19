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
_ARTIFACT_TYPE = "market_signal_platform_handoff"
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

    payload = _platform_handoff_manifest(
        root=root,
        signal_bundle_manifest_path=signal_bundle_manifest_path,
        signal_bundle_summary=signal_bundle_summary,
        source_catalog_manifest_path=source_catalog_manifest_path,
        source_catalog_summary=source_catalog_summary,
        consumer_registry_manifest_path=consumer_registry_manifest_path,
        consumer_registry_summary=consumer_registry_summary,
        consumer=consumer,
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
    )
    _validate_summary_consistency(payload, expected_summary)
    return expected_summary


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
