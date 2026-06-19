from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd


NASDAQ_SP500_CONTEXT_AVAILABILITY_SCHEMA_VERSION = (
    "us_equity_context_availability_report.v1"
)
NASDAQ_SP500_CONTEXT_ARTIFACT_TYPE = "us_equity_context_research_csv"
NASDAQ_SP500_CONTEXT_TRANSFORM = "us_equity.nasdaq_sp500.context.v1"
NASDAQ_SP500_CONTEXT_FIELDS: tuple[str, ...] = (
    "cape_percentile",
    "vix_percentile",
    "breadth_above_sma200_pct",
)


def build_nasdaq_sp500_context_frame(
    frame: pd.DataFrame,
    *,
    as_of: str | None = None,
    date_column: str = "date",
    cape_percentile_column: str = "cape_percentile",
    vix_percentile_column: str = "vix_percentile",
    breadth_column: str = "breadth_above_sma200_pct",
    provider_timestamp_column: str | None = "provider_timestamp",
    passthrough_columns: Iterable[str] = ("QQQ", "SPY"),
    min_history: int = 1,
) -> pd.DataFrame:
    """Normalize a US equity external context CSV for smart-DCA research."""

    if date_column not in frame.columns:
        raise ValueError(f"input CSV missing date column: {date_column}")
    required_columns = {
        "cape_percentile": cape_percentile_column,
        "vix_percentile": vix_percentile_column,
        "breadth_above_sma200_pct": breadth_column,
    }
    missing = [
        source_column
        for source_column in required_columns.values()
        if source_column not in frame.columns
    ]
    if missing:
        raise ValueError("input CSV missing context columns: " + ", ".join(missing))

    normalized = pd.DataFrame()
    normalized["date"] = pd.to_datetime(frame[date_column], errors="coerce")
    for output_column, source_column in required_columns.items():
        normalized[output_column] = pd.to_numeric(
            frame[source_column],
            errors="coerce",
        )
    for column in passthrough_columns:
        if column in frame.columns:
            normalized[str(column)] = pd.to_numeric(frame[column], errors="coerce")
    if provider_timestamp_column and provider_timestamp_column in frame.columns:
        normalized["provider_timestamp"] = frame[provider_timestamp_column].astype(str)
    else:
        normalized["provider_timestamp"] = normalized["date"].dt.strftime("%Y-%m-%dT00:00:00Z")

    normalized = normalized.dropna(subset=("date", *NASDAQ_SP500_CONTEXT_FIELDS))
    normalized["date"] = normalized["date"].dt.normalize()
    if as_of:
        cutoff = pd.Timestamp(as_of).normalize()
        normalized = normalized.loc[normalized["date"] <= cutoff]
    normalized = normalized.sort_values("date").drop_duplicates(
        subset=("date",),
        keep="last",
    )
    normalized = normalized.loc[
        normalized["cape_percentile"].between(0.0, 1.0)
        & normalized["vix_percentile"].between(0.0, 1.0)
        & normalized["breadth_above_sma200_pct"].between(0.0, 1.0)
    ]
    if len(normalized) < int(min_history):
        raise ValueError(
            "insufficient US equity context history: "
            f"{len(normalized)} rows < {int(min_history)}"
        )

    leading_columns = [
        "date",
        *[column for column in ("QQQ", "SPY") if column in normalized.columns],
        *NASDAQ_SP500_CONTEXT_FIELDS,
        "provider_timestamp",
    ]
    output = normalized.loc[:, leading_columns].copy()
    output["date"] = output["date"].dt.date.astype(str)
    return output.reset_index(drop=True)


def build_nasdaq_sp500_context_availability_report(
    path: str | PathLike[str],
    *,
    as_of: str | None = None,
    date_column: str = "date",
    cape_percentile_column: str = "cape_percentile",
    vix_percentile_column: str = "vix_percentile",
    breadth_column: str = "breadth_above_sma200_pct",
    provider_timestamp_column: str | None = "provider_timestamp",
    breadth_universe_snapshot_column: str | None = "breadth_universe_snapshot_id",
    breadth_universe_as_of_column: str | None = "breadth_universe_as_of",
    require_point_in_time_metadata: bool = False,
    min_history_rows: int = 1,
    max_allowed_gap_days: int = 7,
) -> dict[str, Any]:
    """Build a non-sensitive quality report for a US equity context CSV."""

    input_path = Path(path)
    raw = pd.read_csv(input_path)
    selected_columns = {
        "date": date_column,
        "cape_percentile": cape_percentile_column,
        "vix_percentile": vix_percentile_column,
        "breadth_above_sma200_pct": breadth_column,
    }
    missing_columns = tuple(
        column
        for column in selected_columns.values()
        if column not in raw.columns
    )
    input_record = {
        "path": str(input_path),
        "sha256": _sha256_file(input_path),
        "size_bytes": input_path.stat().st_size,
    }
    if missing_columns:
        return _availability_report_payload(
            input_record=input_record,
            selected_columns=selected_columns,
            metadata_columns=_metadata_columns(
                provider_timestamp_column=provider_timestamp_column,
                breadth_universe_snapshot_column=breadth_universe_snapshot_column,
                breadth_universe_as_of_column=breadth_universe_as_of_column,
            ),
            source_columns=tuple(str(column) for column in raw.columns),
            as_of=as_of,
            require_point_in_time_metadata=require_point_in_time_metadata,
            min_history_rows=min_history_rows,
            max_allowed_gap_days=max_allowed_gap_days,
            raw_row_count=len(raw),
            normalized_row_count=0,
            filtered_after_as_of_count=0,
            invalid_date_count=0,
            null_indicator_count_by_field={field: 0 for field in NASDAQ_SP500_CONTEXT_FIELDS},
            out_of_range_count_by_field={field: 0 for field in NASDAQ_SP500_CONTEXT_FIELDS},
            provider_timestamp_missing_column=bool(provider_timestamp_column),
            provider_timestamp_missing_count=0,
            provider_timestamp_after_as_of_count=0,
            breadth_universe_snapshot_missing_column=bool(
                breadth_universe_snapshot_column
            ),
            breadth_universe_snapshot_missing_count=0,
            breadth_universe_as_of_missing_column=bool(breadth_universe_as_of_column),
            breadth_universe_as_of_invalid_count=0,
            breadth_universe_as_of_after_observation_count=0,
            duplicate_date_count=0,
            first_date="",
            last_date="",
            max_gap_days=0,
            gap_count_above_threshold=0,
            failure_reasons=tuple(
                f"missing_required_column:{column}"
                for column in missing_columns
            ),
            warning_reasons=(),
        )

    dates = pd.to_datetime(raw[date_column], errors="coerce").dt.normalize()
    usable = pd.DataFrame({"date": dates})
    null_indicator_count_by_field: dict[str, int] = {}
    out_of_range_count_by_field: dict[str, int] = {}
    for field, source_column in (
        ("cape_percentile", cape_percentile_column),
        ("vix_percentile", vix_percentile_column),
        ("breadth_above_sma200_pct", breadth_column),
    ):
        values = pd.to_numeric(raw[source_column], errors="coerce")
        usable[field] = values
        null_indicator_count_by_field[field] = int(values.isna().sum())
        out_of_range_count_by_field[field] = int(
            (~values.between(0.0, 1.0)).fillna(False).sum()
        )

    invalid_date_count = int(usable["date"].isna().sum())
    usable = usable.dropna(subset=("date", *NASDAQ_SP500_CONTEXT_FIELDS))
    for field in NASDAQ_SP500_CONTEXT_FIELDS:
        usable = usable.loc[usable[field].between(0.0, 1.0)]

    metadata_audit = _point_in_time_metadata_audit(
        raw,
        dates=dates,
        as_of=as_of,
        provider_timestamp_column=provider_timestamp_column,
        breadth_universe_snapshot_column=breadth_universe_snapshot_column,
        breadth_universe_as_of_column=breadth_universe_as_of_column,
    )

    filtered_after_as_of_count = 0
    if as_of:
        cutoff = pd.Timestamp(as_of).normalize()
        filtered_after_as_of_count = int((usable["date"] > cutoff).sum())
        usable = usable.loc[usable["date"] <= cutoff]

    duplicate_date_count = int(usable.duplicated(subset=("date",)).sum())
    normalized = (
        usable.sort_values("date")
        .drop_duplicates(subset=("date",), keep="last")
        .reset_index(drop=True)
    )
    first_date = "" if normalized.empty else normalized.iloc[0]["date"].date().isoformat()
    last_date = "" if normalized.empty else normalized.iloc[-1]["date"].date().isoformat()
    max_gap_days = _max_gap_days(normalized["date"]) if len(normalized) > 1 else 0
    gap_count = (
        _gap_count_above_threshold(normalized["date"], max_allowed_gap_days)
        if len(normalized) > 1
        else 0
    )
    failure_reasons = []
    if len(normalized) < int(min_history_rows):
        failure_reasons.append("insufficient_history_rows")
    failure_reasons.extend(
        _point_in_time_metadata_failure_reasons(
            metadata_audit,
            require_point_in_time_metadata=require_point_in_time_metadata,
        )
    )
    warning_reasons = _availability_warning_reasons(
        invalid_date_count=invalid_date_count,
        null_indicator_count_by_field=null_indicator_count_by_field,
        out_of_range_count_by_field=out_of_range_count_by_field,
        duplicate_date_count=duplicate_date_count,
        filtered_after_as_of_count=filtered_after_as_of_count,
        gap_count_above_threshold=gap_count,
        metadata_audit=metadata_audit,
        require_point_in_time_metadata=require_point_in_time_metadata,
    )
    return _availability_report_payload(
        input_record=input_record,
        selected_columns=selected_columns,
        metadata_columns=_metadata_columns(
            provider_timestamp_column=provider_timestamp_column,
            breadth_universe_snapshot_column=breadth_universe_snapshot_column,
            breadth_universe_as_of_column=breadth_universe_as_of_column,
        ),
        source_columns=tuple(str(column) for column in raw.columns),
        as_of=as_of,
        require_point_in_time_metadata=require_point_in_time_metadata,
        min_history_rows=min_history_rows,
        max_allowed_gap_days=max_allowed_gap_days,
        raw_row_count=len(raw),
        normalized_row_count=len(normalized),
        filtered_after_as_of_count=filtered_after_as_of_count,
        invalid_date_count=invalid_date_count,
        null_indicator_count_by_field=null_indicator_count_by_field,
        out_of_range_count_by_field=out_of_range_count_by_field,
        provider_timestamp_missing_column=metadata_audit[
            "provider_timestamp_missing_column"
        ],
        provider_timestamp_missing_count=metadata_audit[
            "provider_timestamp_missing_count"
        ],
        provider_timestamp_after_as_of_count=metadata_audit[
            "provider_timestamp_after_as_of_count"
        ],
        breadth_universe_snapshot_missing_column=metadata_audit[
            "breadth_universe_snapshot_missing_column"
        ],
        breadth_universe_snapshot_missing_count=metadata_audit[
            "breadth_universe_snapshot_missing_count"
        ],
        breadth_universe_as_of_missing_column=metadata_audit[
            "breadth_universe_as_of_missing_column"
        ],
        breadth_universe_as_of_invalid_count=metadata_audit[
            "breadth_universe_as_of_invalid_count"
        ],
        breadth_universe_as_of_after_observation_count=metadata_audit[
            "breadth_universe_as_of_after_observation_count"
        ],
        duplicate_date_count=duplicate_date_count,
        first_date=first_date,
        last_date=last_date,
        max_gap_days=max_gap_days,
        gap_count_above_threshold=gap_count,
        failure_reasons=tuple(failure_reasons),
        warning_reasons=warning_reasons,
    )


def write_nasdaq_sp500_context_availability_report(
    path: str | PathLike[str],
    input_csv: str | PathLike[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Write a US equity context availability report artifact."""

    report = build_nasdaq_sp500_context_availability_report(input_csv, **kwargs)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _availability_report_payload(
    *,
    input_record: dict[str, object],
    selected_columns: dict[str, object],
    metadata_columns: dict[str, object],
    source_columns: tuple[str, ...],
    as_of: str | None,
    require_point_in_time_metadata: bool,
    min_history_rows: int,
    max_allowed_gap_days: int,
    raw_row_count: int,
    normalized_row_count: int,
    filtered_after_as_of_count: int,
    invalid_date_count: int,
    null_indicator_count_by_field: dict[str, int],
    out_of_range_count_by_field: dict[str, int],
    provider_timestamp_missing_column: bool,
    provider_timestamp_missing_count: int,
    provider_timestamp_after_as_of_count: int,
    breadth_universe_snapshot_missing_column: bool,
    breadth_universe_snapshot_missing_count: int,
    breadth_universe_as_of_missing_column: bool,
    breadth_universe_as_of_invalid_count: int,
    breadth_universe_as_of_after_observation_count: int,
    duplicate_date_count: int,
    first_date: str,
    last_date: str,
    max_gap_days: int,
    gap_count_above_threshold: int,
    failure_reasons: tuple[str, ...],
    warning_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": NASDAQ_SP500_CONTEXT_AVAILABILITY_SCHEMA_VERSION,
        "artifact_type": "us_equity_context_availability_report",
        "quality_status": _quality_status(failure_reasons, warning_reasons),
        "failure_reasons": list(failure_reasons),
        "warning_reasons": list(warning_reasons),
        "input_csv": input_record,
        "selected_columns": selected_columns,
        "metadata_columns": metadata_columns,
        "source_columns": list(source_columns),
        "as_of": None if as_of is None else pd.Timestamp(as_of).normalize().date().isoformat(),
        "require_point_in_time_metadata": bool(require_point_in_time_metadata),
        "min_history_rows": int(min_history_rows),
        "max_allowed_gap_days": int(max_allowed_gap_days),
        "raw_row_count": int(raw_row_count),
        "normalized_row_count": int(normalized_row_count),
        "dropped_row_count": int(raw_row_count) - int(normalized_row_count),
        "filtered_after_as_of_count": int(filtered_after_as_of_count),
        "invalid_date_count": int(invalid_date_count),
        "null_indicator_count_by_field": dict(null_indicator_count_by_field),
        "out_of_range_count_by_field": dict(out_of_range_count_by_field),
        "provider_timestamp_missing_column": bool(provider_timestamp_missing_column),
        "provider_timestamp_missing_count": int(provider_timestamp_missing_count),
        "provider_timestamp_after_as_of_count": int(provider_timestamp_after_as_of_count),
        "breadth_universe_snapshot_missing_column": bool(
            breadth_universe_snapshot_missing_column
        ),
        "breadth_universe_snapshot_missing_count": int(
            breadth_universe_snapshot_missing_count
        ),
        "breadth_universe_as_of_missing_column": bool(
            breadth_universe_as_of_missing_column
        ),
        "breadth_universe_as_of_invalid_count": int(
            breadth_universe_as_of_invalid_count
        ),
        "breadth_universe_as_of_after_observation_count": int(
            breadth_universe_as_of_after_observation_count
        ),
        "duplicate_date_count": int(duplicate_date_count),
        "first_date": first_date,
        "last_date": last_date,
        "max_gap_days": int(max_gap_days),
        "gap_count_above_threshold": int(gap_count_above_threshold),
    }


def _availability_warning_reasons(
    *,
    invalid_date_count: int,
    null_indicator_count_by_field: dict[str, int],
    out_of_range_count_by_field: dict[str, int],
    duplicate_date_count: int,
    filtered_after_as_of_count: int,
    gap_count_above_threshold: int,
    metadata_audit: dict[str, Any],
    require_point_in_time_metadata: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if invalid_date_count:
        reasons.append("invalid_dates_dropped")
    if any(count > 0 for count in null_indicator_count_by_field.values()):
        reasons.append("null_indicators_dropped")
    if any(count > 0 for count in out_of_range_count_by_field.values()):
        reasons.append("out_of_range_indicators_dropped")
    if duplicate_date_count:
        reasons.append("duplicate_dates_collapsed")
    if filtered_after_as_of_count:
        reasons.append("rows_after_as_of_filtered")
    if gap_count_above_threshold:
        reasons.append("date_gaps_above_threshold")
    failure_reasons = set(
        _point_in_time_metadata_failure_reasons(
            metadata_audit,
            require_point_in_time_metadata=require_point_in_time_metadata,
        )
    )
    if (
        metadata_audit["provider_timestamp_missing_column"]
        and "missing_provider_timestamp_column" not in failure_reasons
    ):
        reasons.append("missing_provider_timestamp_column")
    if (
        metadata_audit["provider_timestamp_missing_count"]
        and "provider_timestamps_missing_or_invalid" not in failure_reasons
    ):
        reasons.append("provider_timestamps_missing_or_invalid")
    if (
        metadata_audit["provider_timestamp_after_as_of_count"]
        and "provider_timestamp_after_as_of" not in failure_reasons
    ):
        reasons.append("provider_timestamp_after_as_of")
    if (
        metadata_audit["breadth_universe_snapshot_missing_column"]
        and "missing_breadth_universe_snapshot_column" not in failure_reasons
    ):
        reasons.append("missing_breadth_universe_snapshot_column")
    if (
        metadata_audit["breadth_universe_snapshot_missing_count"]
        and "breadth_universe_snapshot_missing" not in failure_reasons
    ):
        reasons.append("breadth_universe_snapshot_missing")
    if (
        metadata_audit["breadth_universe_as_of_missing_column"]
        and "missing_breadth_universe_as_of_column" not in failure_reasons
    ):
        reasons.append("missing_breadth_universe_as_of_column")
    if (
        metadata_audit["breadth_universe_as_of_invalid_count"]
        and "breadth_universe_as_of_invalid" not in failure_reasons
    ):
        reasons.append("breadth_universe_as_of_invalid")
    if (
        metadata_audit["breadth_universe_as_of_after_observation_count"]
        and "breadth_universe_as_of_after_observation" not in failure_reasons
    ):
        reasons.append("breadth_universe_as_of_after_observation")
    return tuple(reasons)


def _point_in_time_metadata_failure_reasons(
    metadata_audit: dict[str, Any],
    *,
    require_point_in_time_metadata: bool,
) -> list[str]:
    reasons: list[str] = []
    if require_point_in_time_metadata and metadata_audit[
        "provider_timestamp_missing_column"
    ]:
        reasons.append("missing_provider_timestamp_column")
    if require_point_in_time_metadata and metadata_audit[
        "provider_timestamp_missing_count"
    ]:
        reasons.append("provider_timestamps_missing_or_invalid")
    if metadata_audit["provider_timestamp_after_as_of_count"]:
        reasons.append("provider_timestamp_after_as_of")
    if require_point_in_time_metadata and metadata_audit[
        "breadth_universe_snapshot_missing_column"
    ]:
        reasons.append("missing_breadth_universe_snapshot_column")
    if require_point_in_time_metadata and metadata_audit[
        "breadth_universe_snapshot_missing_count"
    ]:
        reasons.append("breadth_universe_snapshot_missing")
    if require_point_in_time_metadata and metadata_audit[
        "breadth_universe_as_of_missing_column"
    ]:
        reasons.append("missing_breadth_universe_as_of_column")
    if require_point_in_time_metadata and metadata_audit[
        "breadth_universe_as_of_invalid_count"
    ]:
        reasons.append("breadth_universe_as_of_invalid")
    if metadata_audit["breadth_universe_as_of_after_observation_count"]:
        reasons.append("breadth_universe_as_of_after_observation")
    return reasons


def _point_in_time_metadata_audit(
    frame: pd.DataFrame,
    *,
    dates: pd.Series,
    as_of: str | None,
    provider_timestamp_column: str | None,
    breadth_universe_snapshot_column: str | None,
    breadth_universe_as_of_column: str | None,
) -> dict[str, Any]:
    provider_missing_column = bool(
        provider_timestamp_column and provider_timestamp_column not in frame.columns
    )
    provider_missing_count = 0
    provider_after_as_of_count = 0
    if provider_timestamp_column and provider_timestamp_column in frame.columns:
        provider_timestamps = _timestamp_series(frame[provider_timestamp_column])
        provider_missing_count = int(provider_timestamps.isna().sum())
        if as_of:
            cutoff = pd.Timestamp(as_of).normalize()
            provider_after_as_of_count = int(
                (provider_timestamps.dt.normalize() > cutoff).fillna(False).sum()
            )

    snapshot_missing_column = bool(
        breadth_universe_snapshot_column
        and breadth_universe_snapshot_column not in frame.columns
    )
    snapshot_missing_count = 0
    if (
        breadth_universe_snapshot_column
        and breadth_universe_snapshot_column in frame.columns
    ):
        snapshots = frame[breadth_universe_snapshot_column].astype("string")
        snapshot_missing_count = int(snapshots.fillna("").str.strip().eq("").sum())

    universe_as_of_missing_column = bool(
        breadth_universe_as_of_column
        and breadth_universe_as_of_column not in frame.columns
    )
    universe_as_of_invalid_count = 0
    universe_as_of_after_observation_count = 0
    if breadth_universe_as_of_column and breadth_universe_as_of_column in frame.columns:
        universe_as_of = _timestamp_series(frame[breadth_universe_as_of_column])
        universe_as_of_invalid_count = int(universe_as_of.isna().sum())
        universe_as_of_after_observation_count = int(
            (universe_as_of.dt.normalize() > dates).fillna(False).sum()
        )

    return {
        "provider_timestamp_missing_column": provider_missing_column,
        "provider_timestamp_missing_count": provider_missing_count,
        "provider_timestamp_after_as_of_count": provider_after_as_of_count,
        "breadth_universe_snapshot_missing_column": snapshot_missing_column,
        "breadth_universe_snapshot_missing_count": snapshot_missing_count,
        "breadth_universe_as_of_missing_column": universe_as_of_missing_column,
        "breadth_universe_as_of_invalid_count": universe_as_of_invalid_count,
        "breadth_universe_as_of_after_observation_count": (
            universe_as_of_after_observation_count
        ),
    }


def _timestamp_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert(None)


def _metadata_columns(
    *,
    provider_timestamp_column: str | None,
    breadth_universe_snapshot_column: str | None,
    breadth_universe_as_of_column: str | None,
) -> dict[str, object]:
    return {
        "provider_timestamp": provider_timestamp_column or "",
        "breadth_universe_snapshot_id": breadth_universe_snapshot_column or "",
        "breadth_universe_as_of": breadth_universe_as_of_column or "",
    }


def _quality_status(
    failure_reasons: tuple[str, ...],
    warning_reasons: tuple[str, ...],
) -> str:
    if failure_reasons:
        return "fail"
    if warning_reasons:
        return "warn"
    return "pass"


def _max_gap_days(dates: pd.Series) -> int:
    normalized = pd.to_datetime(dates).dropna().sort_values()
    if len(normalized) < 2:
        return 0
    gaps = normalized.diff().dropna().dt.days
    return int(gaps.max()) if not gaps.empty else 0


def _gap_count_above_threshold(dates: pd.Series, threshold_days: int) -> int:
    normalized = pd.to_datetime(dates).dropna().sort_values()
    if len(normalized) < 2:
        return 0
    gaps = normalized.diff().dropna().dt.days
    return int((gaps > int(threshold_days)).sum())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
