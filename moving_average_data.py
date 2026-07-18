from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from config import CACHE_DIR


DEFAULT_PERIODS = (20, 60, 120, 200)
QUICK_PERIODS = (5, 10, 20, 50, 60, 80, 100, 120, 200, 240)
MIN_PERIOD = 5
MAX_PERIOD = 240
SLOPE_LOOKBACK = 5
HISTORY_ROWS = MAX_PERIOD + SLOPE_LOOKBACK + 15


def market_history_path(market_text: str) -> str:
    return os.path.join(CACHE_DIR, f"price_history_{market_text}_latest.json")


def _safe_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, 6)


def save_market_price_history(
    market_text: str,
    closes: pd.DataFrame,
    base_df: pd.DataFrame,
    data_date: Optional[str] = None,
) -> dict:
    frame = closes.sort_index().tail(HISTORY_ROWS).copy()
    frame.index = pd.to_datetime(frame.index)
    metadata = {}
    if not base_df.empty:
        for _, row in base_df.iterrows():
            yf_symbol = str(row.get("yf_symbol", "")).strip()
            if not yf_symbol:
                continue
            metadata[yf_symbol] = {
                "symbol": str(row.get("symbol", yf_symbol)).strip(),
                "name": str(row.get("name", row.get("symbol", yf_symbol))).strip(),
            }

    symbols = {}
    for yf_symbol in frame.columns:
        info = metadata.get(str(yf_symbol), {})
        symbol = info.get("symbol") or str(yf_symbol).split(".")[0]
        values = [_safe_float(value) for value in frame[yf_symbol].tolist()]
        symbols[str(symbol)] = {
            "yf_symbol": str(yf_symbol),
            "name": info.get("name") or str(symbol),
            "values": values,
        }

    payload = {
        "version": 1,
        "market": market_text,
        "data_date": data_date or (frame.index[-1].strftime("%Y-%m-%d") if len(frame.index) else None),
        "collected_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "dates": [date.strftime("%Y-%m-%d") for date in frame.index],
        "symbols": symbols,
    }

    path = market_history_path(market_text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(temp_path, path)
    return payload


def load_market_price_history(market_text: str) -> Optional[dict]:
    path = market_history_path(market_text)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload.get("symbols"), dict):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def get_symbol_history(payload: dict, symbol: str) -> Optional[dict]:
    item = (payload.get("symbols") or {}).get(str(symbol))
    if not item:
        return None
    dates = payload.get("dates") or []
    values = item.get("values") or []
    pairs = [
        (date, value)
        for date, value in zip(dates, values)
        if value is not None
    ]
    if not pairs:
        return None
    return {
        "symbol": str(symbol),
        "name": item.get("name") or str(symbol),
        "dates": [pair[0] for pair in pairs],
        "values": [pair[1] for pair in pairs],
        "data_date": payload.get("data_date") or pairs[-1][0],
        "collected_at": payload.get("collected_at"),
    }


def calculate_moving_average_rows(
    values: Iterable[float],
    periods: Iterable[int],
    slope_lookback: int = SLOPE_LOOKBACK,
) -> dict:
    series = pd.Series(list(values), dtype="float64").dropna()
    if series.empty:
        return {"close": None, "rows": []}

    close = float(series.iloc[-1])
    rows = []
    for raw_period in sorted(set(periods)):
        try:
            period = int(raw_period)
        except (TypeError, ValueError):
            continue
        if period < MIN_PERIOD or period > MAX_PERIOD or len(series) < period:
            continue

        rolling = series.rolling(period).mean().dropna()
        if rolling.empty:
            continue
        average = float(rolling.iloc[-1])
        distance = ((close - average) / average * 100) if average else None

        direction = "확인 중"
        slope_pct = None
        if len(rolling) > slope_lookback:
            previous = float(rolling.iloc[-1 - slope_lookback])
            slope_pct = ((average - previous) / previous * 100) if previous else None
            if slope_pct is not None:
                if slope_pct > 0.05:
                    direction = "상승 중"
                elif slope_pct < -0.05:
                    direction = "하락 중"
                else:
                    direction = "보합"

        rows.append({
            "period": period,
            "average": average,
            "distance_pct": distance,
            "direction": direction,
            "slope_pct": slope_pct,
        })

    return {"close": close, "rows": rows}


def summarize_alignment(rows: list[dict]) -> str:
    usable = [row for row in rows if row.get("average") is not None]
    if len(usable) < 2:
        return "배열 확인 중"
    averages = [float(row["average"]) for row in sorted(usable, key=lambda row: row["period"])]
    if all(left > right for left, right in zip(averages, averages[1:])):
        return "정배열"
    if all(left < right for left, right in zip(averages, averages[1:])):
        return "역배열"
    return "혼조 배열"
