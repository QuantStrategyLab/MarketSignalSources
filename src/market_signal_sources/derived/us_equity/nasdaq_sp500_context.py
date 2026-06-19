from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


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
