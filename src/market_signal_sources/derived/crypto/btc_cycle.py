from __future__ import annotations

import math
from typing import Any

import pandas as pd


BITCOIN_GENESIS_DATE = pd.Timestamp("2009-01-03")
BTC_RESEARCH_INDICATOR_FIELDS: tuple[str, ...] = (
    "ahr999_365d_percentile",
    "ahr999_30d_slope",
    "mayer_multiple_365d_percentile",
    "realized_volatility_30d",
    "momentum_90d",
)
IndicatorValue = float | str | None


def compute_btc_cycle_indicators(
    ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    min_history: int = 200,
) -> dict[str, IndicatorValue]:
    """Compute deterministic BTC cycle indicators from local daily OHLCV data."""

    frame = _normalize_ohlcv(ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        frame = frame.loc[frame["date"] <= cutoff]
    if len(frame) < int(min_history):
        raise ValueError(f"BTC cycle indicators require at least {int(min_history)} rows")

    trailing_history_rows = max(int(min_history), 252) + 365 - 1
    indicator_frame = _build_btc_cycle_indicator_frame_from_normalized(
        frame.tail(trailing_history_rows).reset_index(drop=True),
        min_history=int(min_history),
    )
    latest = indicator_frame.iloc[-1].to_dict()
    latest.pop("date", None)
    return {
        str(field): _json_safe_indicator_value(value)
        for field, value in latest.items()
    }


def build_btc_cycle_indicator_frame(
    ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    min_history: int = 200,
) -> pd.DataFrame:
    """Build a daily BTC cycle indicator frame for offline research exports."""

    frame = _normalize_ohlcv(ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        frame = frame.loc[frame["date"] <= cutoff].reset_index(drop=True)
    return _build_btc_cycle_indicator_frame_from_normalized(
        frame,
        min_history=int(min_history),
    )


def _build_btc_cycle_indicator_frame_from_normalized(
    frame: pd.DataFrame,
    *,
    min_history: int,
) -> pd.DataFrame:
    rows: list[dict[str, IndicatorValue]] = []
    for index in range(int(min_history) - 1, len(frame)):
        history = frame.iloc[: index + 1]
        date = pd.Timestamp(history.iloc[-1]["date"]).normalize().date().isoformat()
        rows.append(
            {
                "date": date,
                **_compute_btc_cycle_base_indicators(history),
            }
        )
    if not rows:
        raise ValueError(f"BTC cycle research export requires at least {int(min_history)} rows")
    return _with_research_cycle_fields(pd.DataFrame(rows))


def _compute_btc_cycle_base_indicators(
    frame: pd.DataFrame,
) -> dict[str, IndicatorValue]:
    latest_row = frame.iloc[-1]
    latest_date = pd.Timestamp(latest_row["date"]).normalize()
    close_series = frame["close"].astype(float)
    latest_close = float(latest_row["close"])
    sma200 = float(close_series.iloc[-200:].mean())
    gma200 = _geometric_mean(close_series.iloc[-200:])
    high_source = frame["high"].astype(float) if "high" in frame.columns else close_series
    high252 = float(high_source.iloc[-252:].max())
    estimate_price = _bitcoin_age_estimate_price(latest_date)
    mayer = float(latest_close / sma200) if sma200 > 0.0 else float("nan")
    ahr999 = (
        float((latest_close / gma200) * (latest_close / estimate_price))
        if gma200 > 0.0 and estimate_price > 0.0
        else float("nan")
    )
    ahr999_sma = (
        float((latest_close / sma200) * (latest_close / estimate_price))
        if sma200 > 0.0 and estimate_price > 0.0
        else float("nan")
    )

    return {
        "close": latest_close,
        "sma200": sma200,
        "gma200": gma200,
        "high252": high252,
        "drawdown_252d": 0.0 if high252 <= 0.0 else max(0.0, 1.0 - latest_close / high252),
        "sma200_gap": 0.0 if sma200 <= 0.0 else latest_close / sma200 - 1.0,
        "rsi14": _rsi(close_series),
        "mayer_multiple": mayer,
        "ahr999": ahr999,
        "ahr999_sma": ahr999_sma,
        "ahr999_estimate_price": estimate_price,
        "realized_volatility_30d": _realized_volatility(close_series),
        "momentum_90d": _momentum(close_series, periods=90),
        "cycle_indicator_source": "price_derived",
    }


def _with_research_cycle_fields(indicator_frame: pd.DataFrame) -> pd.DataFrame:
    frame = indicator_frame.copy()
    ahr999 = pd.to_numeric(frame["ahr999"], errors="coerce")
    mayer_multiple = pd.to_numeric(frame["mayer_multiple"], errors="coerce")
    frame["ahr999_365d_percentile"] = _trailing_percentile(ahr999, window=365)
    frame["ahr999_30d_slope"] = _trailing_slope(ahr999, periods=30)
    frame["mayer_multiple_365d_percentile"] = _trailing_percentile(
        mayer_multiple,
        window=365,
    )
    ordered_columns = [
        "date",
        "close",
        "sma200",
        "gma200",
        "high252",
        "drawdown_252d",
        "sma200_gap",
        "rsi14",
        "mayer_multiple",
        "ahr999",
        "ahr999_sma",
        "ahr999_estimate_price",
        *BTC_RESEARCH_INDICATOR_FIELDS,
        "cycle_indicator_source",
    ]
    return frame.loc[:, ordered_columns]


def _normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = sorted(required - set(ohlcv.columns))
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    frame = ohlcv.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "high" in frame.columns:
        frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
    else:
        frame["high"] = frame["close"]
    frame = frame.dropna(subset=["date", "close"])
    frame = frame.loc[frame["close"] > 0.0].sort_values("date")
    frame = frame.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if frame.empty:
        raise ValueError("OHLCV frame has no usable positive close rows")
    return frame


def _bitcoin_age_estimate_price(as_of: Any) -> float:
    timestamp = pd.Timestamp(as_of)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    age_days = max(1, int((timestamp.normalize() - BITCOIN_GENESIS_DATE).days))
    return float(10 ** (5.84 * math.log10(age_days) - 17.01))


def _geometric_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values.loc[values > 0.0]
    if values.empty:
        return float("nan")
    return float(math.exp(sum(math.log(float(value)) for value in values) / len(values)))


def _rsi(series: pd.Series, window: int = 14) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= window:
        return float("nan")
    delta = values.diff().dropna()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = float(gains.iloc[-window:].mean())
    avg_loss = float(losses.iloc[-window:].mean())
    if avg_loss <= 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    return float(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))


def _realized_volatility(series: pd.Series, window: int = 30) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= window:
        return None
    recent = values.iloc[-(window + 1) :]
    returns = (recent / recent.shift(1)).dropna()
    returns = returns.loc[returns > 0.0].apply(lambda value: math.log(float(value)))
    if len(returns) < 2:
        return None
    volatility = float(returns.std(ddof=0) * math.sqrt(365.0))
    return volatility if math.isfinite(volatility) else None


def _momentum(series: pd.Series, *, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= periods:
        return None
    previous = float(values.iloc[-(periods + 1)])
    latest = float(values.iloc[-1])
    if previous <= 0.0:
        return None
    momentum = latest / previous - 1.0
    return momentum if math.isfinite(momentum) else None


def _trailing_percentile(series: pd.Series, *, window: int) -> list[float | None]:
    values = pd.to_numeric(series, errors="coerce")
    percentiles: list[float | None] = []
    for index, latest in enumerate(values):
        if pd.isna(latest):
            percentiles.append(None)
            continue
        window_values = values.iloc[max(0, index - window + 1) : index + 1].dropna()
        if window_values.empty:
            percentiles.append(None)
            continue
        percentile = float((window_values <= float(latest)).sum() / len(window_values))
        percentiles.append(percentile)
    return percentiles


def _trailing_slope(series: pd.Series, *, periods: int) -> list[float | None]:
    values = pd.to_numeric(series, errors="coerce")
    slopes: list[float | None] = []
    for index, latest in enumerate(values):
        if index < periods or pd.isna(latest):
            slopes.append(None)
            continue
        previous = values.iloc[index - periods]
        if pd.isna(previous):
            slopes.append(None)
            continue
        slope = (float(latest) - float(previous)) / float(periods)
        slopes.append(slope if math.isfinite(slope) else None)
    return slopes


def _json_safe_indicator_value(value: Any) -> IndicatorValue:
    if value is None or isinstance(value, str):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    number = float(value)
    return number if math.isfinite(number) else None
