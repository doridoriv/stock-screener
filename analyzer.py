import os
import json
import time
import random
import io
import re
import queue
import hashlib
from datetime import datetime, time as datetime_time, timedelta
import concurrent.futures
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import FinanceDataReader as fdr
import finnhub_client
import krx_client
import nxt_client
import opendart_client
import supplemental_data

from config import (
    DEFAULT_US_TICKERS,
    US_NAME_MAP,
    US_TICKER_ALIASES,
    US_MARKETCAP_CACHE_FILE,
    GRADE_RULES,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    BACKOFF_FACTOR,
    MIN_SLEEP,
    MAX_SLEEP,
    USER_AGENTS,
    CACHE_DIR,
    FIXED_TOP_N,
    US_MAX_WORKERS,
)

# ==========================================
# 1. 코어 보조 및 매크로 지표 수집
# ==========================================
def _get_safe_yfinance_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session

def download_prices_robust(yf_symbols, start_date):
    """Fetch closing prices for a list of symbols using FinanceDataReader.
    Returns a DataFrame with columns named by the original yf_symbols.
    """
    price_series = {}
    for sym in yf_symbols:
        try:
            clean_sym = sym.split('.')[0]
            df = fdr.DataReader(clean_sym, start_date)
            if df is not None and not df.empty and 'Close' in df.columns:
                price_series[sym] = df['Close']
            else:
                print(f"[WARN] No price data for {sym} via FinanceDataReader")
        except Exception as e:
            print(f"[ERROR] FinanceDataReader failed for {sym}: {e}")
        time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))
    if not price_series:
        raise RuntimeError("All price fetches failed.")
    closes = pd.concat(price_series, axis=1).sort_index()
    # Keep pre-listing periods empty. Backfilling would fabricate price history
    # for newly listed stocks and distort 200-day averages and drawdowns.
    closes = closes.ffill().dropna(how="all")
    print(f"[OK] FinanceDataReader fetched {len(closes.columns)} symbols.")
    return closes

def fetch_extended_last_price(symbol: str, fallback=np.nan, allow_extended=True) -> tuple:
    """Return the latest available price with a source label."""
    collected_at = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    if not allow_extended:
        return fallback, "daily_close", collected_at

    try:
        ticker = yf.Ticker(symbol, session=_get_safe_yfinance_session())
        info = ticker.info
        for key in ["postMarketPrice", "preMarketPrice", "regularMarketPrice", "currentPrice"]:
            val = info.get(key)
            if val is not None and pd.notna(val) and float(val) > 0:
                return float(val), key, collected_at

        try:
            fast_info = ticker.fast_info
            val = fast_info.get("last_price") if hasattr(fast_info, "get") else getattr(fast_info, "last_price", None)
            if val is not None and pd.notna(val) and float(val) > 0:
                return float(val), "fast_info.last_price", collected_at
        except Exception:
            pass
    except Exception:
        pass
    return fallback, "daily_close", collected_at


def normalize_price_source(source: str, is_kr: bool) -> str:
    source = str(source or "")
    if source == "nxt_web_latest":
        return "NXT 체결가"
    if source == "postMarketPrice":
        return "애프터마켓"
    if source == "preMarketPrice":
        return "프리마켓"
    if source in ["regularMarketPrice", "currentPrice", "fast_info.last_price"]:
        return "정규장/실시간"
    if source == "daily_close":
        return "NXT 미확인" if is_kr else "일봉 종가"
    return source or "확인 필요"

def _get_us_10y_yield():
    try:
        hist = yf.Ticker("^TNX", session=_get_safe_yfinance_session()).history(period="1d")
        return round(float(hist['Close'].iloc[-1]), 2) if not hist.empty else 4.25
    except:
        return 4.25

def fetch_us_market_cap(symbol: str) -> int:
    """Fetch market cap from yfinance safely."""
    try:
        t = yf.Ticker(symbol, session=_get_safe_yfinance_session())
        info = t.info
        return int(info.get('marketCap', 0))
    except Exception as e:
        print(f"[WARN] market cap fetch failed for {symbol}: {e}")
        return 0

# ==========================================
# 2. 로컬 캐시 및 최근 마감 거래일 날짜 연산
# ==========================================
def get_latest_market_date(market: str) -> str:
    """
    각 시장별 가장 최근 마감된 거래일의 날짜를 YYYYMMDD 형태로 반환합니다.
    - 한국 시장(코스피/코스닥): 15:30 장마감 (16:00 데이터 안정화 기준)
    - 미국 시장: 현지 시각 16:00 장마감 (한국 시각으로 대략 아침 06:30 ~ 07:00 데이터 안정화 기준)
    """
    tz_kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(tz_kst)
    
    if market in ["코스피", "코스닥", "한국(코스피)", "한국(코스닥)", "한국"]:
        current_date = now_kst.date()
        current_time = now_kst.time()
        weekday = now_kst.weekday()  # 0 = 월, ..., 6 = 일
        
        # 평일이고 16:00 이후이면 오늘 데이터 사용, 그 전이면 이전 거래일 사용
        if weekday < 5:
            if current_time >= datetime_time(16, 0):
                target_date = current_date
            else:
                days_to_subtract = 3 if weekday == 0 else 1
                target_date = current_date - timedelta(days=days_to_subtract)
        else:
            days_to_subtract = 1 if weekday == 5 else 2
            target_date = current_date - timedelta(days=days_to_subtract)
            
        return target_date.strftime("%Y%m%d")
        
    else:  # 미국
        tz_est = ZoneInfo("America/New_York")
        now_est = datetime.now(tz_est)
        
        current_date = now_est.date()
        current_time = now_est.time()
        weekday = now_est.weekday()
        
        # 미국 평일이고 16:15(EST) 이후이면 오늘 미국 날짜 사용, 그 전이면 이전 거래일 사용
        if weekday < 5:
            if current_time >= datetime_time(16, 15):
                target_date = current_date
            else:
                days_to_subtract = 3 if weekday == 0 else 1
                target_date = current_date - timedelta(days=days_to_subtract)
        else:
            days_to_subtract = 1 if weekday == 5 else 2
            target_date = current_date - timedelta(days=days_to_subtract)
            
        return target_date.strftime("%Y%m%d")

def _get_daily_cache_path(market_text: str, date_str: str) -> str:
    return os.path.join(CACHE_DIR, f"snapshot_{market_text}_{date_str}.csv")


REQUIRED_CACHE_COLUMNS = {"symbol", "name", "price", "data_date"}


def validate_cache_dataframe(
    df: pd.DataFrame,
    expected_rows: int = FIXED_TOP_N,
    require_complete_prices: bool = True,
) -> tuple[bool, list[str]]:
    """Validate a snapshot before it is served or committed."""
    reasons = []
    if df is None or df.empty:
        return False, ["empty cache"]

    missing_columns = sorted(REQUIRED_CACHE_COLUMNS - set(df.columns))
    if missing_columns:
        reasons.append(f"missing columns: {', '.join(missing_columns)}")

    if expected_rows and len(df) < expected_rows:
        reasons.append(f"row count {len(df)} < {expected_rows}")

    if "symbol" in df.columns:
        symbols = df["symbol"].fillna("").astype(str).str.strip()
        unique_symbols = symbols[symbols != ""].nunique()
        if expected_rows and unique_symbols < expected_rows:
            reasons.append(f"unique symbols {unique_symbols} < {expected_rows}")

    if "price" in df.columns:
        valid_prices = pd.to_numeric(df["price"], errors="coerce").gt(0)
        minimum_valid = len(df) if require_complete_prices else max(1, int(len(df) * 0.95))
        if int(valid_prices.sum()) < minimum_valid:
            reasons.append(f"valid prices {int(valid_prices.sum())} < {minimum_valid}")

    if "data_date" in df.columns:
        dates = df["data_date"].dropna().astype(str).str.strip()
        if dates.empty:
            reasons.append("data date missing")
        elif dates.nunique() != 1:
            reasons.append("mixed data dates")

    return not reasons, reasons


def _read_valid_cache(path: str, expected_rows: int = FIXED_TOP_N) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    # Legacy snapshots may contain a small number of unavailable prices. They
    # can still be served while every newly written snapshot is validated at
    # 100% completeness.
    valid, _ = validate_cache_dataframe(
        df,
        expected_rows=expected_rows,
        require_complete_prices=False,
    )
    return df if valid else None


def find_latest_valid_cache(market_text: str):
    """
    가장 최근 거래일의 캐시가 있으면 가져오고, 없으면 최대 8일 전 캐시까지 탐색합니다.
    """
    target_date_str = get_latest_market_date(market_text)
    file_path = _get_daily_cache_path(market_text, target_date_str)
    
    candidates = [file_path]
    # 공휴일이나 휴장일 대비 이전 8일간의 캐시 역추적
    for i in range(1, 9):
        check_date = datetime.strptime(target_date_str, "%Y%m%d") - timedelta(days=i)
        candidates.append(_get_daily_cache_path(market_text, check_date.strftime("%Y%m%d")))

    for candidate in candidates:
        if os.path.exists(candidate) and _read_valid_cache(candidate) is not None:
            return candidate
    return None

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {ticker: {"rank": i, "name": US_NAME_MAP.get(ticker, ticker), "market_cap": 0} 
            for i, ticker in enumerate(DEFAULT_US_TICKERS, 1)}

def sort_by_market_cap(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "market_cap" not in df.columns:
        return df
    out = df.copy()
    out["_market_cap_sort"] = pd.to_numeric(out["market_cap"], errors="coerce").fillna(-1)
    out = out.sort_values(by="_market_cap_sort", ascending=False).drop(columns=["_market_cap_sort"])
    out = out.reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def normalize_financial_sanity_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Quarantine clearly incompatible Korean cash-flow units in cached data."""
    if df is None or df.empty:
        return df

    out = df.copy()
    cash_fields = ["operating_cashflow", "free_cashflow", "cash", "total_debt", "net_cash"]
    for field in ["revenue", *cash_fields]:
        if field not in out.columns:
            out[field] = np.nan

    symbols = out.get("symbol", pd.Series("", index=out.index)).fillna("").astype(str).str.zfill(6)
    is_korean_symbol = symbols.str.fullmatch(r"\d{6}")
    revenue = pd.to_numeric(out["revenue"], errors="coerce").abs()
    cash_scale = pd.concat(
        [pd.to_numeric(out[field], errors="coerce").abs() for field in ["operating_cashflow", "cash", "total_debt"]],
        axis=1,
    ).max(axis=1)
    scale_mismatch = (
        is_korean_symbol
        & revenue.ge(1_000)
        & cash_scale.gt(0)
        & cash_scale.div(revenue.replace(0, np.nan)).lt(0.001)
    )

    if "cashflow_status" not in out.columns:
        out["cashflow_status"] = ""
    else:
        out["cashflow_status"] = out["cashflow_status"].fillna("").astype(str)
    out.loc[scale_mismatch, "cashflow_status"] = "통화 단위 확인 필요"
    out.loc[scale_mismatch, cash_fields] = np.nan
    return out


def market_date_from_prices(closes: pd.DataFrame) -> str | None:
    if closes is None or closes.empty:
        return None
    parsed = pd.to_datetime(pd.Index(closes.index), errors="coerce")
    parsed = parsed[~pd.isna(parsed)]
    if len(parsed) == 0:
        return None
    return pd.Timestamp(parsed.max()).strftime("%Y%m%d")


def _period_return(closes: pd.DataFrame, current_prices: pd.Series, sessions: int) -> pd.Series:
    result = pd.Series(np.nan, index=current_prices.index, dtype=float)
    if closes is None or len(closes) <= sessions:
        return result
    base = pd.to_numeric(closes.shift(sessions).iloc[-1], errors="coerce")
    current = pd.to_numeric(current_prices, errors="coerce")
    valid = base.gt(0) & current.notna()
    result.loc[valid] = ((current.loc[valid] - base.loc[valid]) / base.loc[valid] * 100).round(2)
    return result


def _stable_refresh_bucket(symbol: str, buckets: int = 5) -> int:
    digest = hashlib.sha1(str(symbol).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets

def merge_missing_fields(base: dict, supplement: dict) -> dict:
    for key, value in supplement.items():
        current = base.get(key)
        missing = (
            current is None
            or pd.isna(current)
            or str(current).strip() in ["", "-", "None", "nan", "NaN", "N/A"]
        )
        if missing:
            base[key] = value
    return base


def _is_missing_value(value) -> bool:
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() in ["", "-", "None", "none", "nan", "NaN", "N/A"]


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _normalize_yield_percent(value):
    number = _to_float_or_none(value)
    if number is None or number <= 0:
        return np.nan
    return round(number * 100, 2) if number < 0.2 else round(number, 2)


def _dividend_yield_from_info(info: dict):
    dividend_rate = _to_float_or_none(info.get("dividendRate") or info.get("trailingAnnualDividendRate"))
    price = _to_float_or_none(
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    if dividend_rate and dividend_rate > 0 and price and price > 0:
        return round((dividend_rate / price) * 100, 2)

    trailing_yield = _to_float_or_none(info.get("trailingAnnualDividendYield"))
    if trailing_yield and trailing_yield > 0:
        return round(trailing_yield * 100, 2) if trailing_yield <= 1 else round(trailing_yield, 2)

    return _normalize_yield_percent(info.get("dividendYield"))


def extract_naver_target_mean(value):
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    for text in reversed(numbers):
        try:
            number = float(text.replace(",", ""))
        except ValueError:
            continue
        if number > 0:
            return round(number, 2)
    return np.nan


def extract_naver_opinion_score(value):
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    if not numbers:
        return np.nan
    try:
        score = float(numbers[0].replace(",", ""))
    except ValueError:
        return np.nan
    return round(score, 2) if 0 < score <= 5 else np.nan


def consensus_metrics_from_yfinance_info(info: dict) -> dict:
    metrics = {}
    for source_key, target_key in [
        ("targetMeanPrice", "target_mean"),
        ("targetHighPrice", "target_high"),
        ("targetLowPrice", "target_low"),
    ]:
        value = _to_float_or_none(info.get(source_key))
        if value is not None and value > 0:
            metrics[target_key] = round(value, 2)
    recommendation_mean = _to_float_or_none(info.get("recommendationMean"))
    if recommendation_mean is not None and 1 <= recommendation_mean <= 5:
        metrics["analyst_opinion_score"] = round(6 - recommendation_mean, 2)
    opinion_count = _to_float_or_none(info.get("numberOfAnalystOpinions"))
    if opinion_count is not None and opinion_count > 0:
        metrics["analyst_opinion_count"] = int(opinion_count)
    if metrics:
        metrics["consensus_source"] = "yfinance"
    return metrics


def summarize_us_dividend_history(
    dividends: pd.Series,
    reference_year: int | None = None,
    max_years: int = 10,
) -> dict:
    if dividends is None or len(dividends) == 0:
        return {}

    values = pd.to_numeric(pd.Series(dividends), errors="coerce")
    dates = pd.to_datetime(values.index, errors="coerce")
    valid = values.notna() & values.gt(0) & ~pd.isna(dates)
    values = values.loc[valid]
    dates = dates[valid]
    if values.empty:
        return {}

    completed_year = reference_year or (datetime.now().year - 1)
    annual_regular = {}
    for year in sorted(set(dates.year)):
        if year > completed_year:
            continue
        payments = values.loc[dates.year == year]
        if payments.empty:
            continue
        median_payment = float(payments.median())
        regular_payments = payments
        if len(payments) >= 3 and median_payment > 0:
            # Exclude obvious one-off special dividends (for example COST)
            # from regular dividend growth and cut detection.
            regular_payments = payments[payments <= median_payment * 3]
        if not regular_payments.empty:
            annual_regular[int(year)] = float(regular_payments.sum())

    if not annual_regular:
        return {}

    consecutive_years = 0
    for year in range(completed_year, completed_year - max_years, -1):
        if annual_regular.get(year, 0) <= 0:
            break
        consecutive_years += 1

    result = {
        "dividend_history_years": len(annual_regular),
        "dividend_consecutive_years": consecutive_years,
        "dividend_history_source": "yfinance dividend history",
    }

    latest = annual_regular.get(completed_year)
    previous = annual_regular.get(completed_year - 1)
    if latest and previous:
        result["dividend_cut_flag"] = bool(latest < previous * 0.95)

    first = annual_regular.get(completed_year - 3)
    if latest and first:
        result["dividend_growth_3y"] = round(((latest / first) ** (1 / 3) - 1) * 100, 2)
    return result


def _needs_cashflow_boost(data: dict) -> bool:
    return any(_is_missing_value(data.get(field)) for field in ["free_cashflow", "operating_cashflow", "cash"])


def _needs_dart_boost(data: dict) -> bool:
    dart_fields = [
        "free_cashflow",
        "operating_cashflow",
        "cash",
        "dividend_yield",
        "payout_ratio",
        "dividend_per_share",
    ]
    return any(_is_missing_value(data.get(field)) for field in dart_fields)


def add_peer_comparison_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    group_col = None
    for candidate in ["sector", "industry"]:
        if candidate in out.columns and out[candidate].fillna("").astype(str).str.strip().ne("").any():
            group_col = candidate
            break
    if not group_col:
        return out

    out["_peer_group"] = out[group_col].fillna("").astype(str).str.strip()
    out.loc[out["_peer_group"] == "", "_peer_group"] = "미분류"
    for field in ["per", "pbr", "roe"]:
        if field in out.columns:
            out[field] = pd.to_numeric(out[field], errors="coerce")

    valid_per = out["per"].where(out["per"] > 0) if "per" in out.columns else pd.Series(np.nan, index=out.index)
    valid_pbr = out["pbr"].where(out["pbr"] > 0) if "pbr" in out.columns else pd.Series(np.nan, index=out.index)
    valid_roe = out["roe"] if "roe" in out.columns else pd.Series(np.nan, index=out.index)

    def leave_one_out_median(values: pd.Series) -> tuple[pd.Series, pd.Series]:
        medians = pd.Series(np.nan, index=out.index, dtype=float)
        counts = pd.Series(0, index=out.index, dtype=int)
        for _, group_indexes in out.groupby("_peer_group").groups.items():
            group_values = values.loc[group_indexes]
            for row_index in group_indexes:
                peers = group_values.drop(index=row_index, errors="ignore").dropna()
                counts.at[row_index] = len(peers)
                if len(peers) >= 3:
                    medians.at[row_index] = float(peers.median())
        return medians.round(2), counts

    out["peer_per_avg"], out["peer_per_count"] = leave_one_out_median(valid_per)
    out["peer_pbr_avg"], out["peer_pbr_count"] = leave_one_out_median(valid_pbr)
    out["peer_roe_avg"], out["peer_roe_count"] = leave_one_out_median(valid_roe)
    out["peer_group_count"] = out.groupby("_peer_group")["_peer_group"].transform("count")

    out["peer_per_gap"] = np.where(
        (out["peer_per_count"] >= 3) & (out["peer_per_avg"] > 0) & (out["per"] > 0),
        ((out["per"] - out["peer_per_avg"]) / out["peer_per_avg"] * 100).round(2),
        np.nan,
    )
    out["peer_pbr_gap"] = np.where(
        (out["peer_pbr_count"] >= 3) & (out["peer_pbr_avg"] > 0) & (out["pbr"] > 0),
        ((out["pbr"] - out["peer_pbr_avg"]) / out["peer_pbr_avg"] * 100).round(2),
        np.nan,
    )
    return out.drop(columns=["_peer_group"], errors="ignore")


def normalize_dividend_yield_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "dividend_yield" not in df.columns:
        return df
    out = df.copy()
    current = pd.to_numeric(out.get("dividend_yield"), errors="coerce")

    if "dividend_per_share" in out.columns and "price" in out.columns:
        dividend_per_share = pd.to_numeric(out["dividend_per_share"], errors="coerce")
        price = pd.to_numeric(out["price"], errors="coerce")
        calculated = (dividend_per_share / price) * 100
        calculated = calculated.where((dividend_per_share > 0) & (price > 0))
        needs_calculated = calculated.notna()
        out.loc[needs_calculated, "dividend_yield"] = calculated.loc[needs_calculated].round(2)
        current = pd.to_numeric(out.get("dividend_yield"), errors="coerce")

    unit_bug = current.gt(20) & current.le(1000)
    out.loc[unit_bug, "dividend_yield"] = (current.loc[unit_bug] / 100).round(2)
    return out


# ==========================================
# 3. 안전한 HTTP GET 요청 처리 (차단 방지 모드)
# ==========================================
def safe_requests_get(url: str) -> requests.Response:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://finance.naver.com/",
    }
    
    retries = 0
    while retries < MAX_RETRIES:
        try:
            time.sleep(random.uniform(MIN_SLEEP, MAX_SLEEP))
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return response
            elif response.status_code == 429 or response.status_code >= 500:
                raise requests.RequestException(f"Status code {response.status_code}")
        except Exception as e:
            retries += 1
            if retries == MAX_RETRIES:
                raise e
            wait_time = BACKOFF_FACTOR * (2 ** retries) + random.uniform(0.1, 0.5)
            time.sleep(wait_time)
    raise requests.RequestException("Max retries exceeded")

# ==========================================
# 4. 네이버 금융 크롤러 (한국 시장 fundamentals 수집)
# ==========================================
def fetch_kr_fundamental_naver(symbol: str) -> dict:
    clean_sym = symbol.split(".")[0]
    url = f"https://finance.naver.com/item/main.naver?code={clean_sym}"
    
    res_dict = {
        "eps_growth": np.nan,
        "hist_per_avg": np.nan,
        "foreign_supply": np.nan,
        "per": np.nan,
        "pbr": np.nan,
        "roe": np.nan,
        "debt_ratio": np.nan,
        "revenue_growth": np.nan,
        "operating_growth": np.nan,
        "eps_cagr": np.nan,
        "eps3y": "-",
        "revenue": np.nan,
        "operating_income": np.nan,
        "net_income": np.nan,
        "operating_margin": np.nan,
        "net_margin": np.nan,
        "operating_cashflow": np.nan,
        "free_cashflow": np.nan,
        "cash": np.nan,
        "total_debt": np.nan,
        "net_cash": np.nan,
        "dividend_yield": np.nan,
        "payout_ratio": np.nan,
        "dividend_per_share": np.nan,
        "dividend_total": np.nan,
        "dividend_source": "",
        "dividend_growth_3y": np.nan,
        "dividend_consecutive_years": np.nan,
        "dividend_cut_flag": "",
        "dividend_history_years": np.nan,
        "dividend_history_source": "",
        "sector": "",
        "industry": "",
        "target_mean": np.nan,
        "target_high": np.nan,
        "target_low": np.nan,
        "target_upside": np.nan,
        "analyst_opinion_score": np.nan,
        "analyst_opinion_count": np.nan,
        "consensus_source": "",
    }
    
    try:
        response = safe_requests_get(url)
        tables = pd.read_html(io.StringIO(response.text))
        
        for table in tables:
            txt = table.to_string()

            if "투자의견" in txt and "목표주가" in txt:
                for _, target_row in table.iterrows():
                    label = str(target_row.iloc[0]) if len(target_row) else ""
                    if "목표주가" not in label:
                        continue
                    raw_value = target_row.iloc[1] if len(target_row) > 1 else ""
                    target_mean = extract_naver_target_mean(raw_value)
                    opinion_score = extract_naver_opinion_score(raw_value)
                    if pd.notna(target_mean):
                        res_dict["target_mean"] = target_mean
                        res_dict["consensus_source"] = "Naver/FnGuide"
                    if pd.notna(opinion_score):
                        res_dict["analyst_opinion_score"] = opinion_score
                        res_dict["consensus_source"] = "Naver/FnGuide"
                    break
            
            # 1. 기업 실적 분석 테이블 (Table 4)
            if '주요재무정보' in txt and '매출액' in txt:
                first_col = table.columns[0]
                table = table.set_index(first_col)
                
                eps_row = next((table.loc[idx] for idx in table.index if 'EPS' in str(idx)), None)
                per_row = next((table.loc[idx] for idx in table.index if 'PER' in str(idx)), None)
                roe_row = next((table.loc[idx] for idx in table.index if 'ROE' in str(idx)), None)
                debt_row = next((table.loc[idx] for idx in table.index if '부채비율' in str(idx)), None)
                rev_row = next((table.loc[idx] for idx in table.index if '매출액' in str(idx)), None)
                op_row = next((table.loc[idx] for idx in table.index if '영업이익' in str(idx) and '영업이익률' not in str(idx)), None)
                net_row = next((table.loc[idx] for idx in table.index if '당기순이익' in str(idx)), None)

                # 연간 실적 컬럼만 필터링하여 중복 컬럼명(2025.12 연간/분기 중복 등) 충돌 방지
                annual_cols = [col for col in table.columns if isinstance(col, tuple) and col[0] == '최근 연간 실적']
                years = [col for col in annual_cols if col[1].endswith('.12') and not col[1].endswith('(E)')]
                years.sort(key=lambda x: x[1])
                
                # EPS 성장률 & trend & CAGR 연산
                if eps_row is not None:
                    valid_eps = {}
                    for yr in years:
                        try:
                            val = float(str(eps_row[yr]).replace(',', ''))
                            if not np.isnan(val) and val > 0:
                                valid_eps[yr] = val
                        except: pass
                    
                    if len(valid_eps) >= 2:
                        sorted_years = sorted(valid_eps.keys())
                        latest_yr = sorted_years[-1]
                        prev_yr = sorted_years[-2]
                        latest_eps = valid_eps[latest_yr]
                        prev_eps = valid_eps[prev_yr]
                        res_dict["eps_growth"] = round(((latest_eps - prev_eps) / prev_eps) * 100, 2)
                        
                        trend_vals = [str(int(valid_eps[y])) for y in sorted_years[-3:]]
                        res_dict["eps3y"] = " -> ".join(trend_vals)
                        
                        if len(sorted_years) >= 3:
                            first_yr = sorted_years[-3]
                            first_eps = valid_eps[first_yr]
                            if first_eps > 0:
                                res_dict["eps_cagr"] = round(((latest_eps / first_eps) ** (1/2) - 1) * 100, 2)
                
                # 과거 평균 PER 연산
                if per_row is not None:
                    per_vals = []
                    for yr in years:
                        try:
                            val = float(str(per_row[yr]).replace(',', ''))
                            if not np.isnan(val) and val > 0:
                                per_vals.append(val)
                        except: pass
                    if per_vals:
                        res_dict["hist_per_avg"] = round(np.mean(per_vals), 2)
                        
                # ROE 연산
                if roe_row is not None:
                    for yr in reversed(years):
                        try:
                            val = float(str(roe_row[yr]).replace(',', ''))
                            if not np.isnan(val):
                                res_dict["roe"] = round(val, 2)
                                break
                        except: pass
                        
                # 부채비율 연산
                if debt_row is not None:
                    for yr in reversed(years):
                        try:
                            val = float(str(debt_row[yr]).replace(',', ''))
                            if not np.isnan(val):
                                res_dict["debt_ratio"] = round(val, 2)
                                break
                        except: pass
                
                # 매출 & 영업이익 성장률 연산
                if rev_row is not None and len(years) >= 2:
                    try:
                        latest_rev = float(str(rev_row[years[-1]]).replace(',', ''))
                        prev_rev = float(str(rev_row[years[-2]]).replace(',', ''))
                        res_dict["revenue"] = round(latest_rev, 2)
                        if prev_rev > 0:
                            res_dict["revenue_growth"] = round(((latest_rev - prev_rev) / prev_rev) * 100, 2)
                    except: pass
                    
                if op_row is not None and len(years) >= 2:
                    try:
                        latest_op = float(str(op_row[years[-1]]).replace(',', ''))
                        prev_op = float(str(op_row[years[-2]]).replace(',', ''))
                        res_dict["operating_income"] = round(latest_op, 2)
                        if res_dict["revenue"] and res_dict["revenue"] > 0:
                            res_dict["operating_margin"] = round((latest_op / res_dict["revenue"]) * 100, 2)
                        if prev_op > 0:
                            res_dict["operating_growth"] = round(((latest_op - prev_op) / prev_op) * 100, 2)
                    except: pass

                if net_row is not None and len(years) >= 1:
                    try:
                        latest_net = float(str(net_row[years[-1]]).replace(',', ''))
                        res_dict["net_income"] = round(latest_net, 2)
                        if res_dict["revenue"] and res_dict["revenue"] > 0:
                            res_dict["net_margin"] = round((latest_net / res_dict["revenue"]) * 100, 2)
                    except: pass

            # 2. 외국인 지분 정보 테이블 (Table 5)
            if '외국인비율(%)' in txt:
                for r_idx, row in table.iterrows():
                    row_name = str(row.iloc[0])
                    if '외국인비율' in row_name:
                        try:
                            val = float(str(row.iloc[1]).replace('%', '').replace(',', ''))
                            res_dict["foreign_supply"] = round(val, 2)
                        except: pass
                        break
                        
            # 3. 우측 시세 정보 요약 테이블 (Table 9) - PER / PBR 실시간 보정용
            if 'PERlEPS' in txt or 'PBRlBPS' in txt:
                for r_idx, row in table.iterrows():
                    val0 = str(row.iloc[0])
                    val1 = str(row.iloc[1])
                    if 'PERlEPS' in val0:
                        try:
                            per_str = val1.split('배')[0].strip()
                            res_dict["per"] = round(float(per_str), 2)
                        except: pass
                    elif 'PBRlBPS' in val0:
                        try:
                            pbr_str = val1.split('배')[0].strip()
                            res_dict["pbr"] = round(float(pbr_str), 2)
                        except: pass
                        
    except Exception as e:
        print(f"Error parsing Naver data for {symbol}: {e}")
        
    return res_dict

# ==========================================
# 5. yfinance 데이터 수집기 (미국 시장 fundamentals 연산)
# ==========================================
def fetch_us_fundamental_yfinance(symbol: str) -> dict:
    res_dict = {
        "eps_growth": np.nan,
        "hist_per_avg": np.nan,
        "foreign_supply": np.nan,
        "per": np.nan,
        "pbr": np.nan,
        "roe": np.nan,
        "debt_ratio": np.nan,
        "revenue_growth": np.nan,
        "operating_growth": np.nan,
        "eps_cagr": np.nan,
        "eps3y": "-",
        "revenue": np.nan,
        "operating_income": np.nan,
        "net_income": np.nan,
        "operating_margin": np.nan,
        "net_margin": np.nan,
        "operating_cashflow": np.nan,
        "free_cashflow": np.nan,
        "cash": np.nan,
        "total_debt": np.nan,
        "net_cash": np.nan,
        "dividend_yield": np.nan,
        "payout_ratio": np.nan,
        "dividend_per_share": np.nan,
        "dividend_total": np.nan,
        "dividend_source": "",
        "dividend_growth_3y": np.nan,
        "dividend_consecutive_years": np.nan,
        "dividend_cut_flag": "",
        "dividend_history_years": np.nan,
        "dividend_history_source": "",
        "sector": "",
        "industry": "",
        "analyst_buy_ratio": np.nan,
        "analyst_opinion_score": np.nan,
        "analyst_opinion_count": np.nan,
        "consensus_revision": np.nan,
        "target_mean": np.nan,
        "target_high": np.nan,
        "target_low": np.nan,
        "target_upside": np.nan,
        "earnings_surprise_pct": np.nan,
        "finnhub_source": "",
        "consensus_source": "",
    }

    try:
        time.sleep(random.uniform(0.3, 0.8))
        t = yf.Ticker(symbol, session=_get_safe_yfinance_session())
        info = t.info

        info_eps_growth = info.get("earningsGrowth")
        if info_eps_growth is not None:
            res_dict["eps_growth"] = round(float(info_eps_growth) * 100, 2)
            
        res_dict["per"] = info.get("trailingPE", np.nan)
        res_dict["pbr"] = info.get("priceToBook", np.nan)
        res_dict["sector"] = info.get("sector", "")
        res_dict["industry"] = info.get("industry", "")
        
        roe_val = info.get("returnOnEquity")
        if roe_val is not None:
            res_dict["roe"] = round(float(roe_val) * 100, 2)
            
        res_dict["debt_ratio"] = info.get("debtToEquity", np.nan)
        res_dict["foreign_supply"] = round((info.get("heldPercentInstitutions", 0) or 0) * 100, 2)
        
        info_rev_growth = info.get("revenueGrowth")
        if info_rev_growth is not None:
            res_dict["revenue_growth"] = round(float(info_rev_growth) * 100, 2)

        dividend_yield = _dividend_yield_from_info(info)
        if pd.notna(dividend_yield):
            res_dict["dividend_yield"] = dividend_yield
            res_dict["dividend_source"] = "yfinance"
        payout_ratio = info.get("payoutRatio")
        if payout_ratio is not None:
            res_dict["payout_ratio"] = round(float(payout_ratio) * 100, 2)
            res_dict["dividend_source"] = "yfinance"
        dividend_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
        if dividend_rate is not None:
            res_dict["dividend_per_share"] = round(float(dividend_rate), 2)
            res_dict["dividend_source"] = "yfinance"

        res_dict = merge_missing_fields(res_dict, consensus_metrics_from_yfinance_info(info))

        try:
            dividend_history = t.history(period="10y", actions=True, auto_adjust=False)
            if dividend_history is not None and "Dividends" in dividend_history.columns:
                history_metrics = summarize_us_dividend_history(dividend_history["Dividends"])
                res_dict = merge_missing_fields(res_dict, history_metrics)
        except Exception:
            pass

        # 연간 재무제표를 바탕으로 과거 평균 PER 및 EPS 트렌드 산출
        fin = t.financials
        
        # EPS 성장률 Fallback (info에서 수집 실패한 경우 연간 EPS 데이터 기반 연산)
        if "Diluted EPS" in fin.index:
            eps_series = fin.loc["Diluted EPS"].dropna()
            if pd.isna(res_dict["eps_growth"]) and len(eps_series) >= 2:
                latest_eps = eps_series.iloc[0]
                prev_eps = eps_series.iloc[1]
                if prev_eps != 0:
                    res_dict["eps_growth"] = round(((latest_eps - prev_eps) / abs(prev_eps)) * 100, 2)
            
            # 과거 평균 PER 산출용 history 가격 연산
            dates = eps_series.index
            dates_naive = pd.to_datetime(dates).tz_localize(None)

            # 각 재무결산일 즈음의 주가 다운로드
            history = t.history(start=min(dates_naive) - pd.Timedelta(days=10), end=max(dates_naive) + pd.Timedelta(days=10))
            history.index = history.index.tz_localize(None)

            pe_history = []
            eps_vals = {}
            for dt, eps in eps_series.items():
                dt_naive = pd.to_datetime(dt).tz_localize(None)
                if pd.isna(eps) or eps <= 0:
                    continue
                eps_vals[dt_naive.year] = eps
                try:
                    closest_idx = history.index.get_indexer([dt_naive], method='nearest')[0]
                    price = history.iloc[closest_idx]['Close']
                    pe_history.append(price / eps)
                except Exception:
                    pass

            if pe_history:
                res_dict["hist_per_avg"] = round(np.mean(pe_history), 2)

            if len(eps_vals) >= 2:
                sorted_years = sorted(eps_vals.keys())
                trend_vals = [str(round(eps_vals[y], 2)) for y in sorted_years[-3:]]
                res_dict["eps3y"] = " -> ".join(trend_vals)
                
                latest_eps = eps_vals[sorted_years[-1]]
                if len(sorted_years) >= 3:
                    first_eps = eps_vals[sorted_years[-3]]
                    if first_eps > 0:
                        res_dict["eps_cagr"] = round(((latest_eps / first_eps) ** (1/2) - 1) * 100, 2)

        # 영업이익 성장률 연산
        if "Operating Income" in fin.index:
            op_series = fin.loc["Operating Income"].dropna()
            if len(op_series) >= 2:
                latest_op = op_series.iloc[0]
                prev_op = op_series.iloc[1]
                res_dict["operating_income"] = round(float(latest_op), 2)
                if prev_op > 0:
                    res_dict["operating_growth"] = round(((latest_op - prev_op) / prev_op) * 100, 2)

        # 매출액 성장률 Fallback
        if pd.isna(res_dict["revenue_growth"]) and "Total Revenue" in fin.index:
            rev_series = fin.loc["Total Revenue"].dropna()
            if len(rev_series) >= 2:
                latest_rev = rev_series.iloc[0]
                prev_rev = rev_series.iloc[1]
                res_dict["revenue"] = round(float(latest_rev), 2)
                if prev_rev > 0:
                    res_dict["revenue_growth"] = round(((latest_rev - prev_rev) / prev_rev) * 100, 2)
        elif "Total Revenue" in fin.index:
            rev_series = fin.loc["Total Revenue"].dropna()
            if len(rev_series) >= 1:
                res_dict["revenue"] = round(float(rev_series.iloc[0]), 2)

        if "Net Income" in fin.index:
            net_series = fin.loc["Net Income"].dropna()
            if len(net_series) >= 1:
                res_dict["net_income"] = round(float(net_series.iloc[0]), 2)

        if res_dict["revenue"] and res_dict["revenue"] > 0:
            if pd.notna(res_dict["operating_income"]):
                res_dict["operating_margin"] = round((res_dict["operating_income"] / res_dict["revenue"]) * 100, 2)
            if pd.notna(res_dict["net_income"]):
                res_dict["net_margin"] = round((res_dict["net_income"] / res_dict["revenue"]) * 100, 2)

        cashflow = t.cashflow
        if cashflow is not None and not cashflow.empty:
            if "Operating Cash Flow" in cashflow.index:
                ocf_series = cashflow.loc["Operating Cash Flow"].dropna()
                if len(ocf_series) >= 1:
                    res_dict["operating_cashflow"] = round(float(ocf_series.iloc[0]), 2)
            if "Free Cash Flow" in cashflow.index:
                fcf_series = cashflow.loc["Free Cash Flow"].dropna()
                if len(fcf_series) >= 1:
                    res_dict["free_cashflow"] = round(float(fcf_series.iloc[0]), 2)
            elif "Capital Expenditure" in cashflow.index and pd.notna(res_dict["operating_cashflow"]):
                capex_series = cashflow.loc["Capital Expenditure"].dropna()
                if len(capex_series) >= 1:
                    res_dict["free_cashflow"] = round(float(res_dict["operating_cashflow"]) + float(capex_series.iloc[0]), 2)

        balance = t.balance_sheet
        if balance is not None and not balance.empty:
            for cash_key in ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]:
                if cash_key in balance.index:
                    cash_series = balance.loc[cash_key].dropna()
                    if len(cash_series) >= 1:
                        res_dict["cash"] = round(float(cash_series.iloc[0]), 2)
                        break
            if "Total Debt" in balance.index:
                debt_series = balance.loc["Total Debt"].dropna()
                if len(debt_series) >= 1:
                    res_dict["total_debt"] = round(float(debt_series.iloc[0]), 2)
        if pd.notna(res_dict["cash"]) and pd.notna(res_dict["total_debt"]):
            res_dict["net_cash"] = round(float(res_dict["cash"]) - float(res_dict["total_debt"]), 2)

        finnhub_metrics = finnhub_client.fetch_finnhub_metrics(symbol)
        res_dict = merge_missing_fields(res_dict, finnhub_metrics)
                        
    except Exception as e:
        print(f"Error fetching yfinance for {symbol}: {e}")
        
    return res_dict

# ==========================================
# 6. S&P500 기반 동적 미국 시가총액 상위 100선 추출
# ==========================================
def normalize_us_ticker(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    return US_TICKER_ALIASES.get(value, value)


def _is_valid_us_ticker(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}", str(symbol or "")))


def fetch_us_top100_tickers(top_n=100) -> list:
    """
    미국 시가총액 상위 100선 추출:
    매번 500개 종목을 조회하여 야후 파이낸스 차단을 유도하지 않고,
    로컬 캐시파일(us_marketcap_cache.json)이 있으면 이를 읽고, 
    없으면 config.py의 DEFAULT_US_TICKERS 목록을 기반으로 즉시 반환합니다.
    """
    candidates = {}

    def add_candidate(symbol, name=None, market_cap=0):
        normalized = normalize_us_ticker(symbol)
        if not _is_valid_us_ticker(normalized):
            return
        try:
            cap_val = float(market_cap or 0)
        except (TypeError, ValueError):
            cap_val = 0
        if cap_val > 1_000_000:
            cap_val = round(cap_val / 1_000_000_000, 2)

        display_name = str(name or "").strip()
        if not display_name or display_name in {str(symbol), normalized}:
            display_name = US_NAME_MAP.get(normalized, normalized)

        existing = candidates.get(normalized)
        if existing is None:
            candidates[normalized] = {
                "yf_symbol": normalized,
                "symbol": normalized,
                "name": display_name,
                "market_cap": cap_val,
            }
            return
        if cap_val > float(existing.get("market_cap") or 0):
            existing["market_cap"] = cap_val
        if existing.get("name") in {"", existing["symbol"]} and display_name != normalized:
            existing["name"] = display_name

    try:
        cache_data = load_us_market_cap_cache()
        if isinstance(cache_data, dict):
            sorted_items = sorted(
                cache_data.items(),
                key=lambda item: float((item[1] or {}).get("market_cap", 0) or 0),
                reverse=True,
            )
            for sym, info in sorted_items:
                info = info or {}
                add_candidate(sym, info.get("name"), info.get("market_cap", 0))
        elif isinstance(cache_data, list):
            for item in cache_data:
                item = item or {}
                symbol = item.get("symbol", item.get("yf_symbol"))
                add_candidate(symbol, item.get("name"), item.get("market_cap", 0))
    except Exception as e:
        print("로컬 미국 시총 캐시 읽기 오류, 기본 목록 대체:", e)

    for symbol in DEFAULT_US_TICKERS:
        add_candidate(symbol, US_NAME_MAP.get(normalize_us_ticker(symbol)), 0)
        if len(candidates) >= top_n:
            break

    tickers_info = list(candidates.values())[:top_n]
    if len(tickers_info) < top_n:
        raise RuntimeError(f"US universe has only {len(tickers_info)} unique tickers; expected {top_n}.")
    return tickers_info

# ==========================================
# 7. [핵심] Pandas & NumPy 벡터화 스크리닝 엔진
# ==========================================
def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data, force_scrape=False, save_cache=True):
    try:
        try:
            top_n = int(top_n)
        except (TypeError, ValueError):
            top_n = FIXED_TOP_N
        top_n = max(1, min(top_n, FIXED_TOP_N))
        market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
        
        # 1. 최근 마감된 날짜 캐시 확인
        target_date_str = get_latest_market_date(market_text)
        cache_file = _get_daily_cache_path(market_text, target_date_str)
        
        if not force_scrape and os.path.exists(cache_file):
            df_cached = _read_valid_cache(cache_file, expected_rows=top_n)
            if df_cached is not None:
                df_cached = normalize_dividend_yield_metrics(df_cached)
                df_cached = normalize_financial_sanity_metrics(df_cached)
                df_cached = sort_by_market_cap(df_cached).head(top_n)
                app_queue.put({"type": "data", "data": df_cached.to_dict(orient='records')})
                app_queue.put({"type": "done", "text": f"[OK] [{market_text}] {target_date_str} 캐시 데이터 로드 완료!"})
                return


        # 2. 명단 추출
        app_queue.put({"type": "progress", "value": 10, "text": "시총 명단 로드 중..."})
        tickers_info = []
        kr_nxt_prices = {}
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"
            krx_base_info = krx_client.fetch_base_info_map(market_type)
            try:
                kr_nxt_prices = nxt_client.fetch_nxt_latest_prices()
            except Exception as e:
                print(f"[WARN] NXT latest price fetch failed for Korean market; using daily close fallback: {e}")
            if not kr_nxt_prices:
                print("[WARN] NXT latest price data is empty; using daily close fallback for Korean screening.")

            df_kr = fdr.StockListing(market_type).dropna(subset=["Marcap"]).copy()
            df_kr["Code"] = df_kr["Code"].astype(str).str.zfill(6)
            df_kr = df_kr.sort_values(by="Marcap", ascending=False).head(top_n)
            if len(df_kr) < top_n:
                raise RuntimeError(f"{market_type} universe has only {len(df_kr)} rows; expected {top_n}.")
            for idx, r in df_kr.iterrows():
                code = str(r["Code"]).zfill(6)
                krx_info = krx_base_info.get(code, {})
                tickers_info.append({
                    "yf_symbol": f"{code}.KQ" if market_type == "KOSDAQ" else f"{code}.KS", 
                    "symbol": code, 
                    "name": r["Name"], 
                    "market_cap": int(r["Marcap"]/100000000),
                    "sector": krx_info.get("sector") or r.get("Sector") or r.get("Industry") or "",
                    "industry": krx_info.get("industry") or r.get("Industry") or krx_info.get("sector") or "",
                    "listing_department": krx_info.get("listing_department", ""),
                    "products": krx_info.get("products", ""),
                    "krx_market": krx_info.get("krx_market", ""),
                    "security_group": krx_info.get("security_group", ""),
                    "krx_source": krx_info.get("krx_source", "")
                })
        else:
            # Pull a small reserve list so unavailable or retired symbols can
            # be replaced before the expensive fundamentals stage begins.
            tickers_info = fetch_us_top100_tickers(top_n + 20)
        
        base_df = pd.DataFrame(tickers_info)
        yf_symbols = base_df['yf_symbol'].tolist()

        # 3. YF 주가 일괄 다운로드 및 행렬 연산
        app_queue.put({"type": "progress", "value": 30, "text": "주가 정보 연산 중..."})
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        closes = download_prices_robust(yf_symbols, start_date)

        if market_text == "미국":
            latest_prices = pd.to_numeric(closes.iloc[-1], errors="coerce")
            valid_symbols = [
                symbol
                for symbol in yf_symbols
                if symbol in latest_prices.index and pd.notna(latest_prices.get(symbol)) and latest_prices.get(symbol) > 0
            ]
            if len(valid_symbols) < top_n:
                raise RuntimeError(
                    f"US universe has only {len(valid_symbols)} symbols with valid prices; expected {top_n}."
                )
            valid_symbols = valid_symbols[:top_n]
            base_df = base_df[base_df["yf_symbol"].isin(valid_symbols)].copy()
            base_df["_candidate_order"] = base_df["yf_symbol"].map(
                {symbol: index for index, symbol in enumerate(valid_symbols)}
            )
            base_df = (
                base_df.sort_values("_candidate_order")
                .drop(columns="_candidate_order")
                .reset_index(drop=True)
            )
            yf_symbols = valid_symbols
            closes = closes.reindex(columns=yf_symbols)

        actual_market_date = market_date_from_prices(closes)
        if actual_market_date:
            target_date_str = actual_market_date
            cache_file = _get_daily_cache_path(market_text, target_date_str)

        # On exchange holidays the calendar-derived date can be newer than the
        # last real close. Reuse that trading day's validated cache instead of
        # publishing a duplicate snapshot under a false date.
        if not force_scrape and os.path.exists(cache_file):
            df_cached = _read_valid_cache(cache_file, expected_rows=top_n)
            if df_cached is not None:
                df_cached = normalize_dividend_yield_metrics(df_cached)
                df_cached = normalize_financial_sanity_metrics(df_cached)
                df_cached = sort_by_market_cap(df_cached).head(top_n)
                app_queue.put({"type": "data", "data": df_cached.to_dict(orient="records")})
                app_queue.put({"type": "done", "text": f"[OK] [{market_text}] {target_date_str} 실제 거래일 캐시 재사용"})
                return

        current_prices = closes.iloc[-1].copy()
        is_kr_market = market in ["한국(코스피)", "한국(코스닥)", "한국"]
        price_sources = pd.Series("daily_close", index=current_prices.index)
        price_times = pd.Series(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"), index=current_prices.index)
        after_market_prices = pd.Series(np.nan, index=current_prices.index)
        after_market_change_pct = pd.Series(np.nan, index=current_prices.index)
        if is_kr_market:
            nxt_prices = kr_nxt_prices
            if not nxt_prices:
                try:
                    nxt_prices = nxt_client.fetch_nxt_latest_prices()
                except Exception as e:
                    print(f"[WARN] NXT latest price retry failed; keeping daily close prices: {e}")

            for sym in yf_symbols:
                clean_sym = str(sym).split(".")[0].zfill(6)
                nxt_price = nxt_prices.get(clean_sym)
                if not nxt_price:
                    continue
                latest_price = nxt_price.get("price")
                if pd.notna(latest_price):
                    current_prices.loc[sym] = latest_price
                    price_sources.loc[sym] = nxt_price.get("source", "nxt_web_latest")
                    price_times.loc[sym] = nxt_price.get("time", price_times.loc[sym])
        else:
            for sym in yf_symbols:
                extended_price, price_source, price_time = fetch_extended_last_price(
                    sym,
                    fallback=current_prices.get(sym, np.nan),
                    allow_extended=True,
                )
                if price_source in ["postMarketPrice", "preMarketPrice"] and pd.notna(extended_price):
                    after_market_prices.loc[sym] = extended_price
                    regular_close = current_prices.get(sym, np.nan)
                    if pd.notna(regular_close) and regular_close:
                        after_market_change_pct.loc[sym] = ((extended_price - regular_close) / regular_close) * 100
                    price_sources.loc[sym] = "daily_close"
                    price_times.loc[sym] = price_time

        price_basis = price_sources.apply(lambda source: normalize_price_source(source, is_kr_market))

        ma200 = closes.rolling(window=200).mean().iloc[-1]
        diff_val = ((current_prices - ma200) / ma200) * 100
        peak = closes.max()
        peak_diff = ((current_prices - peak) / peak) * 100
        return_20d = _period_return(closes, current_prices, 20)
        return_60d = _period_return(closes, current_prices, 60)

        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).iloc[-1].fillna(50.0)

        tech_df = pd.DataFrame({
            'price': current_prices, 
            'ma200': ma200, 
            'diff': diff_val, 
            'peak': peak, 
            'peak_diff': peak_diff, 
            'rsi': rsi,
            'return_20d': return_20d,
            'return_60d': return_60d,
            'price_source': price_sources,
            'price_basis': price_basis,
            'price_time': price_times,
            'after_market_price': after_market_prices,
            'after_market_change_pct': after_market_change_pct
        }).reset_index()
        
        if 'Ticker' in tech_df.columns:
            tech_df = tech_df.rename(columns={'Ticker': 'yf_symbol'})
        else:
            tech_df = tech_df.rename(columns={'index': 'yf_symbol'})

        # 4. 멀티스레드 재무 데이터 안전 수집
        app_queue.put({"type": "progress", "value": 50, "text": "재무제표 정밀 수집 가동 (차단 방지 모드)..."})
        fund_rows = []
        us_10y = _get_us_10y_yield()
        
        # [패치] 이전 캐시 데이터 로드 (yfinance 429 차단 대비 하이브리드 캐시 복원용)
        prev_cache_file = find_latest_valid_cache(market_text)
        prev_fund_map = {}
        if prev_cache_file and os.path.exists(prev_cache_file):
            try:
                prev_df = pd.read_csv(prev_cache_file)
                key_col = 'yf_symbol' if 'yf_symbol' in prev_df.columns else 'symbol'
                for _, row in prev_df.iterrows():
                    sym = row[key_col]
                    fund_fields = ["eps_growth", "hist_per_avg", "foreign_supply", "per", "pbr", "roe", "debt_ratio", "revenue_growth", "operating_growth", "peg", "eps3y", "cagr", "revenue", "operating_income", "net_income", "operating_margin", "net_margin", "operating_cashflow", "free_cashflow", "cash", "total_debt", "net_cash", "cashflow_status", "financial_currency", "fundamental_refreshed_at", "dart_year", "dart_fs_div", "dart_report_code", "dart_source", "dividend_yield", "payout_ratio", "dividend_per_share", "dividend_total", "dividend_source", "dividend_year", "dividend_report_code", "dividend_growth_3y", "dividend_consecutive_years", "dividend_cut_flag", "dividend_history_years", "dividend_history_source", "sector", "industry", "peer_per_avg", "peer_pbr_avg", "peer_roe_avg", "peer_group_count", "peer_per_count", "peer_pbr_count", "peer_roe_count", "peer_per_gap", "peer_pbr_gap", "analyst_buy_ratio", "analyst_opinion_score", "analyst_opinion_count", "consensus_revision", "target_mean", "target_high", "target_low", "target_upside", "earnings_surprise_pct", "finnhub_source", "consensus_source"]
                    data_dict = {}
                    for f in fund_fields:
                        val = row.get(f)
                        if pd.notna(val) and val != "-" and str(val).strip() != "None" and str(val).strip() != "":
                            data_dict[f] = val
                    if data_dict:
                        prev_fund_map[sym] = data_dict
            except Exception as e:
                print(f"[WARN] Failed to load previous cache for fallback: {e}")
        
        refresh_buckets = 5
        refresh_bucket = datetime.strptime(target_date_str, "%Y%m%d").date().toordinal() % refresh_buckets

        def process_fundamental(sym):
            if stop_requested_func():
                return None
            
            # force_scrape가 아니며 이전 캐시에 6개 이상 채워진 데이터가 있는 경우 스킵(차단 원천 우회)
            use_cached = False
            refresh_due = _stable_refresh_bucket(sym, refresh_buckets) == refresh_bucket
            if not force_scrape and not refresh_due and sym in prev_fund_map and len(prev_fund_map[sym]) >= 6:
                use_cached = True
                
            if use_cached:
                data = {
                    "eps_growth": np.nan, "hist_per_avg": np.nan, "foreign_supply": np.nan,
                    "per": np.nan, "pbr": np.nan, "roe": np.nan, "debt_ratio": np.nan,
                    "revenue_growth": np.nan, "operating_growth": np.nan, "eps_cagr": np.nan,
                    "eps3y": "-", "revenue": np.nan, "operating_income": np.nan, "net_income": np.nan,
                    "operating_margin": np.nan, "net_margin": np.nan, "operating_cashflow": np.nan,
                    "free_cashflow": np.nan, "cash": np.nan, "total_debt": np.nan, "net_cash": np.nan,
                    "dividend_yield": np.nan, "payout_ratio": np.nan, "dividend_per_share": np.nan,
                    "dividend_total": np.nan, "dividend_source": "", "dividend_growth_3y": np.nan,
                    "dividend_consecutive_years": np.nan, "dividend_cut_flag": "",
                    "dividend_history_years": np.nan, "dividend_history_source": "", "sector": "",
                    "industry": "", "analyst_buy_ratio": np.nan, "analyst_opinion_score": np.nan,
                    "analyst_opinion_count": np.nan, "consensus_revision": np.nan,
                    "target_mean": np.nan, "target_high": np.nan, "target_low": np.nan,
                    "target_upside": np.nan, "earnings_surprise_pct": np.nan, "finnhub_source": "",
                    "consensus_source": "",
                    "cashflow_status": "", "financial_currency": "", "fundamental_refreshed_at": "",
                    "dart_year": np.nan, "dart_fs_div": "", "dart_report_code": "", "dart_source": ""
                }
                data.update(prev_fund_map[sym])
                if 'cagr' in prev_fund_map[sym] and pd.notna(prev_fund_map[sym]['cagr']):
                    data['eps_cagr'] = prev_fund_map[sym]['cagr']
                if market in ["한국(코스피)", "한국(코스닥)", "한국"] and _needs_dart_boost(data):
                    data = merge_missing_fields(data, opendart_client.fetch_dart_metrics(sym))
                data['yf_symbol'] = sym
                return data
                
            # 수집 시도
            if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                data = fetch_kr_fundamental_naver(sym)
                data = merge_missing_fields(data, opendart_client.fetch_dart_metrics(sym))
            else:
                data = fetch_us_fundamental_yfinance(sym)

            data["fundamental_refreshed_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
                
            # 수집 실패 시 이전 캐시로 필드별 개별 보완
            if sym in prev_fund_map:
                for k, v in prev_fund_map[sym].items():
                    val = data.get(k)
                    if pd.isna(val) or val == "-" or str(val).strip() == "None" or str(val).strip() == "":
                        data[k] = v
                if (pd.isna(data.get('eps_cagr')) or data.get('eps_cagr') == "") and 'cagr' in prev_fund_map[sym] and pd.notna(prev_fund_map[sym]['cagr']):
                    data['eps_cagr'] = prev_fund_map[sym]['cagr']
            
            data['yf_symbol'] = sym
            return data
            
        # 미국 시장 워커 수를 config 설정에 따르게 함
        num_workers = US_MAX_WORKERS if market_text == "미국" else 5
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(process_fundamental, sym) for sym in yf_symbols]
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                res = future.result()
                if res is not None:
                    fund_rows.append(res)
                progress_val = 50 + int((i / len(yf_symbols)) * 30)
                app_queue.put({
                    "type": "progress", 
                    "value": progress_val, 
                    "text": f"재무 데이터 수집 및 안전 검증 중... ({i}/{len(yf_symbols)})"
                })
        
        fund_df = pd.DataFrame(fund_rows)

        # 5. 데이터 병합 (Merge)
        df = pd.merge(base_df, tech_df, on='yf_symbol', how='left')
        df = pd.merge(df, fund_df, on='yf_symbol', how='left')
        for field in ["sector", "industry"]:
            left_col = f"{field}_x"
            right_col = f"{field}_y"
            if left_col in df.columns or right_col in df.columns:
                left = df[left_col] if left_col in df.columns else ""
                right = df[right_col] if right_col in df.columns else ""
                df[field] = left.where(left.fillna("").astype(str).str.strip() != "", right)
                df = df.drop(columns=[left_col, right_col], errors="ignore")
        df = supplemental_data.merge_supplemental_metrics(df, market_text)
        df = normalize_dividend_yield_metrics(df)
        df = normalize_financial_sanity_metrics(df)
        df = add_peer_comparison_metrics(df)
        
        app_queue.put({"type": "progress", "value": 85, "text": "가치 및 성장성 스코어링 모형 구동..."})

        # 지표 추가 바인딩
        df['data_date'] = datetime.strptime(target_date_str, "%Y%m%d").strftime("%Y-%m-%d")
        df['us_10y_bond'] = us_10y
        df['peg'] = np.where((df['per'] > 0) & (df['eps_growth'] > 0), round(df['per'] / df['eps_growth'], 2), np.nan)
        df['cagr'] = df['eps_cagr']
        if "target_mean" in df.columns:
            target_mean = pd.to_numeric(df["target_mean"], errors="coerce")
            price = pd.to_numeric(df["price"], errors="coerce")
            df["target_upside"] = np.where((target_mean > 0) & (price > 0), ((target_mean - price) / price * 100).round(2), np.nan)

        # 스코어링 연산
        df['score_per'] = np.select([df['per']<=0, df['per']<=8, df['per']<=12, df['per']<=18, df['per']<=25], [0, 15, 12, 8, 4], default=0)
        df['score_pbr'] = np.select([df['pbr']<=0, df['pbr']<=0.8, df['pbr']<=1.2, df['pbr']<=1.8, df['pbr']<=3.0], [0, 10, 8, 6, 3], default=0)
        df['score_roe'] = np.select([df['roe']>=20, df['roe']>=15, df['roe']>=10, df['roe']>=5], [20, 16, 12, 6], default=0)
        df['score_peg'] = np.select([df['peg']<=0, df['peg']<=0.7, df['peg']<=1.0, df['peg']<=1.5, df['peg']<=2.0], [0, 20, 16, 10, 5], default=0)
        df['score_cagr'] = np.select([df['cagr']>=25, df['cagr']>=15, df['cagr']>=8, df['cagr']>=3], [15, 12, 8, 4], default=0)
        df['score_eps3y'] = np.select([df['eps_growth']>=30, df['eps_growth']>=15, df['eps_growth']>=5, df['eps_growth']>0], [10, 8, 5, 2], default=0)
        df['score_rsi'] = np.select([df['rsi']>=65, df['rsi']>=55, df['rsi']>=35, df['rsi']>=25], [1, 3, 5, 3], default=1)
        df['score_peak_diff'] = np.select([df['peak_diff']< -60, df['peak_diff']<= -45, df['peak_diff']<= -10], [1, 3, 5], default=0)
        
        # 합산 및 등급 맵핑
        df['score'] = df['score_per'] + df['score_pbr'] + df['score_roe'] + df['score_peg'] + df['score_cagr'] + df['score_eps3y'] + df['score_rsi'] + df['score_peak_diff']
        df['grade'] = np.select([df['score']>=85, df['score']>=70, df['score']>=55, df['score']>=40], ['S', 'A', 'B', 'C'], default='D')
        
        # 시가총액 기준 내림차순 정렬 및 순위 부여
        df = sort_by_market_cap(df)

        # 6. 저장 및 UI 전송
        valid_cache, validation_reasons = validate_cache_dataframe(df, expected_rows=top_n)
        if not valid_cache:
            raise RuntimeError(f"cache validation failed: {'; '.join(validation_reasons)}")

        final_data = df.to_dict(orient='records')
        if save_cache:
            temp_cache_file = f"{cache_file}.tmp"
            df.to_csv(temp_cache_file, index=False, encoding="utf-8-sig")
            os.replace(temp_cache_file, cache_file)
        
        app_queue.put({"type": "data", "data": final_data})
        app_queue.put({"type": "done", "text": "[OK] 스크리닝 성공 및 로컬 데이터베이스 덤프 완료!"})
        
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 치명적 오류 발생: {e}"})
