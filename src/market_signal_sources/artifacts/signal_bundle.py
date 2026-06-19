from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd

from market_signal_sources.derived.crypto.btc_cycle import compute_btc_cycle_indicators


MARKET_SIGNAL_BUNDLE_SCHEMA_VERSION = "market_signal_bundle.v1"
MARKET_SIGNAL_MANIFEST_SCHEMA_VERSION = "market_signal_manifest.v1"
MARKET_SIGNAL_INDEX_SCHEMA_VERSION = "market_signal_index.v1"
CANONICAL_INPUT_DERIVED_INDICATORS = "derived_indicators"
FRESHNESS_FRESH = "fresh"


def build_derived_indicator_signal_bundle(
    *,
    domain: str,
    bundle_id: str,
    as_of: str,
    generated_at: str,
    symbols: Iterable[str],
    derived_indicators: Mapping[str, Mapping[str, Any]],
    freshness: Mapping[str, Any],
    provenance: Mapping[str, Any],
    compatible_profiles: Iterable[str],
    min_strategy_contract: str = "derived_indicators+portfolio_snapshot",
) -> dict[str, Any]:
    """Build a market_signal_bundle.v1 derived_indicators envelope."""

    normalized_as_of = _normalize_date(as_of)
    normalized_symbols = [
        _non_empty(symbol, "symbols item")
        for symbol in symbols
    ]
    if not normalized_symbols:
        raise ValueError("symbols must include at least one symbol")
    normalized_profiles = [
        _non_empty(profile, "compatible_profiles item")
        for profile in compatible_profiles
    ]
    if not normalized_profiles:
        raise ValueError("compatible_profiles must include at least one profile")

    indicators_by_symbol: dict[str, dict[str, Any]] = {}
    source_indicators = {
        str(symbol).strip(): payload
        for symbol, payload in derived_indicators.items()
    }
    for symbol in normalized_symbols:
        payload = source_indicators.get(symbol)
        if not isinstance(payload, Mapping) or not payload:
            raise ValueError(f"derived_indicators missing non-empty payload for {symbol}")
        indicators_by_symbol[symbol] = dict(payload)

    return {
        "schema_version": MARKET_SIGNAL_BUNDLE_SCHEMA_VERSION,
        "bundle_id": _non_empty(bundle_id, "bundle_id"),
        "bundle_type": CANONICAL_INPUT_DERIVED_INDICATORS,
        "domain": _non_empty(domain, "domain"),
        "consumer_contract": {
            "canonical_input": CANONICAL_INPUT_DERIVED_INDICATORS,
            "compatible_profiles": normalized_profiles,
            "min_strategy_contract": _non_empty(
                min_strategy_contract,
                "min_strategy_contract",
            ),
        },
        "as_of": normalized_as_of,
        "generated_at": _non_empty(generated_at, "generated_at"),
        "symbols": normalized_symbols,
        CANONICAL_INPUT_DERIVED_INDICATORS: indicators_by_symbol,
        "freshness": dict(freshness),
        "provenance": dict(provenance),
    }


def build_btc_cycle_signal_bundle(
    ohlcv: pd.DataFrame,
    *,
    as_of: str,
    symbol: str = "BTC-USD",
    provider: str = "local_csv",
    provider_dataset: str = "btc_usd_daily_ohlcv",
    raw_artifact_sha256: str,
    source_repo: str = "QuantStrategyLab/MarketSignalSources",
    source_version: str = "0.1.0",
    code_commit: str = "0000000000000000000000000000000000000000",
    generated_at: str,
    freshness_status: str = FRESHNESS_FRESH,
    freshness_policy: str = "crypto_daily_close_t_plus_1",
    max_age_hours: int = 36,
) -> dict[str, Any]:
    """Build a market_signal_bundle.v1 BTC cycle derived_indicators payload."""

    normalized_symbol = _non_empty(symbol, "symbol")
    normalized_as_of = _normalize_date(as_of)
    indicators = compute_btc_cycle_indicators(ohlcv, as_of=normalized_as_of)
    indicators["provider_timestamp"] = f"{normalized_as_of}T00:00:00Z"

    return build_derived_indicator_signal_bundle(
        domain="crypto",
        bundle_id=f"crypto.btc.derived_indicators.{normalized_as_of}",
        as_of=normalized_as_of,
        generated_at=generated_at,
        symbols=(normalized_symbol,),
        derived_indicators={normalized_symbol: indicators},
        freshness={
            "policy": freshness_policy,
            "max_age_hours": int(max_age_hours),
            "provider_timestamp": f"{normalized_as_of}T00:00:00Z",
            "status": freshness_status,
        },
        provenance={
            "source_repo": _non_empty(source_repo, "source_repo"),
            "source_version": _non_empty(source_version, "source_version"),
            "code_commit": _non_empty(code_commit, "code_commit"),
            "provider": _non_empty(provider, "provider"),
            "provider_dataset": _non_empty(provider_dataset, "provider_dataset"),
            "raw_artifact_sha256": _non_empty(raw_artifact_sha256, "raw_artifact_sha256"),
            "transform": "crypto.btc.ahr999.v1",
            "license_scope": "internal_runtime",
            "generated_by": "market_signal_sources.local_csv",
        },
        compatible_profiles=(
            "us_equity:ibit_smart_dca",
            "research:ibit_btc_ahr999_mayer_precomputed",
            "research:ibit_btc_ahr999_mayer_precomputed_variants",
        ),
    )


def write_signal_bundle_artifacts(
    output_dir: str | PathLike[str],
    bundle: dict[str, Any],
    *,
    quality_report_path: str | PathLike[str] | None = None,
    validate_after_write: bool = True,
) -> dict[str, Path]:
    """Write signal bundle, manifest, and local index artifacts."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    bundle_path = output_path / "signal_bundle.json"
    manifest_path = output_path / "manifest.json"
    index_path = output_path / "index.json"

    _write_json(bundle_path, bundle)
    bundle_sha256 = _sha256_file(bundle_path)
    manifest = _manifest_for_bundle(
        bundle,
        bundle_sha256=bundle_sha256,
        output_root=output_path,
        quality_report_path=quality_report_path,
    )
    _write_json(manifest_path, manifest)
    manifest_sha256 = _sha256_file(manifest_path)
    index = _index_for_manifest(manifest, manifest_sha256=manifest_sha256)
    _write_json(index_path, index)
    if validate_after_write:
        _validate_written_signal_bundle_index(index_path, bundle)

    return {
        "signal_bundle": bundle_path,
        "manifest": manifest_path,
        "index": index_path,
    }


def _manifest_for_bundle(
    bundle: dict[str, Any],
    *,
    bundle_sha256: str,
    output_root: Path,
    quality_report_path: str | PathLike[str] | None,
) -> dict[str, Any]:
    freshness = bundle.get("freshness")
    if not isinstance(freshness, dict):
        raise ValueError("bundle freshness must be a mapping")
    manifest = {
        "schema_version": MARKET_SIGNAL_MANIFEST_SCHEMA_VERSION,
        "bundle_path": "signal_bundle.json",
        "bundle_sha256": bundle_sha256,
        "bundle_id": bundle["bundle_id"],
        "as_of": bundle["as_of"],
        "canonical_input": bundle["consumer_contract"]["canonical_input"],
        "bundle_schema_version": bundle["schema_version"],
        "freshness_status": freshness.get("status", ""),
    }
    if quality_report_path is not None:
        quality_path = Path(quality_report_path).resolve()
        root = output_root.resolve()
        try:
            relative_quality_path = quality_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("quality_report_path must stay inside output_dir") from exc
        manifest.update(
            {
                "quality_report_path": relative_quality_path.as_posix(),
                "quality_report_sha256": _sha256_file(quality_path),
            }
        )
    return manifest


def _index_for_manifest(manifest: dict[str, Any], *, manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_INDEX_SCHEMA_VERSION,
        "generated_at": f"{manifest['as_of']}T00:15:00Z",
        "bundles": [
            {
                "manifest_path": "manifest.json",
                "manifest_sha256": manifest_sha256,
                "bundle_id": manifest["bundle_id"],
                "as_of": manifest["as_of"],
                "canonical_input": manifest["canonical_input"],
                "freshness_status": manifest.get("freshness_status", ""),
            }
        ],
    }


def sha256_file(path: str | PathLike[str]) -> str:
    return _sha256_file(Path(path))


def _validate_written_signal_bundle_index(index_path: Path, bundle: dict[str, Any]) -> None:
    freshness = bundle.get("freshness")
    freshness_status = ""
    if isinstance(freshness, dict):
        freshness_status = str(freshness.get("status", "")).strip()
    from .validation import validate_signal_bundle_index

    validate_signal_bundle_index(
        index_path,
        as_of=str(bundle.get("as_of", "")).strip() or None,
        bundle_id=str(bundle.get("bundle_id", "")).strip() or None,
        accepted_freshness_statuses=(freshness_status or FRESHNESS_FRESH,),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalize_date(value: str) -> str:
    return pd.Timestamp(value).normalize().date().isoformat()


def _non_empty(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized
