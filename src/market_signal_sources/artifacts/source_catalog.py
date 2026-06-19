from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import (
    SignalConsumerContractError,
    required_indicator_fields_for_consumer,
)
from .signal_bundle import CANONICAL_INPUT_DERIVED_INDICATORS


SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION = "market_signal_source_families.v1"
SIGNAL_SOURCE_FAMILY_CATALOG_MANIFEST_SCHEMA_VERSION = (
    "market_signal_source_family_catalog_manifest.v1"
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

BTC_CYCLE_DERIVED_INDICATOR_FIELDS: tuple[str, ...] = (
    "ahr999",
    "ahr999_estimate_price",
    "ahr999_sma",
    "close",
    "cycle_indicator_source",
    "drawdown_252d",
    "gma200",
    "high252",
    "mayer_multiple",
    "provider_timestamp",
    "rsi14",
    "sma200",
    "sma200_gap",
)
BTC_CYCLE_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "us_equity:ibit_smart_dca",
    "research:ibit_btc_ahr999_precomputed",
    "research:ibit_btc_ahr999_mayer_precomputed",
    "research:ibit_btc_ahr999_mayer_precomputed_variants",
)

SIGNAL_SOURCE_FAMILIES: dict[str, dict[str, object]] = {
    "crypto.btc_cycle_daily": {
        "family": "crypto.btc_cycle_daily",
        "domain": "crypto",
        "bundle_type": "derived_indicators",
        "bundle_id_prefix": "crypto.btc.derived_indicators",
        "canonical_input": "derived_indicators",
        "transform": "crypto.btc.ahr999.v1",
        "provider_dataset": "btc_usd_daily_ohlcv",
        "freshness_policy": "crypto_daily_close_t_plus_1",
        "minimum_history_rows": 200,
        "symbols": ("BTC-USD",),
        "derived_indicator_fields": BTC_CYCLE_DERIVED_INDICATOR_FIELDS,
        "compatible_profiles": BTC_CYCLE_COMPATIBLE_PROFILES,
        "runtime_consumers": ("us_equity:ibit_smart_dca",),
        "research_consumers": (
            "research:ibit_btc_ahr999_precomputed",
            "research:ibit_btc_ahr999_mayer_precomputed",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
        ),
    },
}


def known_signal_source_families() -> tuple[str, ...]:
    """Return known signal source family identifiers in stable order."""

    return tuple(sorted(SIGNAL_SOURCE_FAMILIES))


def signal_source_family_record(family: str) -> dict[str, Any]:
    """Return a JSON-safe signal source family record."""

    normalized = str(family or "").strip()
    if normalized not in SIGNAL_SOURCE_FAMILIES:
        known = ", ".join(known_signal_source_families())
        raise ValueError(f"unknown signal source family: {family!r}; known: {known}")
    return _json_safe_record(SIGNAL_SOURCE_FAMILIES[normalized])


def compatible_profiles_for_signal_source_family(family: str) -> tuple[str, ...]:
    """Return compatible consumers for a known signal source family."""

    record = signal_source_family_record(family)
    return tuple(str(profile) for profile in record["compatible_profiles"])


def signal_source_family_consumer_contract_coverage(family: str) -> dict[str, Any]:
    """Return consumer-contract coverage metadata for a known source family."""

    return _consumer_contract_coverage_summary(signal_source_family_record(family))


def signal_source_family_catalog_payload(
    *,
    families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return JSON-safe metadata for all known signal source families."""

    selected_families = (
        tuple(families)
        if families is not None
        else known_signal_source_families()
    )
    return {
        "schema_version": SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION,
        "families": [
            signal_source_family_record(family)
            for family in selected_families
        ],
    }


def write_signal_source_family_catalog(
    path: str | PathLike[str],
    *,
    families: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Write the signal source family catalog and return hash metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = signal_source_family_catalog_payload(families=families)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_signal_source_family_catalog_file(output_path)


def write_signal_source_family_catalog_artifacts(
    output_dir: str | PathLike[str],
    *,
    families: Iterable[str] | None = None,
    catalog_filename: str = "signal_source_families.json",
    manifest_filename: str = "signal_source_families.manifest.json",
) -> dict[str, Any]:
    """Write a catalog JSON artifact plus a manifest with catalog hash metadata."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    catalog_path = _artifact_child_path(
        output_path,
        catalog_filename,
        field="catalog_filename",
    )
    manifest_path = _artifact_child_path(
        output_path,
        manifest_filename,
        field="manifest_filename",
    )
    catalog_summary = write_signal_source_family_catalog(
        catalog_path,
        families=families,
    )
    manifest = _source_catalog_manifest(
        catalog_summary,
        catalog_path=catalog_path,
        root=output_path,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _source_catalog_manifest_summary(
        manifest_path=manifest_path,
        catalog_path=catalog_path,
        catalog_summary=catalog_summary,
        manifest=manifest,
    )


def validate_signal_source_family_catalog(
    payload: Mapping[str, Any],
    *,
    require_all_known_families: bool = False,
) -> dict[str, Any]:
    """Validate a signal source family catalog payload."""

    if not isinstance(payload, Mapping):
        raise ValueError("signal source family catalog payload must be an object")
    _validate_no_sensitive_fields(payload)
    if payload.get("schema_version") != SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION:
        raise ValueError(
            "signal source family catalog schema_version must be "
            f"{SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION!r}"
        )
    families = payload.get("families")
    if not isinstance(families, list):
        raise ValueError("signal source family catalog families must be a list")

    seen: set[str] = set()
    family_names: list[str] = []
    coverage_by_family: dict[str, Any] = {}
    for record in families:
        if not isinstance(record, dict):
            raise ValueError("signal source family catalog records must be objects")
        family = str(record.get("family", "")).strip()
        if not family:
            raise ValueError("signal source family catalog record family is required")
        if family in seen:
            raise ValueError(f"duplicate signal source family: {family}")
        seen.add(family)
        family_names.append(family)
        expected_record = signal_source_family_record(family)
        if record != expected_record:
            raise ValueError(f"signal source family record drift: {family}")
        coverage_by_family[family] = _consumer_contract_coverage_summary(record)

    missing_known_families = sorted(set(SIGNAL_SOURCE_FAMILIES) - set(family_names))
    if require_all_known_families and missing_known_families:
        raise ValueError(
            "missing known signal source families: "
            + ", ".join(missing_known_families)
        )

    return {
        "schema_version": payload["schema_version"],
        "family_count": len(family_names),
        "families": family_names,
        "known_family_count": len(SIGNAL_SOURCE_FAMILIES),
        "missing_known_families": missing_known_families,
        "all_known_families_present": not missing_known_families,
        "consumer_contract_coverage": coverage_by_family,
        "all_consumer_contracts_satisfied": all(
            bool(summary["all_required_fields_present"])
            for summary in coverage_by_family.values()
        ),
    }


def validate_signal_source_family_catalog_manifest(
    path: str | PathLike[str],
    *,
    require_all_known_families: bool = False,
) -> dict[str, Any]:
    """Validate a catalog manifest and its linked catalog artifact."""

    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as file_obj:
        manifest = json.load(file_obj)
    _validate_source_catalog_manifest_shape(manifest)
    catalog_path = _resolve_manifest_catalog_path(
        manifest_path,
        str(manifest["catalog_path"]),
    )
    catalog_summary = validate_signal_source_family_catalog_file(
        catalog_path,
        require_all_known_families=require_all_known_families,
    )
    _validate_source_catalog_manifest_consistency(
        manifest,
        catalog_summary=catalog_summary,
    )
    return _source_catalog_manifest_summary(
        manifest_path=manifest_path,
        catalog_path=catalog_path,
        catalog_summary=catalog_summary,
        manifest=manifest,
    )


def validate_signal_source_family_catalog_file(
    path: str | PathLike[str],
    *,
    require_all_known_families: bool = False,
) -> dict[str, Any]:
    """Validate a signal source family catalog JSON artifact."""

    catalog_path = Path(path)
    with catalog_path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    summary = validate_signal_source_family_catalog(
        payload,
        require_all_known_families=require_all_known_families,
    )
    return {
        "path": str(catalog_path),
        **summary,
        "sha256": _sha256_file(catalog_path),
        "size_bytes": catalog_path.stat().st_size,
    }


def _json_safe_record(record: dict[str, object]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, tuple):
            safe[key] = list(value)
        else:
            safe[key] = value
    return safe


def _source_catalog_manifest(
    catalog_summary: Mapping[str, Any],
    *,
    catalog_path: Path,
    root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SIGNAL_SOURCE_FAMILY_CATALOG_MANIFEST_SCHEMA_VERSION,
        "artifact_type": "market_signal_source_family_catalog",
        "catalog_path": catalog_path.relative_to(root).as_posix(),
        "catalog_sha256": catalog_summary["sha256"],
        "catalog_size_bytes": catalog_summary["size_bytes"],
        "catalog_schema_version": catalog_summary["schema_version"],
        "family_count": catalog_summary["family_count"],
        "known_family_count": catalog_summary["known_family_count"],
        "missing_known_families": catalog_summary["missing_known_families"],
        "all_known_families_present": catalog_summary["all_known_families_present"],
        "all_consumer_contracts_satisfied": catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
    }


def _source_catalog_manifest_summary(
    *,
    manifest_path: Path,
    catalog_path: Path,
    catalog_summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "manifest_path": str(manifest_path),
        "manifest_schema_version": manifest["schema_version"],
        "manifest_sha256": _sha256_file(manifest_path),
        "manifest_size_bytes": manifest_path.stat().st_size,
        "artifact_type": manifest["artifact_type"],
        "catalog_path": str(catalog_path),
        "catalog_sha256": catalog_summary["sha256"],
        "catalog_size_bytes": catalog_summary["size_bytes"],
        "catalog_schema_version": catalog_summary["schema_version"],
        "family_count": catalog_summary["family_count"],
        "families": catalog_summary["families"],
        "known_family_count": catalog_summary["known_family_count"],
        "missing_known_families": catalog_summary["missing_known_families"],
        "all_known_families_present": catalog_summary["all_known_families_present"],
        "all_consumer_contracts_satisfied": catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
    }


def _artifact_child_path(root: Path, value: str, *, field: str) -> Path:
    raw_path = Path(str(value).strip())
    if not str(value).strip():
        raise ValueError(f"{field} must not be empty")
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(f"{field} must stay inside output_dir")
    return root / raw_path


def _validate_source_catalog_manifest_shape(manifest: object) -> None:
    if not isinstance(manifest, Mapping):
        raise ValueError("signal source family catalog manifest must be an object")
    _validate_no_sensitive_fields(manifest, path="manifest")
    if (
        manifest.get("schema_version")
        != SIGNAL_SOURCE_FAMILY_CATALOG_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported signal source family catalog manifest schema_version: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("artifact_type") != "market_signal_source_family_catalog":
        raise ValueError(
            "signal source family catalog manifest artifact_type mismatch: "
            f"{manifest.get('artifact_type')!r}"
        )
    for field in (
        "catalog_path",
        "catalog_sha256",
        "catalog_size_bytes",
        "catalog_schema_version",
        "family_count",
        "known_family_count",
        "missing_known_families",
        "all_known_families_present",
        "all_consumer_contracts_satisfied",
    ):
        if field not in manifest:
            raise ValueError(
                f"signal source family catalog manifest missing field: {field}"
            )
    if not isinstance(manifest["missing_known_families"], list):
        raise ValueError(
            "signal source family catalog manifest missing_known_families must be a list"
        )
    if not isinstance(manifest["all_known_families_present"], bool):
        raise ValueError(
            "signal source family catalog manifest all_known_families_present must be a bool"
        )
    if not isinstance(manifest["all_consumer_contracts_satisfied"], bool):
        raise ValueError(
            "signal source family catalog manifest all_consumer_contracts_satisfied must be a bool"
        )


def _resolve_manifest_catalog_path(manifest_path: Path, value: str) -> Path:
    raw_path = Path(value.strip())
    if not value.strip():
        raise ValueError(
            "signal source family catalog manifest catalog_path must not be empty"
        )
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError(
            "signal source family catalog manifest catalog_path must stay inside manifest directory"
        )
    catalog_path = (manifest_path.parent / raw_path).resolve()
    if not catalog_path.exists():
        raise ValueError(
            "signal source family catalog manifest catalog_path does not exist: "
            f"{value}"
        )
    return catalog_path


def _validate_source_catalog_manifest_consistency(
    manifest: Mapping[str, Any],
    *,
    catalog_summary: Mapping[str, Any],
) -> None:
    expected_values = {
        "catalog_sha256": catalog_summary["sha256"],
        "catalog_size_bytes": catalog_summary["size_bytes"],
        "catalog_schema_version": catalog_summary["schema_version"],
        "family_count": catalog_summary["family_count"],
        "known_family_count": catalog_summary["known_family_count"],
        "missing_known_families": catalog_summary["missing_known_families"],
        "all_known_families_present": catalog_summary["all_known_families_present"],
        "all_consumer_contracts_satisfied": catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
    }
    for field, expected in expected_values.items():
        if manifest[field] != expected:
            raise ValueError(
                f"signal source family catalog manifest {field} mismatch: "
                f"{manifest[field]!r} != {expected!r}"
            )


def _consumer_contract_coverage_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    family = str(record.get("family", "")).strip()
    canonical_input = str(record.get("canonical_input", "")).strip()
    if canonical_input != CANONICAL_INPUT_DERIVED_INDICATORS:
        raise ValueError(
            f"signal source family {family} canonical_input must be "
            f"{CANONICAL_INPUT_DERIVED_INDICATORS!r} for current consumer contracts"
        )

    symbols = _normalized_sequence(record.get("symbols"), field="symbols", family=family)
    fields = _normalized_field_set(
        record.get("derived_indicator_fields"),
        field="derived_indicator_fields",
        family=family,
    )
    compatible_profiles = _normalized_sequence(
        record.get("compatible_profiles"),
        field="compatible_profiles",
        family=family,
    )

    required_by_consumer: dict[str, dict[str, list[str]]] = {}
    missing_by_consumer: dict[str, dict[str, list[str]]] = {}
    for consumer in compatible_profiles:
        try:
            required_fields_by_symbol = required_indicator_fields_for_consumer(consumer)
        except SignalConsumerContractError as exc:
            raise ValueError(str(exc)) from exc

        consumer_required: dict[str, list[str]] = {}
        consumer_missing: dict[str, list[str]] = {}
        for raw_symbol, required_fields in required_fields_by_symbol.items():
            symbol = _normalize_symbol(raw_symbol)
            normalized_required = [
                str(field).strip()
                for field in required_fields
                if str(field).strip()
            ]
            consumer_required[symbol] = normalized_required
            missing_fields = [
                field
                for field in normalized_required
                if symbol not in symbols or field.lower() not in fields
            ]
            if missing_fields:
                consumer_missing[symbol] = missing_fields
        required_by_consumer[consumer] = consumer_required
        if consumer_missing:
            missing_by_consumer[consumer] = consumer_missing

    if missing_by_consumer:
        raise ValueError(
            f"signal source family {family} missing required indicator fields: "
            f"{missing_by_consumer}"
        )

    return {
        "canonical_input": canonical_input,
        "compatible_profiles": compatible_profiles,
        "consumer_count": len(compatible_profiles),
        "symbols": symbols,
        "required_indicator_fields_by_consumer": required_by_consumer,
        "all_required_fields_present": True,
    }


def _normalized_sequence(value: object, *, field: str, family: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"signal source family {family} {field} must be a non-empty list")
    normalized = [str(item).strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError(f"signal source family {family} {field} includes empty values")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"signal source family {family} {field} includes duplicates")
    if field == "symbols":
        return [_normalize_symbol(item) for item in normalized]
    return normalized


def _normalized_field_set(value: object, *, field: str, family: str) -> set[str]:
    return {
        item.lower()
        for item in _normalized_sequence(value, field=field, family=family)
    }


def _normalize_symbol(symbol: object) -> str:
    return str(symbol or "").strip().upper().removesuffix(".US")


def _validate_no_sensitive_fields(value: object, *, path: str = "catalog") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(
                    f"signal source family catalog contains forbidden sensitive key at {path}.{key}"
                )
            _validate_no_sensitive_fields(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_no_sensitive_fields(nested, path=f"{path}[{index}]")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
