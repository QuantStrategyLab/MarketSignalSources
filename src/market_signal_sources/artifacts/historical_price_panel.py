"""Canonical historical price-panel provenance for offline strategy research.

This is metadata only.  It binds one already-acquired price panel to its raw
and quality-report digests, declared adjustment bases, and observability
assumptions.  It never fetches a vendor, reads a price file, or enables a
runtime lane.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

HISTORICAL_PRICE_PANEL_SCHEMA = "qsl.us-equity-historical-price-panel.v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_POINT_IN_TIME_STATUSES = frozenset(
    {"historical_close_with_declared_lag", "point_in_time_vendor_snapshot"}
)
_PRICE_BASES = frozenset({"split_adjusted_close", "total_return_adjusted_close"})
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "panel_id",
        "observation_start",
        "observation_end",
        "source",
        "signal_price_basis",
        "return_price_basis",
        "calendar_id",
        "execution_lag_trading_sessions",
        "symbols",
        "snapshot_sha256",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "source_id",
        "raw_artifact_sha256",
        "quality_report_sha256",
        "license_scope",
        "point_in_time_status",
    }
)


class HistoricalPricePanelError(ValueError):
    """Raised when a price-panel artifact is unsuitable for historical replay."""


def _fail(message: str) -> None:
    raise HistoricalPricePanelError(message)


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _date(value: object, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"invalid {label}")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HistoricalPricePanelError(f"invalid {label}") from exc


def _symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        _fail("invalid panel symbols")
    symbols = tuple(value)
    if not symbols:
        _fail("empty panel symbols")
    normalized: list[str] = []
    for symbol in symbols:
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            _fail("invalid panel symbol")
        normalized.append(symbol)
    if len(set(normalized)) != len(normalized):
        _fail("duplicate panel symbol")
    return tuple(sorted(normalized))


def _source(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_FIELDS:
        _fail("invalid price-panel source")
    license_scope = value["license_scope"]
    status = value["point_in_time_status"]
    if not isinstance(license_scope, str) or not license_scope or license_scope != license_scope.strip():
        _fail("invalid price-panel license scope")
    if status not in _POINT_IN_TIME_STATUSES:
        _fail("invalid price-panel point-in-time status")
    return {
        "source_id": _identifier(value["source_id"], "price-panel source id"),
        "raw_artifact_sha256": _digest(
            value["raw_artifact_sha256"], "price-panel raw artifact digest"
        ),
        "quality_report_sha256": _digest(
            value["quality_report_sha256"], "price-panel quality report digest"
        ),
        "license_scope": license_scope,
        "point_in_time_status": status,
    }


def _price_basis(value: object, label: str) -> str:
    if value not in _PRICE_BASES:
        _fail(f"invalid {label}")
    return str(value)


def _execution_lag(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("invalid execution lag trading sessions")
    return value


def _canonical_json(value: Mapping[str, Any], *, without_digest: bool) -> bytes:
    material = dict(value)
    if without_digest:
        material.pop("snapshot_sha256", None)
    try:
        return json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HistoricalPricePanelError("invalid price-panel snapshot") from exc


def calculate_historical_price_panel_sha256(value: Mapping[str, Any]) -> str:
    """Return the self-digest for one exact historical price-panel artifact."""
    return hashlib.sha256(_canonical_json(value, without_digest=True)).hexdigest()


def build_historical_price_panel(
    *,
    panel_id: object,
    observation_start: object,
    observation_end: object,
    source_id: object,
    raw_artifact_sha256: object,
    quality_report_sha256: object,
    license_scope: object,
    point_in_time_status: object,
    signal_price_basis: object,
    return_price_basis: object,
    calendar_id: object,
    execution_lag_trading_sessions: object,
    symbols: object,
) -> dict[str, object]:
    """Build an immutable metadata binding for an already-acquired price panel."""
    start = _date(observation_start, "observation start")
    end = _date(observation_end, "observation end")
    if start > end:
        _fail("observation start is after observation end")
    result: dict[str, object] = {
        "schema_version": HISTORICAL_PRICE_PANEL_SCHEMA,
        "panel_id": _identifier(panel_id, "price-panel id"),
        "observation_start": start,
        "observation_end": end,
        "source": _source(
            {
                "source_id": source_id,
                "raw_artifact_sha256": raw_artifact_sha256,
                "quality_report_sha256": quality_report_sha256,
                "license_scope": license_scope,
                "point_in_time_status": point_in_time_status,
            }
        ),
        "signal_price_basis": _price_basis(signal_price_basis, "signal price basis"),
        "return_price_basis": _price_basis(return_price_basis, "return price basis"),
        "calendar_id": _identifier(calendar_id, "calendar id"),
        "execution_lag_trading_sessions": _execution_lag(execution_lag_trading_sessions),
        "symbols": list(_symbols(symbols)),
        "snapshot_sha256": "",
    }
    result["snapshot_sha256"] = calculate_historical_price_panel_sha256(result)
    return validate_historical_price_panel(result)


def validate_historical_price_panel(value: object) -> dict[str, object]:
    """Validate a price-panel binding without opening its raw price contents."""
    if not isinstance(value, Mapping) or set(value) != _ROOT_FIELDS:
        _fail("invalid price-panel snapshot")
    if value["schema_version"] != HISTORICAL_PRICE_PANEL_SCHEMA:
        _fail("invalid price-panel snapshot schema")
    start = _date(value["observation_start"], "observation start")
    end = _date(value["observation_end"], "observation end")
    if start > end:
        _fail("observation start is after observation end")
    normalized: dict[str, object] = {
        "schema_version": HISTORICAL_PRICE_PANEL_SCHEMA,
        "panel_id": _identifier(value["panel_id"], "price-panel id"),
        "observation_start": start,
        "observation_end": end,
        "source": _source(value["source"]),
        "signal_price_basis": _price_basis(value["signal_price_basis"], "signal price basis"),
        "return_price_basis": _price_basis(value["return_price_basis"], "return price basis"),
        "calendar_id": _identifier(value["calendar_id"], "calendar id"),
        "execution_lag_trading_sessions": _execution_lag(
            value["execution_lag_trading_sessions"]
        ),
        "symbols": list(_symbols(value["symbols"])),
        "snapshot_sha256": _digest(value["snapshot_sha256"], "price-panel snapshot digest"),
    }
    if normalized["snapshot_sha256"] != calculate_historical_price_panel_sha256(normalized):
        _fail("price-panel snapshot digest mismatch")
    return normalized


__all__ = [
    "HISTORICAL_PRICE_PANEL_SCHEMA",
    "HistoricalPricePanelError",
    "build_historical_price_panel",
    "calculate_historical_price_panel_sha256",
    "validate_historical_price_panel",
]
