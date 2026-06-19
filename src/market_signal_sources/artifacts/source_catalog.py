from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .consumer_contracts import (
    SignalConsumerContractError,
    known_signal_consumers,
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
    "ahr999_30d_slope",
    "ahr999_365d_percentile",
    "ahr999_estimate_price",
    "ahr999_sma",
    "close",
    "cycle_indicator_source",
    "drawdown_252d",
    "gma200",
    "high252",
    "mayer_multiple",
    "mayer_multiple_365d_percentile",
    "momentum_90d",
    "provider_timestamp",
    "realized_volatility_30d",
    "rsi14",
    "sma200",
    "sma200_gap",
)
BTC_CYCLE_SOURCE_PROFILES: tuple[dict[str, object], ...] = (
    {
        "source_id": "local_csv.btc_usd_daily_ohlcv",
        "source_name": "Local BTC daily OHLCV cache",
        "provider_dataset": "btc_usd_daily_ohlcv",
        "produced_fields": BTC_CYCLE_DERIVED_INDICATOR_FIELDS,
        "history_frequency": "daily",
        "point_in_time_status": "cache_snapshot_required",
        "publication_lag_policy": "crypto_daily_close_t_plus_1",
        "research_use_policy": (
            "accepted when raw OHLCV cache hash, provider timestamp, and "
            "transform version are pinned"
        ),
        "source_url": "",
    },
)
BTC_CYCLE_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "us_equity:ibit_smart_dca",
    "research:ibit_btc_ahr999_precomputed",
    "research:ibit_btc_ahr999_helper_precomputed_variants",
    "research:ibit_btc_ahr999_mayer_precomputed",
    "research:ibit_btc_ahr999_mayer_precomputed_variants",
)
US_EQUITY_CONTEXT_SYMBOL = "US-EQUITY-CONTEXT"
US_EQUITY_NASDAQ_SP500_CONTEXT_FIELDS: tuple[str, ...] = (
    "breadth_above_sma200_pct",
    "cape_percentile",
    "provider_timestamp",
    "vix_percentile",
)
US_EQUITY_NASDAQ_SP500_CONTEXT_SOURCE_PROFILES: tuple[dict[str, object], ...] = (
    {
        "source_id": "fred.vixcls",
        "source_name": "Federal Reserve Economic Data VIXCLS",
        "provider_dataset": "VIXCLS",
        "produced_fields": ("vix_percentile",),
        "history_frequency": "daily",
        "point_in_time_status": "public_history_with_execution_lag",
        "max_allowed_lag_days": 10,
        "publication_lag_policy": "use at least T+1 before same-day DCA decisions",
        "research_use_policy": (
            "accepted for research when the downloaded CSV, as_of, and "
            "percentile lookback are hash-pinned"
        ),
        "source_url": "https://fred.stlouisfed.org/series/VIXCLS",
    },
    {
        "source_id": "shiller.cape_monthly",
        "source_name": "Robert Shiller online data CAPE",
        "provider_dataset": "ie_data.xls",
        "produced_fields": ("cape_percentile",),
        "history_frequency": "monthly",
        "point_in_time_status": "public_revised_history_snapshot_required",
        "max_allowed_lag_days": 120,
        "publication_lag_policy": "month-end or later; never same-day daily timing",
        "research_use_policy": (
            "accepted for low-frequency valuation research only when the raw "
            "download snapshot and revision date are preserved"
        ),
        "source_url": "https://www.econ.yale.edu/~shiller/data.htm",
    },
    {
        "source_id": "index_breadth.point_in_time_vendor",
        "source_name": "Point-in-time index breadth history",
        "provider_dataset": "spx_ndx_members_above_sma200_daily",
        "produced_fields": ("breadth_above_sma200_pct",),
        "history_frequency": "daily",
        "point_in_time_status": "requires_point_in_time_vendor_or_breadth_index",
        "publication_lag_policy": "vendor timestamp must be no later than DCA evaluation lag",
        "research_use_policy": (
            "reject current-constituent backfills; use only point-in-time "
            "constituents or an auditable historical breadth index"
        ),
        "source_url": "",
    },
)
US_EQUITY_NASDAQ_SP500_CONTEXT_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "research:nasdaq_sp500_external_context_precomputed",
)
US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_FIELDS: tuple[str, ...] = (
    "cape_percentile",
    "provider_timestamp",
    "vix_percentile",
)
US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_SOURCE_PROFILES: tuple[
    dict[str, object],
    ...,
] = US_EQUITY_NASDAQ_SP500_CONTEXT_SOURCE_PROFILES[:2]
US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "research:nasdaq_sp500_cape_vix_external_context_precomputed",
)
US_EQUITY_PRICE_PROXY_SYMBOL = "US-EQUITY-PRICE-PROXY"
US_EQUITY_NASDAQ_SP500_PRICE_PROXY_FIELDS: tuple[str, ...] = (
    "QQQ",
    "SPY",
    "provider_timestamp",
)
US_EQUITY_NASDAQ_SP500_PRICE_PROXY_SOURCE_PROFILES: tuple[
    dict[str, object],
    ...,
] = (
    {
        "source_id": "fred.nasdaq100",
        "source_name": "Federal Reserve Economic Data NASDAQ100",
        "provider_dataset": "NASDAQ100",
        "produced_fields": ("QQQ",),
        "history_frequency": "daily",
        "point_in_time_status": "public_history_with_execution_lag",
        "max_allowed_lag_days": 10,
        "publication_lag_policy": "use at least T+1 before same-day DCA decisions",
        "research_use_policy": (
            "accepted as a Nasdaq price proxy only when the downloaded CSV, "
            "as_of, and transform version are hash-pinned"
        ),
        "source_url": "https://fred.stlouisfed.org/series/NASDAQ100",
    },
    {
        "source_id": "fred.sp500",
        "source_name": "Federal Reserve Economic Data SP500",
        "provider_dataset": "SP500",
        "produced_fields": ("SPY",),
        "history_frequency": "daily",
        "point_in_time_status": "public_history_with_execution_lag",
        "max_allowed_lag_days": 10,
        "publication_lag_policy": "use at least T+1 before same-day DCA decisions",
        "research_use_policy": (
            "accepted as an S&P 500 price proxy only when the downloaded CSV, "
            "as_of, and transform version are hash-pinned"
        ),
        "source_url": "https://fred.stlouisfed.org/series/SP500",
    },
)
US_EQUITY_NASDAQ_SP500_PRICE_PROXY_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "research:nasdaq_sp500_price_proxy",
)
US_EQUITY_TECHNICAL_DERIVED_INDICATOR_FIELDS: tuple[str, ...] = (
    "atr14",
    "close",
    "drawdown_252d",
    "ema20",
    "ema50",
    "high252",
    "momentum_90d",
    "provider_timestamp",
    "realized_volatility_20d",
    "realized_volatility_63d",
    "rsi14",
    "sma20",
    "sma50",
    "sma100",
    "sma200",
    "sma200_gap",
    "trend_score",
)
US_EQUITY_TECHNICAL_SOURCE_PROFILES: tuple[dict[str, object], ...] = (
    {
        "source_id": "local_csv.us_equity_daily_ohlcv",
        "source_name": "Local US equity daily OHLCV cache",
        "provider_dataset": "us_equity_daily_ohlcv",
        "produced_fields": US_EQUITY_TECHNICAL_DERIVED_INDICATOR_FIELDS,
        "history_frequency": "daily",
        "point_in_time_status": "cache_snapshot_required",
        "publication_lag_policy": "us_equity_daily_close_t_plus_1",
        "research_use_policy": (
            "accepted when raw OHLCV cache hash, provider timestamp, and "
            "technical transform version are pinned"
        ),
        "source_url": "",
    },
)
US_EQUITY_TECHNICAL_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "us_equity:nasdaq_sp500_smart_dca",
)
US_EQUITY_SEMICONDUCTOR_ROTATION_DERIVED_INDICATOR_FIELDS: tuple[str, ...] = (
    "bb_lower",
    "bb_mid",
    "bb_upper",
    "ma20",
    "ma20_slope",
    "ma_trend",
    "price",
    "provider_timestamp",
    "realized_volatility",
    "realized_volatility_10",
    "realized_volatility_10_dynamic_cap",
    "realized_volatility_10_dynamic_floor",
    "realized_volatility_10_dynamic_lookback",
    "realized_volatility_10_dynamic_min_periods",
    "realized_volatility_10_dynamic_percentile",
    "realized_volatility_10_dynamic_sample_count",
    "realized_volatility_10_dynamic_threshold",
    "realized_volatility_20",
    "realized_volatility_dynamic_cap",
    "realized_volatility_dynamic_floor",
    "realized_volatility_dynamic_lookback",
    "realized_volatility_dynamic_min_periods",
    "realized_volatility_dynamic_percentile",
    "realized_volatility_dynamic_sample_count",
    "realized_volatility_dynamic_threshold",
    "rsi14",
    "rsi14_dynamic_threshold",
)
US_EQUITY_SEMICONDUCTOR_ROTATION_SOURCE_PROFILES: tuple[dict[str, object], ...] = (
    {
        "source_id": "local_csv.us_equity_semiconductor_daily_ohlcv",
        "source_name": "Local SOXL/SOXX daily OHLCV cache",
        "provider_dataset": "us_equity_semiconductor_daily_ohlcv",
        "produced_fields": US_EQUITY_SEMICONDUCTOR_ROTATION_DERIVED_INDICATOR_FIELDS,
        "history_frequency": "daily",
        "point_in_time_status": "cache_snapshot_required",
        "publication_lag_policy": "us_equity_daily_close_t_plus_1",
        "research_use_policy": (
            "accepted when both SOXL and SOXX raw OHLCV cache hashes, provider "
            "timestamp, and semiconductor rotation transform version are pinned"
        ),
        "source_url": "",
    },
)
US_EQUITY_SEMICONDUCTOR_ROTATION_COMPATIBLE_PROFILES: tuple[str, ...] = (
    "us_equity:soxl_soxx_trend_income",
)

SIGNAL_SOURCE_DOMAIN_COVERAGE: dict[str, dict[str, object]] = {
    "crypto": {
        "implemented_families": ("crypto.btc_cycle_daily",),
        "planned_families": (
            "crypto.live_pool_feature_catalog",
            "crypto.market_structure_daily",
        ),
        "canonical_inputs": (
            "derived_indicators",
            "market_prices",
            "benchmark_snapshot",
            "universe_snapshot",
        ),
        "provider_boundary": (
            "Crypto market-data, exchange, and on-chain providers stay in "
            "MarketSignalSources or upstream crypto pipelines; strategy repos "
            "consume artifacts only."
        ),
    },
    "us_equity": {
        "implemented_families": (
            "us_equity.technical_daily",
            "us_equity.semiconductor_rotation_daily",
            "us_equity.nasdaq_sp500_context_daily",
            "us_equity.nasdaq_sp500_price_proxy_daily",
            "us_equity.nasdaq_sp500_public_context_daily",
        ),
        "planned_families": (
            "us_equity.index_breadth_daily",
            "us_equity.valuation_macro_context",
            "us_equity.volatility_rates_context",
        ),
        "canonical_inputs": ("derived_indicators", "research_export"),
        "provider_boundary": (
            "US equity breadth, valuation, volatility, and macro providers are "
            "published as source artifacts before strategy runtime consumption."
        ),
    },
    "hk_equity": {
        "implemented_families": (),
        "planned_families": (
            "hk_equity.index_breadth_daily",
            "hk_equity.fx_liquidity_context",
        ),
        "canonical_inputs": ("derived_indicators", "research_export"),
        "provider_boundary": (
            "Hong Kong equity, HKD/USD, and local calendar source adapters stay "
            "outside strategy repos until a hash-pinned artifact contract exists."
        ),
    },
}

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
        "source_profiles": BTC_CYCLE_SOURCE_PROFILES,
        "compatible_profiles": BTC_CYCLE_COMPATIBLE_PROFILES,
        "runtime_consumers": ("us_equity:ibit_smart_dca",),
        "research_consumers": (
            "research:ibit_btc_ahr999_precomputed",
            "research:ibit_btc_ahr999_helper_precomputed_variants",
            "research:ibit_btc_ahr999_mayer_precomputed",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
        ),
    },
    "us_equity.nasdaq_sp500_context_daily": {
        "family": "us_equity.nasdaq_sp500_context_daily",
        "domain": "us_equity",
        "bundle_type": "derived_indicators",
        "bundle_id_prefix": "us_equity.nasdaq_sp500.context",
        "canonical_input": "derived_indicators",
        "transform": "us_equity.nasdaq_sp500.context.v1",
        "provider_dataset": "nasdaq_sp500_external_context_daily",
        "freshness_policy": "us_equity_research_context_t_plus_1",
        "minimum_history_rows": 1,
        "symbols": (US_EQUITY_CONTEXT_SYMBOL,),
        "derived_indicator_fields": US_EQUITY_NASDAQ_SP500_CONTEXT_FIELDS,
        "source_profiles": US_EQUITY_NASDAQ_SP500_CONTEXT_SOURCE_PROFILES,
        "compatible_profiles": US_EQUITY_NASDAQ_SP500_CONTEXT_COMPATIBLE_PROFILES,
        "runtime_consumers": (),
        "research_consumers": US_EQUITY_NASDAQ_SP500_CONTEXT_COMPATIBLE_PROFILES,
    },
    "us_equity.technical_daily": {
        "family": "us_equity.technical_daily",
        "domain": "us_equity",
        "bundle_type": "derived_indicators",
        "bundle_id_prefix": "us_equity.technical.daily",
        "canonical_input": "derived_indicators",
        "transform": "technical.daily_ohlcv.v1",
        "provider_dataset": "us_equity_daily_ohlcv",
        "freshness_policy": "us_equity_daily_close_t_plus_1",
        "minimum_history_rows": 252,
        "symbols": ("QQQ", "SPY"),
        "derived_indicator_fields": US_EQUITY_TECHNICAL_DERIVED_INDICATOR_FIELDS,
        "source_profiles": US_EQUITY_TECHNICAL_SOURCE_PROFILES,
        "compatible_profiles": US_EQUITY_TECHNICAL_COMPATIBLE_PROFILES,
        "runtime_consumers": US_EQUITY_TECHNICAL_COMPATIBLE_PROFILES,
        "research_consumers": (),
    },
    "us_equity.semiconductor_rotation_daily": {
        "family": "us_equity.semiconductor_rotation_daily",
        "domain": "us_equity",
        "bundle_type": "derived_indicators",
        "bundle_id_prefix": "us_equity.semiconductor_rotation.daily",
        "canonical_input": "derived_indicators",
        "transform": "us_equity.semiconductor_rotation.v1",
        "provider_dataset": "us_equity_semiconductor_daily_ohlcv",
        "freshness_policy": "us_equity_daily_close_t_plus_1",
        "minimum_history_rows": 420,
        "symbols": ("SOXL", "SOXX"),
        "derived_indicator_fields": (
            US_EQUITY_SEMICONDUCTOR_ROTATION_DERIVED_INDICATOR_FIELDS
        ),
        "source_profiles": US_EQUITY_SEMICONDUCTOR_ROTATION_SOURCE_PROFILES,
        "compatible_profiles": US_EQUITY_SEMICONDUCTOR_ROTATION_COMPATIBLE_PROFILES,
        "runtime_consumers": US_EQUITY_SEMICONDUCTOR_ROTATION_COMPATIBLE_PROFILES,
        "research_consumers": (),
    },
    "us_equity.nasdaq_sp500_public_context_daily": {
        "family": "us_equity.nasdaq_sp500_public_context_daily",
        "domain": "us_equity",
        "bundle_type": "derived_indicators",
        "bundle_id_prefix": "us_equity.nasdaq_sp500.public_context",
        "canonical_input": "derived_indicators",
        "transform": "us_equity.nasdaq_sp500.context.v1",
        "provider_dataset": "nasdaq_sp500_public_context_daily",
        "freshness_policy": "us_equity_research_context_t_plus_1",
        "minimum_history_rows": 1,
        "symbols": (US_EQUITY_CONTEXT_SYMBOL,),
        "derived_indicator_fields": US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_FIELDS,
        "source_profiles": US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_SOURCE_PROFILES,
        "compatible_profiles": US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_COMPATIBLE_PROFILES,
        "runtime_consumers": (),
        "research_consumers": US_EQUITY_NASDAQ_SP500_PUBLIC_CONTEXT_COMPATIBLE_PROFILES,
    },
    "us_equity.nasdaq_sp500_price_proxy_daily": {
        "family": "us_equity.nasdaq_sp500_price_proxy_daily",
        "domain": "us_equity",
        "bundle_type": "research_export",
        "bundle_id_prefix": "us_equity.nasdaq_sp500.price_proxy",
        "canonical_input": "derived_indicators",
        "transform": "us_equity.nasdaq_sp500.price_proxy.v1",
        "provider_dataset": "fred_nasdaq100_sp500_daily",
        "freshness_policy": "us_equity_price_proxy_t_plus_1",
        "minimum_history_rows": 1,
        "symbols": (US_EQUITY_PRICE_PROXY_SYMBOL,),
        "derived_indicator_fields": US_EQUITY_NASDAQ_SP500_PRICE_PROXY_FIELDS,
        "source_profiles": US_EQUITY_NASDAQ_SP500_PRICE_PROXY_SOURCE_PROFILES,
        "compatible_profiles": US_EQUITY_NASDAQ_SP500_PRICE_PROXY_COMPATIBLE_PROFILES,
        "runtime_consumers": (),
        "research_consumers": US_EQUITY_NASDAQ_SP500_PRICE_PROXY_COMPATIBLE_PROFILES,
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


def runtime_consumers_for_signal_source_family(family: str) -> tuple[str, ...]:
    """Return runtime consumers for a known signal source family."""

    record = signal_source_family_record(family)
    return tuple(str(consumer) for consumer in record.get("runtime_consumers", ()))


def implemented_signal_source_families_for_domain(domain: str) -> tuple[str, ...]:
    """Return implemented source families for a known market domain."""

    normalized = str(domain or "").strip()
    if normalized not in SIGNAL_SOURCE_DOMAIN_COVERAGE:
        known = ", ".join(sorted(SIGNAL_SOURCE_DOMAIN_COVERAGE))
        raise ValueError(f"unknown signal source domain: {domain!r}; known: {known}")
    implemented = SIGNAL_SOURCE_DOMAIN_COVERAGE[normalized]["implemented_families"]
    return tuple(str(family) for family in implemented)


def source_profiles_for_signal_source_family(family: str) -> tuple[dict[str, Any], ...]:
    """Return source-profile requirements for a known signal source family."""

    record = signal_source_family_record(family)
    return tuple(
        dict(profile)
        for profile in record.get("source_profiles", [])
    )


def signal_source_family_consumer_contract_coverage(family: str) -> dict[str, Any]:
    """Return consumer-contract coverage metadata for a known source family."""

    return _consumer_contract_coverage_summary(signal_source_family_record(family))


def signal_source_runtime_consumer_coverage() -> dict[str, Any]:
    """Return runtime consumer coverage across all known source families."""

    return _runtime_consumer_coverage_summary(
        tuple(
            signal_source_family_record(family)
            for family in known_signal_source_families()
        )
    )


def signal_source_domain_coverage_payload() -> dict[str, Any]:
    """Return the cross-market source-family roadmap in JSON-safe form."""

    return _json_safe_value(SIGNAL_SOURCE_DOMAIN_COVERAGE)


def signal_source_family_catalog_payload(
    *,
    families: Iterable[str] | None = None,
    domains: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return JSON-safe metadata for all known signal source families."""

    if families is not None and domains is not None:
        raise ValueError("provide either families or domains, not both")
    if domains is not None:
        selected_families = _families_for_domains(domains)
    elif families is not None:
        selected_families = tuple(families)
    else:
        selected_families = known_signal_source_families()
    return {
        "schema_version": SIGNAL_SOURCE_FAMILY_CATALOG_SCHEMA_VERSION,
        "domain_coverage": signal_source_domain_coverage_payload(),
        "families": [
            signal_source_family_record(family)
            for family in selected_families
        ],
    }


def write_signal_source_family_catalog(
    path: str | PathLike[str],
    *,
    families: Iterable[str] | None = None,
    domains: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Write the signal source family catalog and return hash metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = signal_source_family_catalog_payload(
        families=families,
        domains=domains,
    )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_signal_source_family_catalog_file(output_path)


def write_signal_source_family_catalog_artifacts(
    output_dir: str | PathLike[str],
    *,
    families: Iterable[str] | None = None,
    domains: Iterable[str] | None = None,
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
        domains=domains,
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
    source_profiles_by_family: dict[str, Any] = {}
    records: list[Mapping[str, Any]] = []
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
        if record != expected_record and not _matches_legacy_source_profile_record(
            record,
            expected_record,
        ):
            raise ValueError(f"signal source family record drift: {family}")
        records.append(record)
        coverage_by_family[family] = _consumer_contract_coverage_summary(record)
        source_profiles_by_family[family] = _source_profile_summary(record)

    domain_coverage_summary = _validate_domain_coverage(
        payload.get("domain_coverage")
    )
    missing_known_families = sorted(set(SIGNAL_SOURCE_FAMILIES) - set(family_names))
    if require_all_known_families and missing_known_families:
        raise ValueError(
            "missing known signal source families: "
            + ", ".join(missing_known_families)
        )
    runtime_consumer_coverage = _runtime_consumer_coverage_summary(records)

    return {
        "schema_version": payload["schema_version"],
        "family_count": len(family_names),
        "families": family_names,
        "known_family_count": len(SIGNAL_SOURCE_FAMILIES),
        "missing_known_families": missing_known_families,
        "all_known_families_present": not missing_known_families,
        **domain_coverage_summary,
        "consumer_contract_coverage": coverage_by_family,
        "all_consumer_contracts_satisfied": all(
            bool(summary["all_required_fields_present"])
            for summary in coverage_by_family.values()
        ),
        "runtime_consumer_coverage": runtime_consumer_coverage,
        "all_runtime_consumers_covered": runtime_consumer_coverage[
            "all_runtime_consumers_covered"
        ],
        "source_profile_count": sum(
            int(summary["source_profile_count"])
            for summary in source_profiles_by_family.values()
        ),
        "source_profile_coverage": source_profiles_by_family,
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
    return _json_safe_value(record)


def _families_for_domains(domains: Iterable[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        for family in implemented_signal_source_families_for_domain(domain):
            if family not in seen:
                seen.add(family)
                selected.append(family)
    return tuple(selected)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, tuple | list):
        return [_json_safe_value(item) for item in value]
    return value


def _matches_legacy_source_profile_record(
    record: Mapping[str, Any],
    expected_record: Mapping[str, Any],
) -> bool:
    if "source_profiles" in record:
        return False
    expected_without_profiles = dict(expected_record)
    expected_without_profiles.pop("source_profiles", None)
    return dict(record) == expected_without_profiles


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
        "source_profile_count": catalog_summary["source_profile_count"],
        "all_consumer_contracts_satisfied": catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": catalog_summary[
            "all_runtime_consumers_covered"
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
        "domain_coverage_present": catalog_summary["domain_coverage_present"],
        "domains": catalog_summary["domains"],
        "domain_count": catalog_summary["domain_count"],
        "implemented_family_count": catalog_summary["implemented_family_count"],
        "planned_family_count": catalog_summary["planned_family_count"],
        "all_consumer_contracts_satisfied": catalog_summary[
            "all_consumer_contracts_satisfied"
        ],
        "all_runtime_consumers_covered": catalog_summary[
            "all_runtime_consumers_covered"
        ],
        "source_profile_count": catalog_summary["source_profile_count"],
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
    if (
        "all_runtime_consumers_covered" in manifest
        and not isinstance(manifest["all_runtime_consumers_covered"], bool)
    ):
        raise ValueError(
            "signal source family catalog manifest all_runtime_consumers_covered must be a bool"
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
    if "source_profile_count" in manifest:
        expected_values["source_profile_count"] = catalog_summary["source_profile_count"]
    if "all_runtime_consumers_covered" in manifest:
        expected_values["all_runtime_consumers_covered"] = catalog_summary[
            "all_runtime_consumers_covered"
        ]
    for field, expected in expected_values.items():
        if manifest[field] != expected:
            raise ValueError(
                f"signal source family catalog manifest {field} mismatch: "
                f"{manifest[field]!r} != {expected!r}"
            )


def _validate_domain_coverage(value: object) -> dict[str, Any]:
    if value is None:
        return {
            "domain_coverage_present": False,
            "domains": [],
            "domain_count": 0,
            "implemented_family_count": 0,
            "planned_family_count": 0,
        }
    if not isinstance(value, Mapping) or not value:
        raise ValueError(
            "signal source family catalog domain_coverage must be an object"
        )

    expected = signal_source_domain_coverage_payload()
    if value != expected:
        raise ValueError("signal source family catalog domain_coverage drift")

    implemented_families: list[str] = []
    planned_families: list[str] = []
    for domain, record in value.items():
        normalized_domain = str(domain).strip()
        if not normalized_domain:
            raise ValueError("signal source family catalog domain must not be empty")
        if not isinstance(record, Mapping):
            raise ValueError(
                "signal source family catalog domain_coverage records must be objects"
            )
        implemented = _normalized_sequence(
            record.get("implemented_families"),
            field="implemented_families",
            family=normalized_domain,
            allow_empty=True,
        )
        planned = _normalized_sequence(
            record.get("planned_families"),
            field="planned_families",
            family=normalized_domain,
            allow_empty=True,
        )
        _normalized_sequence(
            record.get("canonical_inputs"),
            field="canonical_inputs",
            family=normalized_domain,
        )
        provider_boundary = str(record.get("provider_boundary", "")).strip()
        if not provider_boundary:
            raise ValueError(
                "signal source family catalog "
                f"{normalized_domain} provider_boundary is required"
            )
        implemented_families.extend(implemented)
        planned_families.extend(planned)

    duplicate_implemented = _duplicate_values(implemented_families)
    if duplicate_implemented:
        raise ValueError(
            "signal source family catalog domain_coverage duplicates "
            "implemented families: "
            + ", ".join(duplicate_implemented)
        )
    duplicate_planned = _duplicate_values(planned_families)
    if duplicate_planned:
        raise ValueError(
            "signal source family catalog domain_coverage duplicates "
            "planned families: "
            + ", ".join(duplicate_planned)
        )

    implemented_set = set(implemented_families)
    planned_set = set(planned_families)
    unknown_implemented = sorted(implemented_set - set(SIGNAL_SOURCE_FAMILIES))
    if unknown_implemented:
        raise ValueError(
            "signal source family catalog domain_coverage unknown implemented "
            "families: "
            + ", ".join(unknown_implemented)
        )
    unassigned_known = sorted(set(SIGNAL_SOURCE_FAMILIES) - implemented_set)
    if unassigned_known:
        raise ValueError(
            "signal source family catalog domain_coverage missing implemented "
            "families: "
            + ", ".join(unassigned_known)
        )
    planned_overlap = sorted(implemented_set & planned_set)
    if planned_overlap:
        raise ValueError(
            "signal source family catalog domain_coverage planned families include "
            "implemented families: "
            + ", ".join(planned_overlap)
        )

    return {
        "domain_coverage_present": True,
        "domains": sorted(str(domain) for domain in value),
        "domain_count": len(value),
        "implemented_family_count": len(implemented_families),
        "planned_family_count": len(planned_families),
    }


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


def _runtime_consumer_coverage_summary(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    known_runtime_consumers = tuple(
        consumer
        for consumer in known_signal_consumers()
        if not consumer.startswith("research:")
    )
    source_families_by_consumer: dict[str, list[str]] = {
        consumer: []
        for consumer in known_runtime_consumers
    }
    runtime_consumers_seen: set[str] = set()
    unknown_runtime_consumers: set[str] = set()
    consumer_scope_errors: list[str] = []

    for record in records:
        family = str(record.get("family", "")).strip()
        compatible_profiles = set(
            _normalized_sequence(
                record.get("compatible_profiles"),
                field="compatible_profiles",
                family=family,
            )
        )
        runtime_consumers = set(
            _normalized_sequence(
                record.get("runtime_consumers"),
                field="runtime_consumers",
                family=family,
                allow_empty=True,
            )
        )
        research_consumers = set(
            _normalized_sequence(
                record.get("research_consumers"),
                field="research_consumers",
                family=family,
                allow_empty=True,
            )
        )
        declared_consumers = runtime_consumers | research_consumers
        if declared_consumers != compatible_profiles:
            consumer_scope_errors.append(f"{family}:consumer_scope_mismatch")
        if runtime_consumers & research_consumers:
            consumer_scope_errors.append(f"{family}:runtime_research_consumer_overlap")

        for consumer in runtime_consumers:
            if consumer.startswith("research:"):
                consumer_scope_errors.append(f"{family}:research_consumer_marked_runtime")
                continue
            runtime_consumers_seen.add(consumer)
            if consumer in source_families_by_consumer:
                source_families_by_consumer[consumer].append(family)
            else:
                unknown_runtime_consumers.add(consumer)

        for consumer in research_consumers:
            if not consumer.startswith("research:"):
                consumer_scope_errors.append(f"{family}:runtime_consumer_marked_research")

    missing_runtime_consumers = tuple(
        consumer
        for consumer, families in source_families_by_consumer.items()
        if not families
    )
    return {
        "known_runtime_consumers": known_runtime_consumers,
        "known_runtime_consumer_count": len(known_runtime_consumers),
        "runtime_consumers": tuple(sorted(runtime_consumers_seen)),
        "runtime_consumer_count": len(runtime_consumers_seen),
        "runtime_consumer_source_families": {
            consumer: tuple(families)
            for consumer, families in sorted(source_families_by_consumer.items())
        },
        "runtime_consumers_without_source_family": missing_runtime_consumers,
        "unknown_runtime_consumers": tuple(sorted(unknown_runtime_consumers)),
        "consumer_scope_errors": tuple(consumer_scope_errors),
        "all_runtime_consumers_covered": (
            not missing_runtime_consumers
            and not unknown_runtime_consumers
            and not consumer_scope_errors
        ),
    }


def _source_profile_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    family = str(record.get("family", "")).strip()
    fields = _normalized_field_set(
        record.get("derived_indicator_fields"),
        field="derived_indicator_fields",
        family=family,
    )
    raw_profiles = record.get("source_profiles")
    if raw_profiles is None:
        return {
            "source_profile_count": 0,
            "source_ids": [],
            "covered_fields": [],
            "profiles": [],
        }
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError(f"signal source family {family} source_profiles must be a list")

    seen: set[str] = set()
    profile_summaries: list[dict[str, object]] = []
    for profile in raw_profiles:
        if not isinstance(profile, Mapping):
            raise ValueError(
                f"signal source family {family} source_profiles records must be objects"
            )
        source_id = str(profile.get("source_id", "")).strip()
        if not source_id:
            raise ValueError(
                f"signal source family {family} source_profiles source_id is required"
            )
        if source_id in seen:
            raise ValueError(
                f"signal source family {family} source_profiles duplicate source_id: "
                f"{source_id}"
            )
        seen.add(source_id)
        produced_fields = _normalized_sequence(
            profile.get("produced_fields"),
            field="source_profiles.produced_fields",
            family=family,
        )
        unknown_fields = sorted(
            field
            for field in produced_fields
            if field.lower() not in fields
        )
        if unknown_fields:
            raise ValueError(
                f"signal source family {family} source profile {source_id} "
                "produced fields are not derived_indicator_fields: "
                + ", ".join(unknown_fields)
            )
        required_text_fields = (
            "source_name",
            "provider_dataset",
            "history_frequency",
            "point_in_time_status",
            "publication_lag_policy",
            "research_use_policy",
        )
        for field in required_text_fields:
            if not str(profile.get(field, "")).strip():
                raise ValueError(
                    f"signal source family {family} source profile {source_id} "
                    f"{field} is required"
                )
        max_allowed_lag_days = profile.get("max_allowed_lag_days")
        if max_allowed_lag_days is not None:
            if (
                not isinstance(max_allowed_lag_days, int)
                or isinstance(max_allowed_lag_days, bool)
                or max_allowed_lag_days < 0
            ):
                raise ValueError(
                    f"signal source family {family} source profile {source_id} "
                    "max_allowed_lag_days must be a non-negative integer"
                )
        profile_summary: dict[str, object] = {
            "source_id": source_id,
            "produced_fields": produced_fields,
            "point_in_time_status": str(profile["point_in_time_status"]),
            "history_frequency": str(profile["history_frequency"]),
        }
        if max_allowed_lag_days is not None:
            profile_summary["max_allowed_lag_days"] = max_allowed_lag_days
        profile_summaries.append(profile_summary)

    covered_fields = sorted(
        {
            field
            for summary in profile_summaries
            for field in summary["produced_fields"]
        }
    )
    return {
        "source_profile_count": len(profile_summaries),
        "source_ids": [str(summary["source_id"]) for summary in profile_summaries],
        "covered_fields": covered_fields,
        "profiles": profile_summaries,
    }


def _normalized_sequence(
    value: object,
    *,
    field: str,
    family: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"signal source family {family} {field} must be a list")
    if not value:
        if allow_empty:
            return []
        raise ValueError(
            f"signal source family {family} {field} must be a non-empty list"
        )
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


def _duplicate_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


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
