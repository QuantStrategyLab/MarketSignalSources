from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd

from .signal_bundle import sha256_file


QUALITY_REPORT_SCHEMA_VERSION = "market_signal_quality_report.v1"


def build_ohlcv_quality_report(
    path: str | PathLike[str],
    *,
    date_column: str = "date",
    close_column: str = "close",
    high_column: str | None = "high",
    low_column: str | None = "low",
    volume_column: str | None = "volume",
    as_of: str | None = None,
    min_history_rows: int = 200,
    max_allowed_gap_days: int = 1,
) -> dict[str, Any]:
    """Build a JSON-safe quality report for a local OHLCV CSV input."""

    input_path = Path(path)
    raw = pd.read_csv(input_path)
    input_record = {
        "path": str(input_path),
        "sha256": sha256_file(input_path),
        "size_bytes": input_path.stat().st_size,
    }
    selected_columns = {
        "date": date_column,
        "close": close_column,
        "high": high_column,
        "low": low_column,
        "volume": volume_column,
    }
    missing_required_columns = tuple(
        column
        for column in (date_column, close_column)
        if column not in raw.columns
    )
    if missing_required_columns:
        return _quality_report_payload(
            input_record=input_record,
            selected_columns=selected_columns,
            source_columns=tuple(str(column) for column in raw.columns),
            as_of=as_of,
            min_history_rows=min_history_rows,
            max_allowed_gap_days=max_allowed_gap_days,
            raw_row_count=len(raw),
            normalized_row_count=0,
            filtered_after_as_of_count=0,
            invalid_date_count=0,
            null_close_count=0,
            non_positive_close_count=0,
            duplicate_date_count=0,
            first_date="",
            last_date="",
            max_gap_days=0,
            gap_count_above_threshold=0,
            failure_reasons=tuple(
                f"missing_required_column:{column}"
                for column in missing_required_columns
            ),
            warning_reasons=(),
        )

    dates = pd.to_datetime(raw[date_column], errors="coerce").dt.tz_localize(None).dt.normalize()
    closes = pd.to_numeric(raw[close_column], errors="coerce")
    usable = pd.DataFrame({"date": dates, "close": closes})
    invalid_date_count = int(usable["date"].isna().sum())
    null_close_count = int(usable["close"].isna().sum())
    non_positive_close_count = int((usable["close"] <= 0.0).fillna(False).sum())
    usable = usable.dropna(subset=["date", "close"])
    usable = usable.loc[usable["close"] > 0.0]

    filtered_after_as_of_count = 0
    normalized_as_of = None if as_of is None else pd.Timestamp(as_of).tz_localize(None).normalize()
    if normalized_as_of is not None:
        filtered_after_as_of_count = int((usable["date"] > normalized_as_of).sum())
        usable = usable.loc[usable["date"] <= normalized_as_of]

    duplicate_date_count = int(usable.duplicated(subset=["date"]).sum())
    normalized = (
        usable.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    first_date = "" if normalized.empty else normalized.iloc[0]["date"].date().isoformat()
    last_date = "" if normalized.empty else normalized.iloc[-1]["date"].date().isoformat()
    max_gap_days = _max_gap_days(normalized["date"]) if len(normalized) > 1 else 0
    gap_count_above_threshold = (
        _gap_count_above_threshold(normalized["date"], max_allowed_gap_days)
        if len(normalized) > 1
        else 0
    )
    failure_reasons = _quality_failure_reasons(
        normalized_row_count=len(normalized),
        min_history_rows=min_history_rows,
    )
    warning_reasons = _quality_warning_reasons(
        invalid_date_count=invalid_date_count,
        null_close_count=null_close_count,
        non_positive_close_count=non_positive_close_count,
        duplicate_date_count=duplicate_date_count,
        filtered_after_as_of_count=filtered_after_as_of_count,
        gap_count_above_threshold=gap_count_above_threshold,
    )
    return _quality_report_payload(
        input_record=input_record,
        selected_columns=selected_columns,
        source_columns=tuple(str(column) for column in raw.columns),
        as_of=as_of,
        min_history_rows=min_history_rows,
        max_allowed_gap_days=max_allowed_gap_days,
        raw_row_count=len(raw),
        normalized_row_count=len(normalized),
        filtered_after_as_of_count=filtered_after_as_of_count,
        invalid_date_count=invalid_date_count,
        null_close_count=null_close_count,
        non_positive_close_count=non_positive_close_count,
        duplicate_date_count=duplicate_date_count,
        first_date=first_date,
        last_date=last_date,
        max_gap_days=max_gap_days,
        gap_count_above_threshold=gap_count_above_threshold,
        failure_reasons=failure_reasons,
        warning_reasons=warning_reasons,
    )


def write_ohlcv_quality_report(
    path: str | PathLike[str],
    input_csv: str | PathLike[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Write a local OHLCV quality report artifact."""

    report = build_ohlcv_quality_report(input_csv, **kwargs)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _quality_report_payload(
    *,
    input_record: dict[str, Any],
    selected_columns: dict[str, str | None],
    source_columns: tuple[str, ...],
    as_of: str | None,
    min_history_rows: int,
    max_allowed_gap_days: int,
    raw_row_count: int,
    normalized_row_count: int,
    filtered_after_as_of_count: int,
    invalid_date_count: int,
    null_close_count: int,
    non_positive_close_count: int,
    duplicate_date_count: int,
    first_date: str,
    last_date: str,
    max_gap_days: int,
    gap_count_above_threshold: int,
    failure_reasons: tuple[str, ...],
    warning_reasons: tuple[str, ...],
) -> dict[str, Any]:
    quality_status = (
        "fail"
        if failure_reasons
        else "warn"
        if warning_reasons
        else "pass"
    )
    return {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "artifact_type": "local_ohlcv_quality_report",
        "quality_status": quality_status,
        "failure_reasons": failure_reasons,
        "warning_reasons": warning_reasons,
        "input_csv": input_record,
        "selected_columns": selected_columns,
        "source_columns": source_columns,
        "as_of": as_of,
        "min_history_rows": int(min_history_rows),
        "max_allowed_gap_days": int(max_allowed_gap_days),
        "raw_row_count": int(raw_row_count),
        "normalized_row_count": int(normalized_row_count),
        "filtered_after_as_of_count": int(filtered_after_as_of_count),
        "dropped_row_count": int(raw_row_count - normalized_row_count),
        "invalid_date_count": int(invalid_date_count),
        "null_close_count": int(null_close_count),
        "non_positive_close_count": int(non_positive_close_count),
        "duplicate_date_count": int(duplicate_date_count),
        "first_date": first_date,
        "last_date": last_date,
        "max_gap_days": int(max_gap_days),
        "gap_count_above_threshold": int(gap_count_above_threshold),
    }


def _quality_failure_reasons(
    *,
    normalized_row_count: int,
    min_history_rows: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if normalized_row_count <= 0:
        reasons.append("no_usable_rows")
    if normalized_row_count < min_history_rows:
        reasons.append("insufficient_history_rows")
    return tuple(reasons)


def _quality_warning_reasons(
    *,
    invalid_date_count: int,
    null_close_count: int,
    non_positive_close_count: int,
    duplicate_date_count: int,
    filtered_after_as_of_count: int,
    gap_count_above_threshold: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if invalid_date_count:
        reasons.append("invalid_dates_dropped")
    if null_close_count:
        reasons.append("null_closes_dropped")
    if non_positive_close_count:
        reasons.append("non_positive_closes_dropped")
    if duplicate_date_count:
        reasons.append("duplicate_dates_collapsed")
    if filtered_after_as_of_count:
        reasons.append("rows_after_as_of_filtered")
    if gap_count_above_threshold:
        reasons.append("date_gaps_above_threshold")
    return tuple(reasons)


def _max_gap_days(dates: pd.Series) -> int:
    gaps = dates.sort_values().diff().dropna().dt.days
    return int(gaps.max()) if not gaps.empty else 0


def _gap_count_above_threshold(dates: pd.Series, threshold: int) -> int:
    gaps = dates.sort_values().diff().dropna().dt.days
    return int((gaps > threshold).sum()) if not gaps.empty else 0
