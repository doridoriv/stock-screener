from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from config import REQUEST_TIMEOUT


NXT_MARKET_DATA_URL = "https://www.nextrade.co.kr/brdinfoTime/brdinfoTimeList.do"
NXT_REFERER = "https://www.nextrade.co.kr/menu/marketData/menuList.do"


_NXT_PRICE_CACHE = None


def _parse_nxt_time(row: dict, fallback: str | None = None) -> str:
    agg_dd = str(row.get("aggDd") or row.get("nowDd") or "")
    now_time = str(row.get("nowTime") or row.get("creTime") or "")
    if len(agg_dd) == 8 and len(now_time) >= 4:
        return f"{agg_dd[:4]}-{agg_dd[4:6]}-{agg_dd[6:8]} {now_time[:2]}:{now_time[2:4]} KST"
    return fallback or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")


def fetch_nxt_latest_prices(force_refresh: bool = False) -> dict:
    """Fetch the latest official NXT web market prices in one low-volume request."""
    global _NXT_PRICE_CACHE
    if _NXT_PRICE_CACHE is not None and not force_refresh:
        return _NXT_PRICE_CACHE

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": NXT_REFERER,
        "X-Requested-With": "XMLHttpRequest",
    }
    response = requests.post(
        NXT_MARKET_DATA_URL,
        data={"pageIndex": 1, "pageUnit": 1000},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("brdinfoTimeList") or []
    fallback_time = str(payload.get("setTime") or "").strip()

    prices = {}
    for row in rows:
        raw_code = str(row.get("isuSrdCd") or "").strip()
        code = raw_code[1:] if raw_code.startswith("A") else raw_code
        if len(code) != 6:
            continue
        price = pd.to_numeric(row.get("curPrc"), errors="coerce")
        if pd.isna(price) or float(price) <= 0:
            continue
        prices[code] = {
            "price": float(price),
            "basis": "NXT 체결가",
            "source": "nxt_web_latest",
            "time": _parse_nxt_time(row, fallback=f"{fallback_time} KST" if fallback_time else None),
        }

    _NXT_PRICE_CACHE = prices
    return prices
