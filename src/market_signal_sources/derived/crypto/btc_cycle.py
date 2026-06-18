from __future__ import annotations

import math
from typing import Any

import pandas as pd


BITCOIN_GENESIS_DATE = pd.Timestamp("2009-01-03")


def compute_btc_cycle_indicators(
    ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    min_history: int = 200,
) -> dict[str, float | str]:
    """Compute deterministic BTC cycle indicators from local daily OHLCV data."""

    frame = _normalize_ohlcv(ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        frame = frame.loc[frame["date"] <= cutoff]
    if len(frame) < int(min_history):
        raise ValueError(f"BTC cycle indicators require at least {int(min_history)} rows")

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
        "cycle_indicator_source": "price_derived",
    }


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
