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
KRW_CURRENCIES = {"KRW", "KOREAN WON", "원", "￦", "₩"}


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


def _row_currency(row) -> str:
    return str(row.get("currency") or row.get("currency_nm") or "").strip().upper()


def _is_krw_row(row) -> bool:
    currency = _row_currency(row)
    return not currency or currency in KRW_CURRENCIES


def _row_amount_eok(row):
    if not _is_krw_row(row):
        return np.nan
    return _won_to_eok(row.get("thstrm_amount"))


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


def _fetch_statement_rows(api_key: str, corp_code: str, year: int, fs_div: str, report_code: str = "11011"):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report_code,
        "fs_div": fs_div,
    }
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "000":
        return []
    return payload.get("list") or []


def _fetch_dividend_rows(api_key: str, corp_code: str, year: int, report_code: str = "11011"):
    url = "https://opendart.fss.or.kr/api/alotMatter.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report_code,
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
    for _, row in candidates:
        value = _row_amount_eok(row)
        if pd.notna(value):
            return value
    return np.nan


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
        value = _row_amount_eok(row)
        if pd.notna(value):
            seen.add(key)
            values.append(value)
    if not values:
        return np.nan
    return round(sum(values), 2)


def _pick_dividend(rows, se_keywords, stock_kind_keywords=None):
    stock_kind_keywords = stock_kind_keywords or []
    candidates = []
    for row in rows:
        se_text = str(row.get("se", "") or "")
        stock_kind = str(row.get("stock_knd", "") or "")
        if not _matches_any(se_text, se_keywords):
            continue
        if stock_kind_keywords and stock_kind and not _matches_any(stock_kind, stock_kind_keywords):
            continue
        priority = 0 if "보통주" in stock_kind else 1 if not stock_kind else 2
        candidates.append((priority, row))

    if not candidates:
        return np.nan
    candidates.sort(key=lambda item: item[0])
    return _to_number(candidates[0][1].get("thstrm"))


def _dividend_metrics(rows):
    if not rows:
        return {}

    dividend_yield = _pick_dividend(rows, ["현금배당수익률"], ["보통주"])
    payout_ratio = _pick_dividend(rows, ["현금배당성향"])
    dividend_per_share = _pick_dividend(rows, ["주당 현금배당금"], ["보통주"])
    dividend_total_million = _pick_dividend(rows, ["현금배당금총액"])

    metrics = {
        "dividend_yield": dividend_yield,
        "payout_ratio": payout_ratio,
        "dividend_per_share": dividend_per_share,
    }
    if pd.notna(dividend_total_million):
        metrics["dividend_total"] = round(dividend_total_million / 100, 2)
    if any(pd.notna(value) for value in metrics.values()):
        metrics["dividend_source"] = "OpenDART"
        return metrics
    return {}


def _summarize_dividend_history(history: list[dict], start_year: int, years: int = 5) -> dict:
    by_year = {item["year"]: _to_number(item.get("dividend_per_share")) for item in history}
    positive_years = {
        year: value
        for year, value in by_year.items()
        if pd.notna(value) and value > 0
    }
    if not positive_years:
        return {}

    consecutive_years = 0
    for target_year in range(start_year, start_year - years, -1):
        value = by_year.get(target_year, np.nan)
        if pd.isna(value) or value <= 0:
            break
        consecutive_years += 1

    adjacent_cuts = []
    for newer_year in range(start_year, start_year - years + 1, -1):
        newer = by_year.get(newer_year, np.nan)
        older = by_year.get(newer_year - 1, np.nan)
        if pd.notna(newer) and newer > 0 and pd.notna(older) and older > 0:
            adjacent_cuts.append(newer < older)

    cut_flag = True if any(adjacent_cuts) else False if consecutive_years == years else None
    result = {
        "dividend_history_years": len(positive_years),
        "dividend_consecutive_years": consecutive_years,
        "dividend_cut_flag": cut_flag,
        "dividend_history_source": "OpenDART",
    }

    growth_values = [by_year.get(year, np.nan) for year in range(start_year - 3, start_year + 1)]
    if all(pd.notna(value) and value > 0 for value in growth_values):
        result["dividend_growth_3y"] = round(((growth_values[-1] / growth_values[0]) ** (1 / 3) - 1) * 100, 2)
    return result


def _collect_dividend_history(api_key: str, corp_code: str, start_year: int, years: int = 5) -> dict:
    history = []
    for target_year in range(start_year, start_year - years, -1):
        try:
            rows = _fetch_dividend_rows(api_key, corp_code, target_year, "11011")
        except Exception:
            rows = []
        metrics = _dividend_metrics(rows)
        history.append({
            "year": target_year,
            "report_code": "11011",
            "dividend_per_share": metrics.get("dividend_per_share") if metrics else np.nan,
        })

    return _summarize_dividend_history(history, start_year, years)


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
    currencies = sorted({_row_currency(row) for row in rows if _row_currency(row)})
    has_krw_rows = any(_is_krw_row(row) for row in rows)
    if has_krw_rows:
        metrics["financial_currency"] = "KRW"
    elif currencies:
        metrics["financial_currency"] = "/".join(currencies)
    if currencies and not has_krw_rows:
        metrics["cashflow_status"] = "외화 공시 환산 필요"
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
    dividend_history = _collect_dividend_history(api_key, corp_code, start_year)
    for target_year in range(start_year, start_year - 3, -1):
        best_metrics = dict(dividend_history)
        for report_code in REPORT_CODES:
            try:
                dividend_rows = _fetch_dividend_rows(api_key, corp_code, target_year, report_code)
            except Exception:
                dividend_rows = []
            dividend_metrics = _dividend_metrics(dividend_rows)
            if dividend_metrics:
                dividend_metrics["dividend_year"] = target_year
                dividend_metrics["dividend_report_code"] = report_code
                cleaned_dividend = {k: v for k, v in dividend_metrics.items() if not (isinstance(v, float) and pd.isna(v))}
                best_metrics.update({k: v for k, v in cleaned_dividend.items() if k not in best_metrics})

            for fs_div in ["CFS", "OFS"]:
                try:
                    rows = _fetch_statement_rows(api_key, corp_code, target_year, fs_div, report_code)
                except Exception:
                    rows = []
                if not rows:
                    continue
                metrics = _statement_metrics(rows)
                metrics["dart_year"] = target_year
                metrics["dart_fs_div"] = fs_div
                metrics["dart_report_code"] = report_code
                numeric_fields = [
                    "revenue",
                    "operating_income",
                    "net_income",
                    "cash",
                    "total_debt",
                    "operating_cashflow",
                    "free_cashflow",
                ]
                has_usable_statement = any(pd.notna(metrics.get(field)) for field in numeric_fields)
                if not has_usable_statement:
                    if metrics.get("cashflow_status") and "cashflow_status" not in best_metrics:
                        best_metrics["cashflow_status"] = metrics["cashflow_status"]
                        best_metrics["financial_currency"] = metrics.get("financial_currency", "")
                    continue

                if not metrics.get("cashflow_status"):
                    best_metrics.pop("cashflow_status", None)
                    best_metrics.pop("financial_currency", None)
                cleaned = {k: v for k, v in metrics.items() if not (isinstance(v, float) and pd.isna(v))}
                best_metrics.update({key: value for key, value in cleaned.items() if key not in best_metrics})
                if all(k in best_metrics for k in ["cash", "operating_cashflow", "free_cashflow"]):
                    return best_metrics
        if best_metrics:
            return best_metrics
    return {}


def debug_dart_accounts(stock_code: str, year: int | None = None, limit: int = 80) -> dict:
    api_key = get_secret("DART_API_KEY")
    if not api_key:
        return {"ok": False, "reason": "DART_API_KEY missing"}

    corp_code = get_corp_code(stock_code, api_key)
    if not corp_code:
        return {"ok": False, "reason": "corp_code not found", "stock_code": stock_code}

    start_year = year or _latest_business_year()
    for target_year in range(start_year, start_year - 3, -1):
        for fs_div in ["CFS", "OFS"]:
            try:
                rows = _fetch_statement_rows(api_key, corp_code, target_year, fs_div)
            except Exception as exc:
                return {"ok": False, "reason": f"request failed: {exc}", "stock_code": stock_code}
            if not rows:
                continue
            metrics = _statement_metrics(rows)
            account_rows = []
            for row in rows:
                sj_nm = str(row.get("sj_nm", "") or "")
                account_nm = str(row.get("account_nm", "") or "")
                account_id = str(row.get("account_id", "") or "")
                if any(keyword in sj_nm + account_nm + account_id for keyword in [
                    "현금",
                    "Cash",
                    "부채",
                    "Liabilities",
                    "영업활동",
                    "OperatingActivities",
                    "유형자산",
                    "PropertyPlant",
                    "무형자산",
                    "Intangible",
                ]):
                    account_rows.append({
                        "sj_nm": sj_nm,
                        "account_id": account_id,
                        "account_nm": account_nm,
                        "amount_eok": _won_to_eok(row.get("thstrm_amount")),
                    })
                if len(account_rows) >= limit:
                    break
            return {
                "ok": True,
                "stock_code": str(stock_code).split(".")[0].zfill(6),
                "corp_code": corp_code,
                "year": target_year,
                "fs_div": fs_div,
                "metrics": {k: v for k, v in metrics.items() if not (isinstance(v, float) and pd.isna(v))},
                "accounts": account_rows,
            }
    return {"ok": False, "reason": "no statement rows", "stock_code": stock_code}
