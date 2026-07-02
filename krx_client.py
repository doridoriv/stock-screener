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


def _first_text(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        text = _clean_text(value)
        if text:
            return text
    return ""


def _clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _fetch_description_map() -> dict:
    try:
        import FinanceDataReader as fdr

        df = fdr.StockListing("KRX-DESC")
    except Exception:
        return {}

    info = {}
    if df is None or df.empty or "Code" not in df.columns:
        return info

    for _, row in df.iterrows():
        code = _clean_text(row.get("Code")).zfill(6)
        if not code:
            continue
        industry = _clean_text(row.get("Industry"))
        department = _clean_text(row.get("Sector"))
        products = _clean_text(row.get("Products"))
        info[code] = {
            "industry": industry,
            "sector": industry,
            "listing_department": department,
            "products": products,
        }
    return info


def fetch_base_info_map(market_type: str) -> dict:
    endpoint_name = "KOSDAQ_BASE" if str(market_type).upper() == "KOSDAQ" else "KOSPI_BASE"
    result = call_krx(endpoint_name)
    if not result.get("ok"):
        return {}
    if not result.get("rows"):
        for bas_dd in recent_business_dates():
            dated_result = call_krx(endpoint_name, bas_dd)
            if dated_result.get("ok") and dated_result.get("rows"):
                result = dated_result
                break

    description_map = _fetch_description_map()
    info = {}
    for row in result.get("rows") or []:
        raw_code = _first_text(row, ["ISU_SRT_CD", "isuSrtCd", "short_code", "symbol"])
        if not raw_code:
            continue
        code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
        desc = description_map.get(code, {})
        industry = desc.get("industry") or _first_text(row, ["IND_TP_NM", "idxIndNm", "IDX_IND_NM"])
        sector = desc.get("sector") or industry
        listing_department = desc.get("listing_department") or _first_text(row, ["SECT_TP_NM", "sectTpNm"])
        info[code] = {
            "sector": sector,
            "industry": industry,
            "listing_department": listing_department,
            "products": desc.get("products", ""),
            "krx_market": _first_text(row, ["MKT_TP_NM", "MKT_NM", "mktTpNm", "mktNm"]),
            "security_group": _first_text(row, ["SECUGRP_NM", "secugrpNm"]),
            "krx_source": "KRX",
        }
    return info
