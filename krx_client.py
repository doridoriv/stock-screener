from datetime import datetime, timedelta

import pandas as pd
import requests

from config import REQUEST_TIMEOUT
from secret_utils import get_secret


KRX_API_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto"
KRX_ENDPOINTS = {
    "KOSPI_DAILY": "/stk_bydd_trd",
    "KOSDAQ_DAILY": "/ksq_bydd_trd",
    "KOSPI_BASE": "/stk_isu_base_info",
    "KOSDAQ_BASE": "/ksq_isu_base_info",
}


def recent_business_dates(days: int = 8):
    today = datetime.now()
    dates = []
    for offset in range(1, days + 1):
        target = today - timedelta(days=offset)
        if target.weekday() < 5:
            dates.append(target.strftime("%Y%m%d"))
    return dates


def call_krx(endpoint_name: str, bas_dd: str | None = None) -> dict:
    api_key = get_secret("KRX_API_KEY")
    if not api_key:
        return {"ok": False, "reason": "KRX_API_KEY missing"}

    endpoint = KRX_ENDPOINTS[endpoint_name]
    url = KRX_API_BASE + endpoint
    payload = {"basDd": bas_dd} if bas_dd else {}
    headers = {
        "AUTH_KEY": api_key.strip(),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        response = requests.get(url, headers=headers, params=payload, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return {
            "ok": False,
            "status_code": response.status_code,
            "reason": response.text[:160],
            "endpoint": endpoint_name,
            "basDd": bas_dd,
        }

    try:
        payload = response.json()
    except Exception as exc:
        return {"ok": False, "reason": f"invalid json: {exc}", "endpoint": endpoint_name, "basDd": bas_dd}

    rows = payload.get("OutBlock_1") or []
    return {
        "ok": True,
        "endpoint": endpoint_name,
        "basDd": bas_dd,
        "rows": rows,
        "columns": list(rows[0].keys()) if rows else [],
    }


def first_available_daily(endpoint_name: str) -> dict:
    for bas_dd in recent_business_dates():
        result = call_krx(endpoint_name, bas_dd)
        if result.get("ok") and result.get("rows"):
            return result
        if result.get("reason") == "KRX_API_KEY missing":
            return result
    return result


def rows_to_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows or [])
