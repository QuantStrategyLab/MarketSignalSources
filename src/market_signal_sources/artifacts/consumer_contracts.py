from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

from .signal_bundle import CANONICAL_INPUT_DERIVED_INDICATORS


MARKET_SIGNAL_CONSUMER_CONTRACTS_SCHEMA_VERSION = "market_signal_consumer_contracts.v1"

CONSUMER_REQUIRED_INDICATOR_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "us_equity:ibit_smart_dca": {
        "BTC-USD": ("ahr999", "mayer_multiple"),
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
    return {
        "path": str(output_path),
        "schema_version": payload["schema_version"],
        "canonical_input": payload["canonical_input"],
        "consumer_count": len(contracts),
        "known_consumer_count": len(CONSUMER_REQUIRED_INDICATOR_FIELDS),
        "missing_known_consumers": missing_known_consumers,
        "all_known_consumers_present": not missing_known_consumers,
        "sha256": _sha256_file(output_path),
        "size_bytes": output_path.stat().st_size,
    }


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
    return {
        "path": str(registry_path),
        "schema_version": payload["schema_version"],
        "canonical_input": payload["canonical_input"],
        "consumer_count": len(contracts),
        "consumers": consumers,
        "known_consumer_count": len(CONSUMER_REQUIRED_INDICATOR_FIELDS),
        "missing_known_consumers": missing_known_consumers,
        "all_known_consumers_present": not missing_known_consumers,
        "sha256": _sha256_file(registry_path),
        "size_bytes": registry_path.stat().st_size,
    }


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
