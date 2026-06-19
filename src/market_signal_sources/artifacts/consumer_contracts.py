from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .signal_bundle import CANONICAL_INPUT_DERIVED_INDICATORS


MARKET_SIGNAL_CONSUMER_CONTRACTS_SCHEMA_VERSION = "market_signal_consumer_contracts.v1"
MARKET_SIGNAL_CONSUMER_CONTRACT_MANIFEST_SCHEMA_VERSION = (
    "market_signal_consumer_contract_manifest.v1"
)

CONSUMER_REQUIRED_INDICATOR_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "us_equity:ibit_smart_dca": {
        "BTC-USD": (
            "close",
            "sma200",
            "sma200_gap",
            "rsi14",
            "ahr999",
            "ahr999_sma",
            "mayer_multiple",
        ),
    },
    "us_equity:nasdaq_sp500_smart_dca": {
        "QQQ": (
            "close",
            "sma50",
            "sma200",
            "high252",
            "drawdown_252d",
            "sma200_gap",
            "rsi14",
        ),
        "SPY": (
            "close",
            "sma50",
            "sma200",
            "high252",
            "drawdown_252d",
            "sma200_gap",
            "rsi14",
        ),
    },
    "us_equity:soxl_soxx_trend_income": {
        "SOXL": (
            "price",
            "ma_trend",
        ),
        "SOXX": (
            "price",
            "ma_trend",
            "ma20",
            "ma20_slope",
            "rsi14",
            "rsi14_dynamic_threshold",
            "bb_upper",
            "realized_volatility_10",
            "realized_volatility_10_dynamic_threshold",
            "realized_volatility_10_dynamic_sample_count",
        ),
    },
    "research:nasdaq_sp500_external_context_precomputed": {
        "US-EQUITY-CONTEXT": (
            "breadth_above_sma200_pct",
            "cape_percentile",
            "vix_percentile",
        ),
    },
    "research:nasdaq_sp500_cape_vix_external_context_precomputed": {
        "US-EQUITY-CONTEXT": (
            "cape_percentile",
            "vix_percentile",
        ),
    },
    "research:nasdaq_sp500_price_proxy": {
        "US-EQUITY-PRICE-PROXY": (
            "QQQ",
            "SPY",
        ),
    },
    "research:ibit_btc_ahr999_precomputed": {
        "BTC-USD": ("ahr999",),
    },
    "research:ibit_btc_ahr999_helper_precomputed_variants": {
        "BTC-USD": ("ahr999", "ahr999_365d_percentile", "ahr999_30d_slope"),
    },
    "research:ibit_btc_ahr999_mayer_precomputed": {
        "BTC-USD": ("ahr999", "mayer_multiple"),
    },
    "research:ibit_btc_ahr999_mayer_precomputed_variants": {
        "BTC-USD": ("ahr999", "ahr999_sma", "mayer_multiple"),
    },
}
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


class SignalConsumerContractError(ValueError):
    """Raised when a requested signal consumer contract is unknown."""


def known_signal_consumers() -> tuple[str, ...]:
    """Return known consumer identifiers in stable order."""

    return tuple(sorted(CONSUMER_REQUIRED_INDICATOR_FIELDS))


def required_indicator_fields_for_consumer(
    consumer: str,
) -> dict[str, tuple[str, ...]]:
    """Return required derived indicator fields for a known downstream consumer."""

    normalized = str(consumer or "").strip()
    if normalized not in CONSUMER_REQUIRED_INDICATOR_FIELDS:
        known = ", ".join(known_signal_consumers())
        raise SignalConsumerContractError(
            f"unknown signal bundle consumer: {consumer!r}; known: {known}"
        )
    return {
        symbol: tuple(fields)
        for symbol, fields in CONSUMER_REQUIRED_INDICATOR_FIELDS[normalized].items()
    }


def consumer_contract_for(consumer: str) -> dict[str, Any]:
    """Return a JSON-safe consumer contract record."""

    return _contract_record(
        consumer,
        required_indicator_fields_for_consumer(consumer),
    )


def consumer_contract_registry_payload(
    *,
    consumers: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return JSON-safe consumer contracts for platform and strategy CI checks."""

    selected_consumers = (
        tuple(consumers)
        if consumers is not None
        else known_signal_consumers()
    )
    return {
        "schema_version": MARKET_SIGNAL_CONSUMER_CONTRACTS_SCHEMA_VERSION,
        "canonical_input": CANONICAL_INPUT_DERIVED_INDICATORS,
        "contracts": [
            consumer_contract_for(consumer)
            for consumer in selected_consumers
        ],
    }


def write_consumer_contract_registry(
    path: str | PathLike[str],
    *,
    consumers: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Write consumer contracts as a JSON artifact and return hash metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = consumer_contract_registry_payload(consumers=consumers)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contracts = payload["contracts"]
    contract_consumers = [str(contract["consumer"]) for contract in contracts]
    missing_known_consumers = sorted(
        set(CONSUMER_REQUIRED_INDICATOR_FIELDS) - set(contract_consumers)
    )
    canonical_payload_sha256 = _canonical_registry_payload_sha256(payload)
    local_payload_sha256 = _local_registry_payload_sha256(contract_consumers)
    return {
        "path": str(output_path),
        "schema_version": payload["schema_version"],
        "canonical_input": payload["canonical_input"],
        "consumer_count": len(contracts),
        "consumers": contract_consumers,
        "known_consumer_count": len(CONSUMER_REQUIRED_INDICATOR_FIELDS),
        "missing_known_consumers": missing_known_consumers,
        "all_known_consumers_present": not missing_known_consumers,
        "canonical_registry_payload_sha256": canonical_payload_sha256,
        "local_registry_payload_sha256": local_payload_sha256,
        "local_contract_registry_verified": (
            canonical_payload_sha256 == local_payload_sha256
        ),
        "sha256": _sha256_file(output_path),
        "size_bytes": output_path.stat().st_size,
    }


def write_consumer_contract_registry_artifacts(
    output_dir: str | PathLike[str],
    *,
    consumers: Iterable[str] | None = None,
    registry_filename: str = "market_signal_consumers.json",
    manifest_filename: str = "market_signal_consumers.manifest.json",
) -> dict[str, Any]:
    """Write a registry JSON artifact plus a manifest with registry hash metadata."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    registry_path = _artifact_child_path(
        output_path,
        registry_filename,
        field="registry_filename",
    )
    manifest_path = _artifact_child_path(
        output_path,
        manifest_filename,
        field="manifest_filename",
    )
    registry_summary = write_consumer_contract_registry(
        registry_path,
        consumers=consumers,
    )
    manifest = _consumer_contract_registry_manifest(
        registry_summary,
        registry_path=registry_path,
        root=output_path,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _consumer_contract_manifest_summary(
        manifest_path=manifest_path,
        registry_path=registry_path,
        registry_summary=registry_summary,
        manifest=manifest,
    )


def validate_consumer_contract_registry_file(
    path: str | PathLike[str],
    *,
    require_all_known_consumers: bool = False,
) -> dict[str, Any]:
    """Validate a consumer contract registry artifact and return audit metadata."""

    registry_path = Path(path)
    with registry_path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    validate_consumer_contract_registry(
        payload,
        require_all_known_consumers=require_all_known_consumers,
    )
    contracts = payload["contracts"]
    consumers = [
        str(contract["consumer"])
        for contract in contracts
    ]
    missing_known_consumers = sorted(
        set(CONSUMER_REQUIRED_INDICATOR_FIELDS) - set(consumers)
    )
    canonical_payload_sha256 = _canonical_registry_payload_sha256(payload)
    local_payload_sha256 = _local_registry_payload_sha256(consumers)
    return {
        "path": str(registry_path),
        "schema_version": payload["schema_version"],
        "canonical_input": payload["canonical_input"],
        "consumer_count": len(contracts),
        "consumers": consumers,
        "known_consumer_count": len(CONSUMER_REQUIRED_INDICATOR_FIELDS),
        "missing_known_consumers": missing_known_consumers,
        "all_known_consumers_present": not missing_known_consumers,
        "canonical_registry_payload_sha256": canonical_payload_sha256,
        "local_registry_payload_sha256": local_payload_sha256,
        "local_contract_registry_verified": (
            canonical_payload_sha256 == local_payload_sha256
        ),
        "sha256": _sha256_file(registry_path),
        "size_bytes": registry_path.stat().st_size,
    }


def validate_consumer_contract_registry_manifest(
    path: str | PathLike[str],
    *,
    require_all_known_consumers: bool = False,
) -> dict[str, Any]:
    """Validate a consumer contract registry manifest and its linked registry."""

    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as file_obj:
        manifest = json.load(file_obj)
    _validate_consumer_contract_registry_manifest_shape(manifest)
    registry_path = _resolve_manifest_registry_path(
        manifest_path,
        str(manifest["registry_path"]),
    )
    registry_summary = validate_consumer_contract_registry_file(
        registry_path,
        require_all_known_consumers=require_all_known_consumers,
    )
    _validate_consumer_contract_registry_manifest_consistency(
        manifest,
        registry_summary=registry_summary,
    )
    return _consumer_contract_manifest_summary(
        manifest_path=manifest_path,
        registry_path=registry_path,
        registry_summary=registry_summary,
        manifest=manifest,
    )


def validate_consumer_contract_registry(
    payload: Mapping[str, Any],
    *,
    require_all_known_consumers: bool = False,
) -> None:
    """Validate a JSON-safe consumer contract registry payload."""

    if not isinstance(payload, Mapping):
        raise SignalConsumerContractError("consumer contract registry must be a mapping")
    _validate_no_sensitive_fields(payload)
    if payload.get("schema_version") != MARKET_SIGNAL_CONSUMER_CONTRACTS_SCHEMA_VERSION:
        raise SignalConsumerContractError(
            "unsupported consumer contract registry schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("canonical_input") != CANONICAL_INPUT_DERIVED_INDICATORS:
        raise SignalConsumerContractError(
            "consumer contract registry canonical_input mismatch: "
            f"{payload.get('canonical_input')!r}"
        )
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise SignalConsumerContractError(
            "consumer contract registry contracts must be a non-empty list"
        )
    seen_consumers: set[str] = set()
    for contract in contracts:
        _validate_consumer_contract_record(contract, seen_consumers=seen_consumers)
    if require_all_known_consumers:
        missing = sorted(set(CONSUMER_REQUIRED_INDICATOR_FIELDS) - seen_consumers)
        if missing:
            raise SignalConsumerContractError(
                "consumer contract registry missing known consumers: "
                + ", ".join(missing)
            )


def _contract_record(
    consumer: str,
    required_fields_by_symbol: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    return {
        "consumer": str(consumer),
        "canonical_input": CANONICAL_INPUT_DERIVED_INDICATORS,
        "required_indicator_fields_by_symbol": {
            str(symbol): [
                str(field)
                for field in fields
            ]
            for symbol, fields in sorted(required_fields_by_symbol.items())
        },
    }


def _consumer_contract_registry_manifest(
    registry_summary: Mapping[str, Any],
    *,
    registry_path: Path,
    root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SIGNAL_CONSUMER_CONTRACT_MANIFEST_SCHEMA_VERSION,
        "artifact_type": "market_signal_consumer_contract_registry",
        "registry_path": registry_path.relative_to(root).as_posix(),
        "registry_sha256": registry_summary["sha256"],
        "registry_size_bytes": registry_summary["size_bytes"],
        "registry_schema_version": registry_summary["schema_version"],
        "canonical_input": registry_summary["canonical_input"],
        "consumer_count": registry_summary["consumer_count"],
        "consumers": list(registry_summary.get("consumers", ())),
        "known_consumer_count": registry_summary["known_consumer_count"],
        "missing_known_consumers": registry_summary["missing_known_consumers"],
        "all_known_consumers_present": registry_summary["all_known_consumers_present"],
    }


def _consumer_contract_manifest_summary(
    *,
    manifest_path: Path,
    registry_path: Path,
    registry_summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "manifest_path": str(manifest_path),
        "manifest_schema_version": manifest["schema_version"],
        "manifest_sha256": _sha256_file(manifest_path),
        "manifest_size_bytes": manifest_path.stat().st_size,
        "artifact_type": manifest["artifact_type"],
        "registry_path": str(registry_path),
        "registry_sha256": registry_summary["sha256"],
        "registry_size_bytes": registry_summary["size_bytes"],
        "registry_schema_version": registry_summary["schema_version"],
        "canonical_input": registry_summary["canonical_input"],
        "consumer_count": registry_summary["consumer_count"],
        "consumers": list(registry_summary.get("consumers", ())),
        "known_consumer_count": registry_summary["known_consumer_count"],
        "missing_known_consumers": registry_summary["missing_known_consumers"],
        "all_known_consumers_present": registry_summary["all_known_consumers_present"],
        "canonical_registry_payload_sha256": registry_summary[
            "canonical_registry_payload_sha256"
        ],
        "local_registry_payload_sha256": registry_summary[
            "local_registry_payload_sha256"
        ],
        "local_contract_registry_verified": registry_summary[
            "local_contract_registry_verified"
        ],
    }


def _artifact_child_path(root: Path, value: str, *, field: str) -> Path:
    raw_path = Path(str(value).strip())
    if not str(value).strip():
        raise SignalConsumerContractError(f"{field} must not be empty")
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise SignalConsumerContractError(f"{field} must stay inside output_dir")
    return root / raw_path


def _validate_consumer_contract_registry_manifest_shape(
    manifest: object,
) -> None:
    if not isinstance(manifest, Mapping):
        raise SignalConsumerContractError("consumer contract manifest must be a mapping")
    _validate_no_sensitive_fields(manifest, path="manifest")
    if (
        manifest.get("schema_version")
        != MARKET_SIGNAL_CONSUMER_CONTRACT_MANIFEST_SCHEMA_VERSION
    ):
        raise SignalConsumerContractError(
            "unsupported consumer contract manifest schema_version: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("artifact_type") != "market_signal_consumer_contract_registry":
        raise SignalConsumerContractError(
            "consumer contract manifest artifact_type mismatch: "
            f"{manifest.get('artifact_type')!r}"
        )
    for field in (
        "registry_path",
        "registry_sha256",
        "registry_size_bytes",
        "registry_schema_version",
        "canonical_input",
        "consumer_count",
        "known_consumer_count",
        "missing_known_consumers",
        "all_known_consumers_present",
    ):
        if field not in manifest:
            raise SignalConsumerContractError(
                f"consumer contract manifest missing field: {field}"
            )
    if not isinstance(manifest["missing_known_consumers"], list):
        raise SignalConsumerContractError(
            "consumer contract manifest missing_known_consumers must be a list"
        )
    if "consumers" in manifest and not isinstance(manifest["consumers"], list):
        raise SignalConsumerContractError(
            "consumer contract manifest consumers must be a list"
        )
    if not isinstance(manifest["all_known_consumers_present"], bool):
        raise SignalConsumerContractError(
            "consumer contract manifest all_known_consumers_present must be a bool"
        )


def _resolve_manifest_registry_path(manifest_path: Path, value: str) -> Path:
    raw_path = Path(value.strip())
    if not value.strip():
        raise SignalConsumerContractError(
            "consumer contract manifest registry_path must not be empty"
        )
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise SignalConsumerContractError(
            "consumer contract manifest registry_path must stay inside manifest directory"
        )
    registry_path = (manifest_path.parent / raw_path).resolve()
    if not registry_path.exists():
        raise SignalConsumerContractError(
            "consumer contract manifest registry_path does not exist: "
            f"{value}"
        )
    return registry_path


def _validate_consumer_contract_registry_manifest_consistency(
    manifest: Mapping[str, Any],
    *,
    registry_summary: Mapping[str, Any],
) -> None:
    expected_values = {
        "registry_sha256": registry_summary["sha256"],
        "registry_size_bytes": registry_summary["size_bytes"],
        "registry_schema_version": registry_summary["schema_version"],
        "canonical_input": registry_summary["canonical_input"],
        "consumer_count": registry_summary["consumer_count"],
        "known_consumer_count": registry_summary["known_consumer_count"],
        "missing_known_consumers": registry_summary["missing_known_consumers"],
        "all_known_consumers_present": registry_summary["all_known_consumers_present"],
    }
    if "consumers" in manifest:
        expected_values["consumers"] = list(registry_summary.get("consumers", ()))
    for field, expected in expected_values.items():
        if manifest[field] != expected:
            raise SignalConsumerContractError(
                f"consumer contract manifest {field} mismatch: "
                f"{manifest[field]!r} != {expected!r}"
            )


def _validate_consumer_contract_record(
    contract: object,
    *,
    seen_consumers: set[str],
) -> None:
    if not isinstance(contract, Mapping):
        raise SignalConsumerContractError("consumer contract entries must be mappings")
    consumer = str(contract.get("consumer", "")).strip()
    if not consumer:
        raise SignalConsumerContractError("consumer contract missing consumer")
    if consumer in seen_consumers:
        raise SignalConsumerContractError(f"duplicate consumer contract: {consumer}")
    seen_consumers.add(consumer)
    if contract.get("canonical_input") != CANONICAL_INPUT_DERIVED_INDICATORS:
        raise SignalConsumerContractError(
            f"consumer contract canonical_input mismatch for {consumer}"
        )
    fields_by_symbol = contract.get("required_indicator_fields_by_symbol")
    if not isinstance(fields_by_symbol, Mapping) or not fields_by_symbol:
        raise SignalConsumerContractError(
            f"consumer contract {consumer} missing required indicator fields"
        )
    expected = required_indicator_fields_for_consumer(consumer)
    normalized_fields: dict[str, tuple[str, ...]] = {}
    for symbol, fields in fields_by_symbol.items():
        normalized_symbol = str(symbol).strip()
        if not normalized_symbol:
            raise SignalConsumerContractError(
                f"consumer contract {consumer} has empty symbol"
            )
        if not isinstance(fields, list) or not fields:
            raise SignalConsumerContractError(
                f"consumer contract {consumer} fields for {normalized_symbol} must be a non-empty list"
            )
        normalized = tuple(str(field).strip() for field in fields)
        if any(not field for field in normalized):
            raise SignalConsumerContractError(
                f"consumer contract {consumer} fields for {normalized_symbol} include empty values"
            )
        if len(set(normalized)) != len(normalized):
            raise SignalConsumerContractError(
                f"consumer contract {consumer} fields for {normalized_symbol} include duplicates"
            )
        normalized_fields[normalized_symbol] = normalized
    if normalized_fields != expected:
        raise SignalConsumerContractError(
            f"consumer contract {consumer} required fields drift from registry"
        )


def _canonical_registry_payload_sha256(payload: Mapping[str, Any]) -> str:
    normalized = {
        "schema_version": MARKET_SIGNAL_CONSUMER_CONTRACTS_SCHEMA_VERSION,
        "canonical_input": CANONICAL_INPUT_DERIVED_INDICATORS,
        "contracts": sorted(
            (
                {
                    "consumer": str(contract["consumer"]),
                    "canonical_input": CANONICAL_INPUT_DERIVED_INDICATORS,
                    "required_indicator_fields_by_symbol": {
                        str(symbol): [
                            str(field)
                            for field in fields
                        ]
                        for symbol, fields in sorted(
                            contract["required_indicator_fields_by_symbol"].items()
                        )
                    },
                }
                for contract in payload["contracts"]
            ),
            key=lambda contract: str(contract["consumer"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(
            normalized,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _local_registry_payload_sha256(consumers: Iterable[str]) -> str:
    return _canonical_registry_payload_sha256(
        consumer_contract_registry_payload(consumers=tuple(sorted(consumers)))
    )


def _validate_no_sensitive_fields(value: object, *, path: str = "registry") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_SENSITIVE_KEY_FRAGMENTS):
                raise SignalConsumerContractError(
                    f"consumer contract registry contains forbidden sensitive key at {path}.{key}"
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
