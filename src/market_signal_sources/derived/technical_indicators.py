from __future__ import annotations

import math
from typing import Any

import pandas as pd


TECHNICAL_INDICATOR_FIELDS: tuple[str, ...] = (
    "close",
    "sma20",
    "sma50",
    "sma100",
    "sma200",
    "ema20",
    "ema50",
    "high252",
    "drawdown_252d",
    "sma200_gap",
    "rsi14",
    "atr14",
    "realized_volatility_20d",
    "realized_volatility_63d",
    "momentum_90d",
    "trend_score",
)
IndicatorValue = float | str | None


def compute_daily_technical_indicators(
    ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    min_history: int = 252,
) -> dict[str, IndicatorValue]:
    """Compute deterministic daily technical indicators from local OHLCV data."""

    frame = _normalize_ohlcv(ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        frame = frame.loc[frame["date"] <= cutoff]
    if len(frame) < int(min_history):
        raise ValueError(
            f"daily technical indicators require at least {int(min_history)} rows"
        )
    indicator_frame = build_daily_technical_indicator_frame(
        frame,
        min_history=int(min_history),
    )
    latest = indicator_frame.iloc[-1].to_dict()
    latest.pop("date", None)
    return {
        str(field): _json_safe_indicator_value(value)
        for field, value in latest.items()
    }


def build_daily_technical_indicator_frame(
    ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    min_history: int = 252,
) -> pd.DataFrame:
    """Build a daily technical indicator frame for research exports or bundles."""

    frame = _normalize_ohlcv(ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        frame = frame.loc[frame["date"] <= cutoff].reset_index(drop=True)
    if len(frame) < int(min_history):
        raise ValueError(
            f"daily technical indicator frame requires at least {int(min_history)} rows"
        )

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    output = pd.DataFrame({"date": frame["date"]})
    output["close"] = close
    output["sma20"] = close.rolling(20, min_periods=20).mean()
    output["sma50"] = close.rolling(50, min_periods=50).mean()
    output["sma100"] = close.rolling(100, min_periods=100).mean()
    output["sma200"] = close.rolling(200, min_periods=200).mean()
    output["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    output["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    output["high252"] = high.rolling(252, min_periods=252).max()
    output["drawdown_252d"] = _safe_ratio_drawdown(close, output["high252"])
    output["sma200_gap"] = _safe_ratio_gap(close, output["sma200"])
    output["rsi14"] = _rsi(close, window=14)
    output["atr14"] = _atr(high, low, close, window=14)
    output["realized_volatility_20d"] = _realized_volatility(close, window=20)
    output["realized_volatility_63d"] = _realized_volatility(close, window=63)
    output["momentum_90d"] = close / close.shift(90) - 1.0
    output["trend_score"] = _trend_score(
        close=close,
        sma50=output["sma50"],
        sma200=output["sma200"],
        rsi14=output["rsi14"],
    )
    output = output.dropna(subset=("close", "sma200", "high252")).reset_index(drop=True)
    if output.empty:
        raise ValueError("daily technical indicator frame has no complete rows")
    output["date"] = pd.to_datetime(output["date"]).dt.date.astype(str)
    return output.loc[:, ("date", *TECHNICAL_INDICATOR_FIELDS)]


def _normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = sorted(required - set(ohlcv.columns))
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    frame = ohlcv.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "high" not in frame.columns:
        frame["high"] = frame["close"]
    if "low" not in frame.columns:
        frame["low"] = frame["close"]
    frame = frame.dropna(subset=("date", "close", "high", "low"))
    frame = frame.loc[
        (frame["close"] > 0.0)
        & (frame["high"] > 0.0)
        & (frame["low"] > 0.0)
    ].sort_values("date")
    frame = frame.drop_duplicates(subset=("date",), keep="last").reset_index(drop=True)
    if frame.empty:
        raise ValueError("OHLCV frame has no usable positive rows")
    return frame


def _safe_ratio_gap(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(denominator, errors="coerce")
    result = numerator / denominator - 1.0
    return result.where(denominator > 0.0)


def _safe_ratio_drawdown(close: pd.Series, high: pd.Series) -> pd.Series:
    high = pd.to_numeric(high, errors="coerce")
    result = 1.0 - close / high
    return result.where(high > 0.0).clip(lower=0.0)


def _rsi(series: pd.Series, *, window: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    delta = values.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.rolling(window, min_periods=window).mean()
    avg_loss = losses.rolling(window, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask((avg_loss <= 0.0) & (avg_gain > 0.0), 100.0)
    rsi = rsi.mask((avg_loss <= 0.0) & (avg_gain <= 0.0), 50.0)
    return rsi


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, *, window: int) -> pd.Series:
    previous_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    true_range = ranges.max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _realized_volatility(close: pd.Series, *, window: int) -> pd.Series:
    returns = (close / close.shift(1)).apply(
        lambda value: math.log(float(value)) if value and value > 0.0 else float("nan")
    )
    return returns.rolling(window, min_periods=window).std(ddof=0) * math.sqrt(252.0)


def _trend_score(
    *,
    close: pd.Series,
    sma50: pd.Series,
    sma200: pd.Series,
    rsi14: pd.Series,
) -> pd.Series:
    price_component = _signed_component(close / sma200 - 1.0)
    trend_component = _signed_component(sma50 / sma200 - 1.0)
    rsi_component = ((rsi14 - 50.0) / 50.0).clip(lower=-1.0, upper=1.0)
    return 0.4 * price_component + 0.35 * trend_component + 0.25 * rsi_component


def _signed_component(series: pd.Series) -> pd.Series:
    return (series / 0.10).clip(lower=-1.0, upper=1.0)


def _json_safe_indicator_value(value: Any) -> IndicatorValue:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(numeric):
        return None
    return numeric
