import io
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

import numpy as np
import pandas as pd
import requests

from config import CACHE_DIR, REQUEST_TIMEOUT
from secret_utils import get_secret


CORP_CODE_CACHE = os.path.join(CACHE_DIR, "dart_corp_codes.csv")
REPORT_CODES = ["11011", "11014", "11012", "11013"]


def _to_number(value):
    if value is None:
        return np.nan
    text = str(value).replace(",", "").replace("−", "-").strip()
    if not text or text in ["-", "nan", "None"]:
        return np.nan
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        parsed = float(text)
        return -parsed if negative else parsed
    except Exception:
        return np.nan


def _won_to_eok(value):
    value = _to_number(value)
    if pd.isna(value):
        return np.nan
    return round(value / 100000000, 2)


def _latest_business_year():
    now = datetime.now()
    return now.year - 1


def _download_corp_codes(api_key: str) -> pd.DataFrame:
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    response = requests.get(url, params={"crtfc_key": api_key}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        xml_name = zf.namelist()[0]
        root = ET.fromstring(zf.read(xml_name))

    rows = []
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        if not stock_code:
            continue
        rows.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": stock_code.zfill(6),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        })
    df = pd.DataFrame(rows)
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(CORP_CODE_CACHE, index=False, encoding="utf-8-sig")
    return df


def load_corp_codes(api_key: str) -> pd.DataFrame:
    if os.path.exists(CORP_CODE_CACHE):
        try:
            return pd.read_csv(CORP_CODE_CACHE, dtype={"stock_code": str, "corp_code": str})
        except Exception:
            pass
    return _download_corp_codes(api_key)


def get_corp_code(stock_code: str, api_key: str) -> str | None:
    clean_code = str(stock_code).split(".")[0].zfill(6)
    df = load_corp_codes(api_key)
    matched = df[df["stock_code"].astype(str).str.zfill(6) == clean_code]
    if matched.empty:
        return None
    return str(matched.iloc[0]["corp_code"]).zfill(8)


def _fetch_statement_rows(api_key: str, corp_code: str, year: int, fs_div: str):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",
        "fs_div": fs_div,
    }
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "000":
        return []
    return payload.get("list") or []


def _row_text(row, *keys):
    return " ".join(str(row.get(key, "") or "") for key in keys)


def _matches_any(text, candidates):
    return any(candidate and candidate in text for candidate in candidates)


def _pick(rows, statement_names=None, account_keywords=None, account_ids=None):
    statement_names = statement_names or []
    account_keywords = account_keywords or []
    account_ids = account_ids or []

    candidates = []
    for row in rows:
        statement_text = _row_text(row, "sj_nm")
        account_text = _row_text(row, "account_nm")
        account_id = str(row.get("account_id", "") or "")

        if account_ids and account_id in account_ids:
            candidates.append((0, row))
            continue
        if statement_names and not _matches_any(statement_text, statement_names):
            continue
        if account_keywords and _matches_any(account_text, account_keywords):
            candidates.append((1, row))

    if not candidates:
        return np.nan
    candidates.sort(key=lambda item: (item[0], len(str(item[1].get("account_nm", "")))))
    return _won_to_eok(candidates[0][1].get("thstrm_amount"))


def _sum_picks(rows, statement_names=None, account_keywords=None, account_ids=None):
    statement_names = statement_names or []
    account_keywords = account_keywords or []
    account_ids = account_ids or []
    seen = set()
    values = []
    for row in rows:
        statement_text = _row_text(row, "sj_nm")
        account_text = _row_text(row, "account_nm")
        account_id = str(row.get("account_id", "") or "")
        matched = (
            (account_ids and account_id in account_ids)
            or (
                (not statement_names or _matches_any(statement_text, statement_names))
                and account_keywords
                and _matches_any(account_text, account_keywords)
            )
        )
        if not matched:
            continue
        key = (account_id, account_text)
        if key in seen:
            continue
        seen.add(key)
        value = _won_to_eok(row.get("thstrm_amount"))
        if pd.notna(value):
            values.append(value)
    if not values:
        return np.nan
    return round(sum(values), 2)


def _statement_metrics(rows):
    income_statements = ["손익계산서", "포괄손익계산서"]
    balance_sheets = ["재무상태표"]
    cashflow_statements = ["현금흐름표"]

    revenue = _pick(
        rows,
        income_statements,
        ["매출액", "수익(매출액)", "영업수익"],
        ["ifrs-full_Revenue", "dart_OperatingRevenue"],
    )
    operating_income = _pick(
        rows,
        income_statements,
        ["영업이익"],
        ["dart_OperatingIncomeLoss"],
    )
    net_income = _pick(
        rows,
        income_statements,
        ["당기순이익", "분기순이익", "반기순이익"],
        ["ifrs-full_ProfitLoss"],
    )
    cash = _pick(
        rows,
        balance_sheets,
        ["현금및현금성자산", "현금 및 현금성자산", "현금및예치금", "현금 및 예치금"],
        ["ifrs-full_CashAndCashEquivalents", "dart_CashAndCashEquivalents"],
    )
    total_debt = _pick(
        rows,
        balance_sheets,
        ["부채총계", "부채 총계"],
        ["ifrs-full_Liabilities"],
    )
    operating_cashflow = _pick(
        rows,
        cashflow_statements,
        [
            "영업활동현금흐름",
            "영업활동 현금흐름",
            "영업활동으로 인한 현금흐름",
            "영업활동으로부터의 현금흐름",
            "영업활동에서 창출된 현금흐름",
        ],
        ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
    )
    capex = _sum_picks(
        rows,
        cashflow_statements,
        [
            "유형자산의 취득",
            "유형자산 취득",
            "유형자산의 증가",
            "무형자산의 취득",
            "무형자산 취득",
            "투자부동산의 취득",
        ],
        [
            "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
            "ifrs-full_PurchaseOfInvestmentPropertyClassifiedAsInvestingActivities",
        ],
    )

    metrics = {
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "cash": cash,
        "total_debt": total_debt,
        "operating_cashflow": operating_cashflow,
        "dart_source": "OpenDART",
    }
    if pd.notna(cash) and pd.notna(total_debt):
        metrics["net_cash"] = round(cash - total_debt, 2)
    if pd.notna(operating_cashflow) and pd.notna(capex):
        metrics["free_cashflow"] = round(operating_cashflow - abs(capex), 2)
    if pd.notna(revenue) and revenue > 0:
        if pd.notna(operating_income):
            metrics["operating_margin"] = round((operating_income / revenue) * 100, 2)
        if pd.notna(net_income):
            metrics["net_margin"] = round((net_income / revenue) * 100, 2)
    return metrics


def fetch_dart_metrics(stock_code: str, year: int | None = None) -> dict:
    api_key = get_secret("DART_API_KEY")
    if not api_key:
        return {}

    corp_code = get_corp_code(stock_code, api_key)
    if not corp_code:
        return {}

    start_year = year or _latest_business_year()
    for target_year in range(start_year, start_year - 3, -1):
        for fs_div in ["CFS", "OFS"]:
            try:
                rows = _fetch_statement_rows(api_key, corp_code, target_year, fs_div)
            except Exception:
                rows = []
            if not rows:
                continue
            metrics = _statement_metrics(rows)
            metrics["dart_year"] = target_year
            metrics["dart_fs_div"] = fs_div
            return {k: v for k, v in metrics.items() if not (isinstance(v, float) and pd.isna(v))}
    return {}
