from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
