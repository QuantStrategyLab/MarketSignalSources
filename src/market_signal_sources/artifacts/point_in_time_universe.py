"""Canonical point-in-time universe snapshots for historical research inputs.

The artifact binds a constituent set to its source content digest and the time
at which that set became available.  It is deliberately a local pure contract:
it does not fetch a provider, select securities, write storage, or enable a
strategy/runtime lane.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

POINT_IN_TIME_UNIVERSE_SCHEMA = "qsl.us-equity-point-in-time-universe.v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "universe_id",
        "effective_date",
        "available_at",
        "source",
        "constituents",
        "snapshot_sha256",
    }
)
_SOURCE_FIELDS = frozenset({"source_id", "raw_artifact_sha256", "license_scope"})


class PointInTimeUniverseError(ValueError):
    """Raised when a universe snapshot cannot prove no-look-ahead eligibility."""


def _fail(message: str) -> None:
    raise PointInTimeUniverseError(message)


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
        raise PointInTimeUniverseError(f"invalid {label}") from exc


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        _fail(f"invalid {label}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise PointInTimeUniverseError(f"invalid {label}") from exc


def _constituents(value: object) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        _fail("invalid constituents")
    items = tuple(value)
    if not items:
        _fail("empty constituents")
    normalized: list[str] = []
    for symbol in items:
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            _fail("invalid constituent symbol")
        normalized.append(symbol)
    if len(set(normalized)) != len(normalized):
        _fail("duplicate constituent symbol")
    return tuple(sorted(normalized))


def _source(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_FIELDS:
        _fail("invalid universe source")
    license_scope = value["license_scope"]
    if not isinstance(license_scope, str) or not license_scope or license_scope != license_scope.strip():
        _fail("invalid universe license scope")
    return {
        "source_id": _identifier(value["source_id"], "universe source id"),
        "raw_artifact_sha256": _digest(value["raw_artifact_sha256"], "universe raw artifact digest"),
        "license_scope": license_scope,
    }


def _canonical_json(value: Mapping[str, Any], *, without_digest: bool) -> bytes:
    material = dict(value)
    if without_digest:
        material.pop("snapshot_sha256", None)
    try:
        return json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PointInTimeUniverseError("invalid universe snapshot") from exc


def calculate_point_in_time_universe_sha256(value: Mapping[str, Any]) -> str:
    """Return the self-digest for one exact point-in-time universe snapshot."""
    return hashlib.sha256(_canonical_json(value, without_digest=True)).hexdigest()


def build_point_in_time_universe_snapshot(
    *,
    universe_id: object,
    effective_date: object,
    available_at: object,
    source_id: object,
    raw_artifact_sha256: object,
    license_scope: object,
    constituents: object,
) -> dict[str, object]:
    """Build a canonical local snapshot without making any provider request."""
    result: dict[str, object] = {
        "schema_version": POINT_IN_TIME_UNIVERSE_SCHEMA,
        "universe_id": _identifier(universe_id, "universe id"),
        "effective_date": _date(effective_date, "effective date"),
        "available_at": _timestamp(available_at, "available timestamp").strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "source": _source(
            {
                "source_id": source_id,
                "raw_artifact_sha256": raw_artifact_sha256,
                "license_scope": license_scope,
            }
        ),
        "constituents": list(_constituents(constituents)),
        "snapshot_sha256": "",
    }
    result["snapshot_sha256"] = calculate_point_in_time_universe_sha256(result)
    return validate_point_in_time_universe_snapshot(result)


def validate_point_in_time_universe_snapshot(value: object) -> dict[str, object]:
    """Validate one exact artifact and its constituent/source binding."""
    if not isinstance(value, Mapping) or set(value) != _ROOT_FIELDS:
        _fail("invalid universe snapshot")
    if value["schema_version"] != POINT_IN_TIME_UNIVERSE_SCHEMA:
        _fail("invalid universe snapshot schema")
    normalized: dict[str, object] = {
        "schema_version": POINT_IN_TIME_UNIVERSE_SCHEMA,
        "universe_id": _identifier(value["universe_id"], "universe id"),
        "effective_date": _date(value["effective_date"], "effective date"),
        "available_at": _timestamp(value["available_at"], "available timestamp").strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "source": _source(value["source"]),
        "constituents": list(_constituents(value["constituents"])),
        "snapshot_sha256": _digest(value["snapshot_sha256"], "universe snapshot digest"),
    }
    if normalized["snapshot_sha256"] != calculate_point_in_time_universe_sha256(normalized):
        _fail("universe snapshot digest mismatch")
    return normalized


def validate_universe_snapshot_for_decision(
    value: object, *, decision_at: object
) -> dict[str, object]:
    """Require that a snapshot was available no later than the decision time."""
    snapshot = validate_point_in_time_universe_snapshot(value)
    available_at = _timestamp(snapshot["available_at"], "available timestamp")
    decision = _timestamp(decision_at, "decision timestamp")
    if available_at > decision:
        _fail("universe snapshot was unavailable at decision time")
    return snapshot


__all__ = [
    "POINT_IN_TIME_UNIVERSE_SCHEMA",
    "PointInTimeUniverseError",
    "build_point_in_time_universe_snapshot",
    "calculate_point_in_time_universe_sha256",
    "validate_point_in_time_universe_snapshot",
    "validate_universe_snapshot_for_decision",
]
