"""Minimal immutable P1 metadata binding for historical US-equity combo research.

The binding composes already-validated point-in-time constituent snapshots and
one historical price-panel record.  It is intentionally pure: no vendor call,
raw-data read, filesystem write, candidate registration, replay, or runtime
permission is performed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from .historical_price_panel import (
    HistoricalPricePanelError,
    validate_historical_price_panel,
)
from .point_in_time_universe import (
    PointInTimeUniverseError,
    validate_universe_snapshot_for_decision,
)

HISTORICAL_COMBO_P1_INPUT_SCHEMA = "qsl.us-equity-historical-combo-p1-input.v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "research_only",
        "candidate",
        "replay_window",
        "price_panel",
        "rebalances",
        "cost_model",
        "input_sha256",
    }
)
_CANDIDATE_FIELDS = frozenset({"candidate_id", "strategy_revision", "config_sha256"})
_WINDOW_FIELDS = frozenset({"start", "end"})
_REBALANCE_FIELDS = frozenset({"decision_at", "universe_snapshot"})
_COST_FIELDS = frozenset(
    {"base_turnover_cost_bps", "stress_turnover_cost_bps", "execution_timing"}
)
_EXECUTION_TIMING = "next_complete_trading_session_after_signal_effective_date"


class HistoricalComboP1InputError(ValueError):
    """Raised when a historical combo input would be ambiguous or look ahead."""


def _fail(message: str) -> None:
    raise HistoricalComboP1InputError(message)


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _fail(f"invalid {label}")
    return value


def _revision(value: object) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        _fail("invalid candidate strategy revision")
    return value


def _date(value: object, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"invalid {label}")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HistoricalComboP1InputError(f"invalid {label}") from exc


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        _fail(f"invalid {label}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise HistoricalComboP1InputError(f"invalid {label}") from exc


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"invalid {label}")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        _fail(f"invalid {label}")
    return numeric


def _candidate(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _CANDIDATE_FIELDS:
        _fail("invalid combo candidate")
    return {
        "candidate_id": _identity(value["candidate_id"], "candidate id"),
        "strategy_revision": _revision(value["strategy_revision"]),
        "config_sha256": _digest(value["config_sha256"], "candidate config digest"),
    }


def _window(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _WINDOW_FIELDS:
        _fail("invalid replay window")
    start = _date(value["start"], "replay window start")
    end = _date(value["end"], "replay window end")
    if start > end:
        _fail("replay window start is after end")
    return {"start": start, "end": end}


def _cost_model(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _COST_FIELDS:
        _fail("invalid combo cost model")
    base = _finite_nonnegative(value["base_turnover_cost_bps"], "base turnover cost")
    if base <= 0.0:
        _fail("base turnover cost must be positive")
    stress = value["stress_turnover_cost_bps"]
    if not isinstance(stress, Sequence) or isinstance(stress, (str, bytes)) or not stress:
        _fail("invalid stress turnover costs")
    normalized_stress = tuple(
        _finite_nonnegative(item, "stress turnover cost") for item in stress
    )
    if tuple(sorted(normalized_stress)) != normalized_stress or normalized_stress[0] < base:
        _fail("invalid stress turnover costs")
    if value["execution_timing"] != _EXECUTION_TIMING:
        _fail("invalid combo execution timing")
    return {
        "base_turnover_cost_bps": base,
        "stress_turnover_cost_bps": list(normalized_stress),
        "execution_timing": _EXECUTION_TIMING,
    }


def _rebalances(value: object, *, window: Mapping[str, str]) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        _fail("invalid combo rebalances")
    result: list[dict[str, object]] = []
    previous_decision: datetime | None = None
    for raw_entry in value:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != _REBALANCE_FIELDS:
            _fail("invalid combo rebalance")
        decision = _timestamp(raw_entry["decision_at"], "rebalance decision timestamp")
        try:
            snapshot = validate_universe_snapshot_for_decision(
                raw_entry["universe_snapshot"],
                decision_at=decision.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        except PointInTimeUniverseError as exc:
            raise HistoricalComboP1InputError("invalid rebalance universe snapshot") from exc
        effective_date = str(snapshot["effective_date"])
        decision_date = decision.date().isoformat()
        if (
            effective_date < window["start"]
            or effective_date > window["end"]
            or effective_date > decision_date
        ):
            _fail("rebalance universe snapshot is outside replay window")
        if previous_decision is not None and decision <= previous_decision:
            _fail("rebalance decisions must be strictly increasing")
        previous_decision = decision
        result.append(
            {
                "decision_at": decision.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "universe_snapshot": snapshot,
            }
        )
    return result


def _validate_cross_input_coverage(
    *,
    price_panel: Mapping[str, object],
    window: Mapping[str, str],
    rebalances: Sequence[Mapping[str, object]],
) -> None:
    if (
        str(price_panel["observation_start"]) > window["start"]
        or str(price_panel["observation_end"]) < window["end"]
    ):
        _fail("price panel does not cover replay window")
    panel_symbols = set(price_panel["symbols"])
    required_symbols = {
        symbol
        for rebalance in rebalances
        for symbol in rebalance["universe_snapshot"]["constituents"]  # type: ignore[index]
    }
    if not required_symbols.issubset(panel_symbols):
        _fail("price panel does not cover rebalance universe")


def _canonical_json(value: Mapping[str, Any], *, without_digest: bool) -> bytes:
    material = dict(value)
    if without_digest:
        material.pop("input_sha256", None)
    try:
        return json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HistoricalComboP1InputError("invalid combo P1 input") from exc


def calculate_historical_combo_p1_input_sha256(value: Mapping[str, Any]) -> str:
    """Return the self-digest for one exact combo P1 metadata binding."""
    return hashlib.sha256(_canonical_json(value, without_digest=True)).hexdigest()


def build_historical_combo_p1_input(
    *,
    candidate_id: object,
    strategy_revision: object,
    config_sha256: object,
    replay_start: object,
    replay_end: object,
    price_panel: object,
    rebalances: object,
    cost_model: object,
) -> dict[str, object]:
    """Build one replayable, research-only combo P1 input binding.

    The passed objects are already-local metadata/artifacts.  This builder does
    not infer a candidate, fetch missing prices, fill a date, or promote a
    result into P2/P3/P4/P5/P6.
    """
    window = _window({"start": replay_start, "end": replay_end})
    try:
        panel = validate_historical_price_panel(price_panel)
    except HistoricalPricePanelError as exc:
        raise HistoricalComboP1InputError("invalid combo price panel") from exc
    normalized_rebalances = _rebalances(rebalances, window=window)
    _validate_cross_input_coverage(
        price_panel=panel,
        window=window,
        rebalances=normalized_rebalances,
    )
    result: dict[str, object] = {
        "schema_version": HISTORICAL_COMBO_P1_INPUT_SCHEMA,
        "research_only": True,
        "candidate": _candidate(
            {
                "candidate_id": candidate_id,
                "strategy_revision": strategy_revision,
                "config_sha256": config_sha256,
            }
        ),
        "replay_window": window,
        "price_panel": panel,
        "rebalances": normalized_rebalances,
        "cost_model": _cost_model(cost_model),
        "input_sha256": "",
    }
    result["input_sha256"] = calculate_historical_combo_p1_input_sha256(result)
    return validate_historical_combo_p1_input(result)


def validate_historical_combo_p1_input(value: object) -> dict[str, object]:
    """Validate an exact combo P1 metadata binding without opening raw prices."""
    if not isinstance(value, Mapping) or set(value) != _ROOT_FIELDS:
        _fail("invalid combo P1 input")
    if value["schema_version"] != HISTORICAL_COMBO_P1_INPUT_SCHEMA:
        _fail("invalid combo P1 input schema")
    if value["research_only"] is not True:
        _fail("combo P1 input must be research only")
    candidate = _candidate(value["candidate"])
    window = _window(value["replay_window"])
    try:
        panel = validate_historical_price_panel(value["price_panel"])
    except HistoricalPricePanelError as exc:
        raise HistoricalComboP1InputError("invalid combo price panel") from exc
    rebalances = _rebalances(value["rebalances"], window=window)
    _validate_cross_input_coverage(price_panel=panel, window=window, rebalances=rebalances)
    normalized: dict[str, object] = {
        "schema_version": HISTORICAL_COMBO_P1_INPUT_SCHEMA,
        "research_only": True,
        "candidate": candidate,
        "replay_window": window,
        "price_panel": panel,
        "rebalances": rebalances,
        "cost_model": _cost_model(value["cost_model"]),
        "input_sha256": _digest(value["input_sha256"], "combo P1 input digest"),
    }
    if normalized["input_sha256"] != calculate_historical_combo_p1_input_sha256(normalized):
        _fail("combo P1 input digest mismatch")
    return normalized


__all__ = [
    "HISTORICAL_COMBO_P1_INPUT_SCHEMA",
    "HistoricalComboP1InputError",
    "build_historical_combo_p1_input",
    "calculate_historical_combo_p1_input_sha256",
    "validate_historical_combo_p1_input",
]
