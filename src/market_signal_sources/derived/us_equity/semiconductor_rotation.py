from __future__ import annotations

from collections.abc import Iterable
import math
from typing import Any

import pandas as pd


DEFAULT_SEMICONDUCTOR_ROTATION_HISTORY_LOOKBACK = 420
SEMICONDUCTOR_ROTATION_SOXL_FIELDS: tuple[str, ...] = (
    "price",
    "ma_trend",
)
SEMICONDUCTOR_ROTATION_SOXX_FIELDS: tuple[str, ...] = (
    "price",
    "ma_trend",
    "ma20",
    "ma20_slope",
    "rsi14",
    "rsi14_dynamic_threshold",
    "bb_mid",
    "bb_upper",
    "bb_lower",
    "realized_volatility",
    "realized_volatility_10",
    "realized_volatility_20",
    "realized_volatility_10_dynamic_threshold",
    "realized_volatility_10_dynamic_sample_count",
    "realized_volatility_10_dynamic_lookback",
    "realized_volatility_10_dynamic_percentile",
    "realized_volatility_10_dynamic_min_periods",
    "realized_volatility_10_dynamic_floor",
    "realized_volatility_10_dynamic_cap",
    "realized_volatility_dynamic_threshold",
    "realized_volatility_dynamic_sample_count",
    "realized_volatility_dynamic_lookback",
    "realized_volatility_dynamic_percentile",
    "realized_volatility_dynamic_min_periods",
    "realized_volatility_dynamic_floor",
    "realized_volatility_dynamic_cap",
)
SEMICONDUCTOR_ROTATION_DERIVED_INDICATOR_FIELDS: tuple[str, ...] = tuple(
    dict.fromkeys((*SEMICONDUCTOR_ROTATION_SOXL_FIELDS, *SEMICONDUCTOR_ROTATION_SOXX_FIELDS))
)
IndicatorValue = float | str | None


def compute_semiconductor_rotation_indicators(
    soxl_ohlcv: pd.DataFrame,
    soxx_ohlcv: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    trend_ma_window: int = 140,
    dynamic_rsi_quantile_window: int = 252,
    dynamic_rsi_quantile: float = 0.90,
    dynamic_rsi_floor: float = 70.0,
    dynamic_volatility_delever_window: int = 10,
    dynamic_volatility_delever_quantile_window: int = 252,
    dynamic_volatility_delever_quantile: float = 0.95,
    dynamic_volatility_delever_min_periods: int = 126,
    dynamic_volatility_delever_floor: float = 0.50,
    dynamic_volatility_delever_cap: float = 0.75,
    min_history: int | None = None,
) -> dict[str, dict[str, IndicatorValue]]:
    """Compute SOXL/SOXX rotation indicators from daily OHLCV close history."""

    soxl_frame = _normalize_ohlcv(soxl_ohlcv)
    soxx_frame = _normalize_ohlcv(soxx_ohlcv)
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).tz_localize(None).normalize()
        soxl_frame = soxl_frame.loc[soxl_frame["date"] <= cutoff]
        soxx_frame = soxx_frame.loc[soxx_frame["date"] <= cutoff]

    required_rows = (
        int(min_history)
        if min_history is not None
        else required_semiconductor_rotation_history_lookback(
            trend_ma_window=trend_ma_window,
            dynamic_rsi_quantile_window=dynamic_rsi_quantile_window,
            dynamic_volatility_delever_window=dynamic_volatility_delever_window,
            dynamic_volatility_delever_quantile_window=(
                dynamic_volatility_delever_quantile_window
            ),
        )
    )
    if required_rows <= 0:
        raise ValueError("min_history must be positive")
    if len(soxl_frame) < required_rows or len(soxx_frame) < required_rows:
        raise ValueError(
            "semiconductor rotation indicators require sufficient SOXL/SOXX history"
        )

    soxl_close = tuple(float(value) for value in soxl_frame["close"])
    soxx_close = tuple(float(value) for value in soxx_frame["close"])
    indicators = _build_semiconductor_rotation_indicators_from_history(
        soxl_history=soxl_close,
        soxx_history=soxx_close,
        trend_ma_window=trend_ma_window,
        dynamic_rsi_quantile_window=dynamic_rsi_quantile_window,
        dynamic_rsi_quantile=dynamic_rsi_quantile,
        dynamic_rsi_floor=dynamic_rsi_floor,
        dynamic_volatility_delever_window=dynamic_volatility_delever_window,
        dynamic_volatility_delever_quantile_window=(
            dynamic_volatility_delever_quantile_window
        ),
        dynamic_volatility_delever_quantile=dynamic_volatility_delever_quantile,
        dynamic_volatility_delever_min_periods=dynamic_volatility_delever_min_periods,
        dynamic_volatility_delever_floor=dynamic_volatility_delever_floor,
        dynamic_volatility_delever_cap=dynamic_volatility_delever_cap,
    )
    return {
        symbol: {
            key: _json_safe_indicator_value(value)
            for key, value in payload.items()
        }
        for symbol, payload in indicators.items()
    }


def required_semiconductor_rotation_history_lookback(
    *,
    trend_ma_window: int = 140,
    dynamic_rsi_quantile_window: int = 252,
    dynamic_volatility_delever_window: int = 10,
    dynamic_volatility_delever_quantile_window: int = 252,
    minimum_lookback: int = DEFAULT_SEMICONDUCTOR_ROTATION_HISTORY_LOOKBACK,
) -> int:
    """Return the close-history rows needed for default SOXL/SOXX indicators."""

    return max(
        int(minimum_lookback),
        int(trend_ma_window) + 20,
        int(dynamic_rsi_quantile_window) + 28,
        int(dynamic_volatility_delever_quantile_window)
        + int(dynamic_volatility_delever_window)
        + 1,
    )


def _build_semiconductor_rotation_indicators_from_history(
    *,
    soxl_history: Iterable[float],
    soxx_history: Iterable[float],
    trend_ma_window: int,
    dynamic_rsi_quantile_window: int,
    dynamic_rsi_quantile: float,
    dynamic_rsi_floor: float,
    dynamic_volatility_delever_window: int,
    dynamic_volatility_delever_quantile_window: int,
    dynamic_volatility_delever_quantile: float,
    dynamic_volatility_delever_min_periods: int,
    dynamic_volatility_delever_floor: float,
    dynamic_volatility_delever_cap: float,
) -> dict[str, dict[str, float]]:
    window = int(trend_ma_window)
    if window <= 0:
        raise ValueError("trend_ma_window must be positive")
    rsi_quantile_window = int(dynamic_rsi_quantile_window)
    if rsi_quantile_window <= 0:
        raise ValueError("dynamic_rsi_quantile_window must be positive")
    rsi_quantile = float(dynamic_rsi_quantile)
    if not 0.0 < rsi_quantile < 1.0:
        raise ValueError("dynamic_rsi_quantile must be between 0 and 1")
    volatility_window = int(dynamic_volatility_delever_window)
    if volatility_window <= 0:
        raise ValueError("dynamic_volatility_delever_window must be positive")
    volatility_quantile_window = int(dynamic_volatility_delever_quantile_window)
    if volatility_quantile_window <= 0:
        raise ValueError("dynamic_volatility_delever_quantile_window must be positive")
    volatility_quantile = float(dynamic_volatility_delever_quantile)
    if not 0.0 < volatility_quantile < 1.0:
        raise ValueError("dynamic_volatility_delever_quantile must be between 0 and 1")
    volatility_min_periods = max(
        1,
        min(volatility_quantile_window, int(dynamic_volatility_delever_min_periods)),
    )

    soxl_close = _normalize_numeric_history(soxl_history, label="SOXL")
    soxx_close = _normalize_numeric_history(soxx_history, label="SOXX")
    if len(soxl_close) < window or len(soxx_close) < window:
        raise ValueError(
            "semiconductor rotation inputs require sufficient SOXL/SOXX history"
        )

    soxl_ma_trend = _tail_mean(soxl_close, window)
    soxx_ma_trend = _tail_mean(soxx_close, window)
    soxx_ma20 = _tail_mean(soxx_close, 20)
    soxx_ma20_prev = _tail_mean(soxx_close[:-1], 20)
    soxx_ma20_slope = float(soxx_ma20 - soxx_ma20_prev)
    soxx_rsi_history = _compute_rsi(soxx_close, window=14)
    soxx_rsi14 = float(soxx_rsi_history[-1])
    rsi_threshold_history = _rolling_quantile(
        soxx_rsi_history,
        window=rsi_quantile_window,
        quantile=rsi_quantile,
    )
    previous_threshold = (
        rsi_threshold_history[-2] if len(rsi_threshold_history) >= 2 else None
    )
    soxx_dynamic_rsi_threshold = float(
        max(
            float(dynamic_rsi_floor),
            float(previous_threshold)
            if previous_threshold is not None
            else float(dynamic_rsi_floor),
        )
    )
    soxx_bb_mid = _tail_mean(soxx_close, 20)
    soxx_bb_std = _tail_std(soxx_close, 20)
    soxx_realized_volatility_10 = _tail_realized_volatility(soxx_close, 10)
    soxx_realized_volatility_20 = _tail_realized_volatility(soxx_close, 20)
    soxx_volatility_history = _realized_volatility_history(
        soxx_close,
        window=volatility_window,
    )
    volatility_threshold_history = _rolling_quantile(
        soxx_volatility_history,
        window=volatility_quantile_window,
        quantile=volatility_quantile,
        min_periods=volatility_min_periods,
    )
    soxx_dynamic_volatility_threshold = _bounded_threshold(
        volatility_threshold_history[-1],
        floor=dynamic_volatility_delever_floor,
        cap=dynamic_volatility_delever_cap,
    )
    soxx_dynamic_volatility_sample_count = _rolling_count(
        soxx_volatility_history,
        window=volatility_quantile_window,
    )[-1]
    volatility_threshold_fields = {
        (
            f"realized_volatility_{volatility_window}_dynamic_threshold"
        ): soxx_dynamic_volatility_threshold,
        f"realized_volatility_{volatility_window}_dynamic_sample_count": float(
            soxx_dynamic_volatility_sample_count
        ),
        f"realized_volatility_{volatility_window}_dynamic_lookback": float(
            volatility_quantile_window
        ),
        (
            f"realized_volatility_{volatility_window}_dynamic_percentile"
        ): volatility_quantile,
        f"realized_volatility_{volatility_window}_dynamic_min_periods": float(
            volatility_min_periods
        ),
        f"realized_volatility_{volatility_window}_dynamic_floor": float(
            dynamic_volatility_delever_floor
        ),
        f"realized_volatility_{volatility_window}_dynamic_cap": float(
            dynamic_volatility_delever_cap
        ),
        "realized_volatility_dynamic_threshold": soxx_dynamic_volatility_threshold,
        "realized_volatility_dynamic_sample_count": float(
            soxx_dynamic_volatility_sample_count
        ),
        "realized_volatility_dynamic_lookback": float(volatility_quantile_window),
        "realized_volatility_dynamic_percentile": volatility_quantile,
        "realized_volatility_dynamic_min_periods": float(volatility_min_periods),
        "realized_volatility_dynamic_floor": float(dynamic_volatility_delever_floor),
        "realized_volatility_dynamic_cap": float(dynamic_volatility_delever_cap),
    }
    return {
        "SOXL": {
            "price": float(soxl_close[-1]),
            "ma_trend": soxl_ma_trend,
        },
        "SOXX": {
            "price": float(soxx_close[-1]),
            "ma_trend": soxx_ma_trend,
            "ma20": soxx_ma20,
            "ma20_slope": soxx_ma20_slope,
            "rsi14": soxx_rsi14,
            "rsi14_dynamic_threshold": soxx_dynamic_rsi_threshold,
            "bb_mid": soxx_bb_mid,
            "bb_upper": soxx_bb_mid + 2.0 * soxx_bb_std,
            "bb_lower": soxx_bb_mid - 2.0 * soxx_bb_std,
            "realized_volatility": soxx_realized_volatility_20,
            "realized_volatility_10": soxx_realized_volatility_10,
            "realized_volatility_20": soxx_realized_volatility_20,
            **{
                key: value
                for key, value in volatility_threshold_fields.items()
                if value is not None
            },
        },
    }


def _normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = sorted(required - set(ohlcv.columns))
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    frame = ohlcv.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=("date", "close"))
    frame = frame.loc[frame["close"] > 0.0].sort_values("date")
    frame = frame.drop_duplicates(subset=("date",), keep="last").reset_index(drop=True)
    if frame.empty:
        raise ValueError("OHLCV frame has no usable positive close rows")
    return frame


def _normalize_numeric_history(
    history: Iterable[float],
    *,
    label: str,
) -> tuple[float, ...]:
    normalized: list[float] = []
    for value in history:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(numeric):
            continue
        normalized.append(numeric)
    if not normalized:
        raise ValueError(
            f"semiconductor rotation inputs require non-empty {label} history"
        )
    return tuple(normalized)


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    if not values:
        raise ValueError("mean requires at least one value")
    return float(sum(values) / len(values))


def _std(values: Iterable[float]) -> float:
    values = tuple(values)
    if not values:
        raise ValueError("std requires at least one value")
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return float(math.sqrt(variance))


def _sample_std(values: Iterable[float]) -> float:
    values = tuple(values)
    if len(values) < 2:
        raise ValueError("sample std requires at least two values")
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return float(math.sqrt(variance))


def _tail_mean(values: tuple[float, ...], window: int) -> float:
    if len(values) < window:
        raise ValueError("insufficient history for rolling mean")
    return _mean(values[-window:])


def _tail_std(values: tuple[float, ...], window: int) -> float:
    if len(values) < window:
        raise ValueError("insufficient history for rolling std")
    return _std(values[-window:])


def _sample_realized_volatility(values: tuple[float, ...], window: int) -> float:
    if len(values) < window + 1:
        raise ValueError("insufficient history for realized volatility")
    tail_values = values[-(window + 1) :]
    returns: list[float] = []
    for previous, current in zip(tail_values, tail_values[1:]):
        if previous == 0.0:
            raise ValueError("realized volatility requires non-zero prices")
        returns.append((current / previous) - 1.0)
    return float(_sample_std(returns) * math.sqrt(252.0))


def _tail_realized_volatility(values: tuple[float, ...], window: int) -> float:
    return _sample_realized_volatility(values, window)


def _realized_volatility_history(
    values: tuple[float, ...],
    *,
    window: int,
) -> tuple[float | None, ...]:
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[float | None] = [None] * len(values)
    for index in range(window, len(values)):
        result[index] = _sample_realized_volatility(
            values[index - window : index + 1],
            window,
        )
    return tuple(result)


def _compute_rsi(values: tuple[float, ...], *, window: int = 14) -> tuple[float, ...]:
    if len(values) < window + 1:
        raise ValueError("insufficient history for RSI")
    rsis = [50.0] * len(values)
    gains = 0.0
    losses = 0.0
    for index in range(1, window + 1):
        delta = values[index] - values[index - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / window
    avg_loss = losses / window

    def _rsi_from_avg(avg_gain_value: float, avg_loss_value: float) -> float:
        if avg_gain_value == 0.0 and avg_loss_value == 0.0:
            return 50.0
        if avg_loss_value == 0.0:
            return 100.0
        if avg_gain_value == 0.0:
            return 0.0
        rs = avg_gain_value / avg_loss_value
        return 100.0 - (100.0 / (1.0 + rs))

    rsis[window] = _rsi_from_avg(avg_gain, avg_loss)
    alpha = 1.0 / window
    for index in range(window + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (1.0 - alpha) * avg_gain + alpha * gain
        avg_loss = (1.0 - alpha) * avg_loss + alpha * loss
        rsis[index] = _rsi_from_avg(avg_gain, avg_loss)
    return tuple(rsis)


def _rolling_count(values: tuple[float | None, ...], *, window: int) -> tuple[int, ...]:
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[int] = [0] * len(values)
    for index in range(len(values)):
        start = max(0, index - window + 1)
        result[index] = sum(
            1 for value in values[start : index + 1] if value is not None
        )
    return tuple(result)


def _rolling_quantile(
    values: tuple[float | None, ...],
    *,
    window: int,
    quantile: float,
    min_periods: int | None = None,
) -> tuple[float | None, ...]:
    if window <= 0:
        raise ValueError("window must be positive")
    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must be between 0 and 1")
    effective_min_periods = window if min_periods is None else max(1, int(min_periods))
    result: list[float | None] = [None] * len(values)
    for index in range(len(values)):
        start = max(0, index - window + 1)
        chunk = sorted(
            value for value in values[start : index + 1] if value is not None
        )
        if len(chunk) < effective_min_periods:
            continue
        position = (len(chunk) - 1) * quantile
        lower_index = int(position)
        upper_index = min(lower_index + 1, len(chunk) - 1)
        fraction = position - lower_index
        result[index] = (
            chunk[lower_index] * (1.0 - fraction) + chunk[upper_index] * fraction
        )
    return tuple(result)


def _bounded_threshold(
    value: float | None,
    *,
    floor: float | None,
    cap: float | None,
) -> float | None:
    if value is None:
        return None
    threshold = float(value)
    if floor is not None:
        threshold = max(float(floor), threshold)
    if cap is not None:
        threshold = min(float(cap), threshold)
    return threshold


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
