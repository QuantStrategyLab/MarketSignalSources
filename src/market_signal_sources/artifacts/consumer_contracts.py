from __future__ import annotations

from collections.abc import Iterable, Mapping
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
