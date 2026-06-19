from __future__ import annotations

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


def signal_source_family_catalog_payload() -> dict[str, Any]:
    """Return JSON-safe metadata for all known signal source families."""

    return {
        "schema_version": SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION,
        "families": [
            signal_source_family_record(family)
            for family in known_signal_source_families()
        ],
    }


def _json_safe_record(record: dict[str, object]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, tuple):
            safe[key] = list(value)
        else:
            safe[key] = value
    return safe
