from __future__ import annotations

import pytest

from market_signal_sources.artifacts.point_in_time_universe import (
    POINT_IN_TIME_UNIVERSE_SCHEMA,
    PointInTimeUniverseError,
    build_point_in_time_universe_snapshot,
    validate_point_in_time_universe_snapshot,
    validate_universe_snapshot_for_decision,
)


def _snapshot() -> dict[str, object]:
    return build_point_in_time_universe_snapshot(
        universe_id="russell_1000",
        effective_date="2025-06-30",
        available_at="2025-06-30T20:15:00Z",
        source_id="ishares.iwb.holdings_csv",
        raw_artifact_sha256="a" * 64,
        license_scope="private_research",
        constituents=("MSFT", "AAPL", "BRK.B"),
    )


def test_snapshot_is_canonical_and_binds_the_source_and_constituents() -> None:
    snapshot = _snapshot()

    assert snapshot["schema_version"] == POINT_IN_TIME_UNIVERSE_SCHEMA
    assert snapshot["constituents"] == ["AAPL", "BRK.B", "MSFT"]
    assert snapshot["source"] == {
        "source_id": "ishares.iwb.holdings_csv",
        "raw_artifact_sha256": "a" * 64,
        "license_scope": "private_research",
    }
    assert validate_point_in_time_universe_snapshot(snapshot) == snapshot


def test_decision_cannot_consume_a_universe_before_it_was_available() -> None:
    snapshot = _snapshot()

    assert validate_universe_snapshot_for_decision(
        snapshot, decision_at="2025-06-30T20:15:00Z"
    ) == snapshot
    with pytest.raises(PointInTimeUniverseError, match="unavailable at decision time"):
        validate_universe_snapshot_for_decision(snapshot, decision_at="2025-06-30T20:14:59Z")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"snapshot_sha256": "b" * 64}), "digest mismatch"),
        (lambda value: value.update({"constituents": ["AAPL", "AAPL"]}), "duplicate constituent"),
        (
            lambda value: value["source"].update({"raw_artifact_sha256": "bad"}),
            "invalid universe raw artifact digest",
        ),
    ],
)
def test_tampered_or_ambiguous_snapshots_fail_closed(mutate, message: str) -> None:
    snapshot = _snapshot()
    mutate(snapshot)

    with pytest.raises(PointInTimeUniverseError, match=message):
        validate_point_in_time_universe_snapshot(snapshot)


def test_builder_rejects_duplicate_or_invalid_constituents() -> None:
    with pytest.raises(PointInTimeUniverseError, match="duplicate constituent"):
        build_point_in_time_universe_snapshot(
            universe_id="russell_1000",
            effective_date="2025-06-30",
            available_at="2025-06-30T20:15:00Z",
            source_id="ishares.iwb.holdings_csv",
            raw_artifact_sha256="a" * 64,
            license_scope="private_research",
            constituents=("AAPL", "AAPL"),
        )
