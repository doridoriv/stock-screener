import os
import json
import time
import random
import io
import queue
from datetime import datetime, time as datetime_time, timedelta
import concurrent.futures
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import FinanceDataReader as fdr
import nxt_client
import opendart_client
import supplemental_data

from config import (
    DEFAULT_US_TICKERS,
    US_NAME_MAP,
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
    closes = pd.concat(price_series, axis=1)
    closes = closes.ffill().bfill()
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
        return "정규장 종가" if is_kr else "일봉 종가"
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

def find_latest_valid_cache(market_text: str):
    """
    가장 최근 거래일의 캐시가 있으면 가져오고, 없으면 최대 8일 전 캐시까지 탐색합니다.
    """
    target_date_str = get_latest_market_date(market_text)
    file_path = _get_daily_cache_path(market_text, target_date_str)
    
    if os.path.exists(file_path):
        return file_path
        
    # 공휴일이나 휴장일 대비 이전 8일간의 캐시 역추적
    for i in range(1, 9):
        check_date = datetime.strptime(target_date_str, "%Y%m%d") - timedelta(days=i)
        fallback_path = _get_daily_cache_path(market_text, check_date.strftime("%Y%m%d"))
        if os.path.exists(fallback_path):
            return fallback_path
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
        "net_cash": np.nan
    }
    
    try:
        response = safe_requests_get(url)
        tables = pd.read_html(io.StringIO(response.text))
        
        for table in tables:
            txt = table.to_string()
            
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
        "net_cash": np.nan
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
        
        roe_val = info.get("returnOnEquity")
        if roe_val is not None:
            res_dict["roe"] = round(float(roe_val) * 100, 2)
            
        res_dict["debt_ratio"] = info.get("debtToEquity", np.nan)
        res_dict["foreign_supply"] = round((info.get("heldPercentInstitutions", 0) or 0) * 100, 2)
        
        info_rev_growth = info.get("revenueGrowth")
        if info_rev_growth is not None:
            res_dict["revenue_growth"] = round(float(info_rev_growth) * 100, 2)

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
                        
    except Exception as e:
        print(f"Error fetching yfinance for {symbol}: {e}")
        
    return res_dict

# ==========================================
# 6. S&P500 기반 동적 미국 시가총액 상위 100선 추출
# ==========================================
def fetch_us_top100_tickers(top_n=100) -> list:
    """
    미국 시가총액 상위 100선 추출:
    매번 500개 종목을 조회하여 야후 파이낸스 차단을 유도하지 않고,
    로컬 캐시파일(us_marketcap_cache.json)이 있으면 이를 읽고, 
    없으면 config.py의 DEFAULT_US_TICKERS 목록을 기반으로 즉시 반환합니다.
    """
    try:
        cache_data = load_us_market_cap_cache()
        if cache_data:
            tickers_info = []
            if isinstance(cache_data, dict):
                sorted_items = sorted(cache_data.items(), key=lambda x: x[1].get("market_cap", 0), reverse=True)
                for sym, info in sorted_items[:top_n]:
                    cap_val = info.get("market_cap", 0)
                    if cap_val > 1000000:
                        cap_val = round(cap_val / 1000000000, 2)
                    tickers_info.append({
                        "yf_symbol": sym,
                        "symbol": sym,
                        "name": info.get("name", sym),
                        "market_cap": cap_val
                    })
            else: # 리스트인 경우
                for item in cache_data[:top_n]:
                    cap_val = item.get("market_cap", 0)
                    if cap_val > 1000000:
                        cap_val = round(cap_val / 1000000000, 2)
                    tickers_info.append({
                        "yf_symbol": item.get("symbol", item.get("yf_symbol")),
                        "symbol": item.get("symbol", item.get("yf_symbol")),
                        "name": item.get("name", item.get("symbol")),
                        "market_cap": cap_val
                    })
            if len(tickers_info) > 0:
                # 캐시된 종목 수가 부족한 경우 DEFAULT_US_TICKERS로 채우되, 캐시의 시총 정보를 보존합니다.
                if len(tickers_info) < top_n:
                    existing_symbols = {t["yf_symbol"] for t in tickers_info}
                    for sym in DEFAULT_US_TICKERS:
                        if len(tickers_info) >= top_n:
                            break
                        if sym not in existing_symbols:
                            tickers_info.append({
                                "yf_symbol": sym,
                                "symbol": sym,
                                "name": US_NAME_MAP.get(sym, sym),
                                "market_cap": 0
                            })
                return tickers_info
    except Exception as e:
        print("로컬 미국 시총 캐시 읽기 오류, 기본 목록 대체:", e)
        
    tickers_info = []
    for i, sym in enumerate(DEFAULT_US_TICKERS[:top_n], 1):
        tickers_info.append({
            "yf_symbol": sym,
            "symbol": sym,
            "name": US_NAME_MAP.get(sym, sym),
            "market_cap": 0
        })
    return tickers_info

# ==========================================
# 7. [핵심] Pandas & NumPy 벡터화 스크리닝 엔진
# ==========================================
def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data, force_scrape=False):
    try:
        top_n = FIXED_TOP_N
        market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
        
        # 1. 최근 마감된 날짜 캐시 확인
        target_date_str = get_latest_market_date(market_text)
        cache_file = _get_daily_cache_path(market_text, target_date_str)
        
        if not force_scrape and os.path.exists(cache_file):
            df_cached = pd.read_csv(cache_file)
            if len(df_cached) >= top_n:
                df_cached = sort_by_market_cap(df_cached).head(top_n)
                app_queue.put({"type": "data", "data": df_cached.to_dict(orient='records')})
                app_queue.put({"type": "done", "text": f"[OK] [{market_text}] {target_date_str} 캐시 데이터 로드 완료!"})
                return


        # 2. 명단 추출
        app_queue.put({"type": "progress", "value": 10, "text": "시총 명단 로드 중..."})
        tickers_info = []
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"
            df_kr = fdr.StockListing(market_type).dropna(subset=["Marcap"]).sort_values(by="Marcap", ascending=False).head(top_n)
            for idx, r in df_kr.iterrows():
                code = str(r["Code"]).zfill(6)
                tickers_info.append({
                    "yf_symbol": f"{code}.KQ" if market_type == "KOSDAQ" else f"{code}.KS", 
                    "symbol": code, 
                    "name": r["Name"], 
                    "market_cap": int(r["Marcap"]/100000000)
                })
        else:
            tickers_info = fetch_us_top100_tickers(top_n)
        
        base_df = pd.DataFrame(tickers_info)
        yf_symbols = base_df['yf_symbol'].tolist()

        # 3. YF 주가 일괄 다운로드 및 행렬 연산
        app_queue.put({"type": "progress", "value": 30, "text": "주가 정보 연산 중..."})
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        closes = download_prices_robust(yf_symbols, start_date)

        current_prices = closes.iloc[-1].copy()
        is_kr_market = market in ["한국(코스피)", "한국(코스닥)", "한국"]
        price_sources = pd.Series("daily_close", index=current_prices.index)
        price_times = pd.Series(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"), index=current_prices.index)
        if is_kr_market:
            try:
                nxt_prices = nxt_client.fetch_nxt_latest_prices()
            except Exception as e:
                print(f"[WARN] NXT latest price fetch failed: {e}")
                nxt_prices = {}

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
                latest_price, price_source, price_time = fetch_extended_last_price(
                    sym,
                    fallback=current_prices.get(sym, np.nan),
                    allow_extended=True,
                )
                if pd.notna(latest_price):
                    current_prices.loc[sym] = latest_price
                    price_sources.loc[sym] = price_source
                    price_times.loc[sym] = price_time

        price_basis = price_sources.apply(lambda source: normalize_price_source(source, is_kr_market))

        ma200 = closes.rolling(window=200).mean().iloc[-1]
        diff_val = ((current_prices - ma200) / ma200) * 100
        peak = closes.max()
        peak_diff = ((current_prices - peak) / peak) * 100

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
            'price_source': price_sources,
            'price_basis': price_basis,
            'price_time': price_times
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
                    fund_fields = ["eps_growth", "hist_per_avg", "foreign_supply", "per", "pbr", "roe", "debt_ratio", "revenue_growth", "operating_growth", "peg", "eps3y", "cagr", "revenue", "operating_income", "net_income", "operating_margin", "net_margin", "operating_cashflow", "free_cashflow", "cash", "total_debt", "net_cash"]
                    data_dict = {}
                    for f in fund_fields:
                        val = row.get(f)
                        if pd.notna(val) and val != "-" and str(val).strip() != "None" and str(val).strip() != "":
                            data_dict[f] = val
                    if data_dict:
                        prev_fund_map[sym] = data_dict
            except Exception as e:
                print(f"[WARN] Failed to load previous cache for fallback: {e}")
        
        def process_fundamental(sym):
            if stop_requested_func():
                return None
            
            # force_scrape가 아니며 이전 캐시에 6개 이상 채워진 데이터가 있는 경우 스킵(차단 원천 우회)
            use_cached = False
            if not force_scrape and sym in prev_fund_map and len(prev_fund_map[sym]) >= 6:
                use_cached = True
                
            if use_cached:
                data = {
                    "eps_growth": np.nan, "hist_per_avg": np.nan, "foreign_supply": np.nan,
                    "per": np.nan, "pbr": np.nan, "roe": np.nan, "debt_ratio": np.nan,
                    "revenue_growth": np.nan, "operating_growth": np.nan, "eps_cagr": np.nan,
                    "eps3y": "-", "revenue": np.nan, "operating_income": np.nan, "net_income": np.nan,
                    "operating_margin": np.nan, "net_margin": np.nan, "operating_cashflow": np.nan,
                    "free_cashflow": np.nan, "cash": np.nan, "total_debt": np.nan, "net_cash": np.nan
                }
                data.update(prev_fund_map[sym])
                if 'cagr' in prev_fund_map[sym] and pd.notna(prev_fund_map[sym]['cagr']):
                    data['eps_cagr'] = prev_fund_map[sym]['cagr']
                data['yf_symbol'] = sym
                return data
                
            # 수집 시도
            if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                data = fetch_kr_fundamental_naver(sym)
                data = merge_missing_fields(data, opendart_client.fetch_dart_metrics(sym))
            else:
                data = fetch_us_fundamental_yfinance(sym)
                
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
        df = supplemental_data.merge_supplemental_metrics(df, market_text)
        
        app_queue.put({"type": "progress", "value": 85, "text": "가치 및 성장성 스코어링 모형 구동..."})

        # 지표 추가 바인딩
        df['data_date'] = datetime.strptime(target_date_str, "%Y%m%d").strftime("%Y-%m-%d")
        df['us_10y_bond'] = us_10y
        df['peg'] = np.where((df['per'] > 0) & (df['eps_growth'] > 0), round(df['per'] / df['eps_growth'], 2), np.nan)
        df['cagr'] = df['eps_cagr']

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
        final_data = df.to_dict(orient='records')
        df.to_csv(cache_file, index=False, encoding="utf-8-sig")
        
        app_queue.put({"type": "data", "data": final_data})
        app_queue.put({"type": "done", "text": "[OK] 스크리닝 성공 및 로컬 데이터베이스 덤프 완료!"})
        
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 치명적 오류 발생: {e}"})
