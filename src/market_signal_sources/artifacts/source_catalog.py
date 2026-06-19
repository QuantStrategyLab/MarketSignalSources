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


def validate_signal_source_family_catalog(
    payload: Mapping[str, Any],
    *,
    require_all_known_families: bool = False,
) -> dict[str, Any]:
    """Validate a signal source family catalog payload."""

    if not isinstance(payload, Mapping):
        raise ValueError("signal source family catalog payload must be an object")
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
