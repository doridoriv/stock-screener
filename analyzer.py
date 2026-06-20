import os
import json
import time
import queue
from datetime import datetime, timedelta
import concurrent.futures

import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

from config import (
    DEFAULT_US_TICKERS,
    US_NAME_MAP,
    US_MARKETCAP_CACHE_FILE,
    SCORE_WEIGHTS,
    GRADE_RULES,
)

# ==========================================
# 1. 코어 보조 지표 수집 (차단 방어용 예외처리 강화)
# ==========================================
def _get_us_10y_yield():
    try:
        hist = yf.Ticker("^TNX").history(period="1d")
        return round(float(hist['Close'].iloc[-1]), 2) if not hist.empty else 4.25
    except:
        return 4.25

def _get_historical_per_average(ticker_obj, current_eps, current_per):
    if not current_eps or current_eps <= 0: return current_per or 0.0
    try:
        hist = ticker_obj.history(period="3y", interval="1wk")
        if not hist.empty:
            avg_per = hist['Close'].mean() / current_eps
            return round(float(avg_per), 2)
    except:
        pass
    return current_per or 0.0

def _get_foreigner_supply(info, market, hist=None):
    try:
        if market == "미국":
            return round(float(info.get("institutionalPercentShares", 0) * 100), 2)
        else:
            held = info.get("sharesPercentSharesOut", 0)
            if held: return round(float(held * 100), 2)
            if hist is not None and len(hist) >= 2:
                return round(float((hist['Volume'].iloc[-1] / (hist['Volume'].mean() + 1e-9)) * 100), 2)
    except:
        pass
    return 0.0

# ==========================================
# 2. 로컬 캐시 시스템 (일일 1회 제한 최적화)
# ==========================================
def _get_daily_cache_path(market_text: str) -> str:
    cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
    today_str = datetime.now().strftime("%Y%m%d")
    return os.path.join(cache_dir, f"snapshot_{market_text}_{today_str}.csv")

def _find_latest_valid_cache(market_text: str):
    now = datetime.now()
    cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
    
    for i in range(8):
        check_date = now - timedelta(days=i)
        file_path = os.path.join(cache_dir, f"snapshot_{market_text}_{check_date.strftime('%Y%m%d')}.csv")
        
        if os.path.exists(file_path):
            if i == 0:
                if market_text in ["코스피", "코스닥"] and now.time() < datetime.strptime("15:40", "%H:%M").time():
                    continue
                if market_text == "미국" and now.time() < datetime.strptime("06:30", "%H:%M").time():
                    continue
            return file_path
    return None

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    
    return {ticker: {"rank": i, "name": US_NAME_MAP.get(ticker, ticker), "market_cap": 0} 
            for i, ticker in enumerate(DEFAULT_US_TICKERS, 1)}

# ==========================================
# 3. 데이터 연산 유틸리티
# ==========================================
def calculate_rsi(series, period=14):
    if len(series) < period + 1: return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0

def _safe_float(val):
    try:
        if pd.isna(val) or str(val).strip() in {"", "-", "N/A", "None", "nan"}: return float("nan")
        return float(str(val).replace(",", "").strip())
    except: return float("nan")

# ==========================================
# 4. 정량 점수 스코어링 시스템 (기존 로직 유지)
# ==========================================
def _score_metric(val, rules):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    for threshold, score, is_greater in rules:
        if (is_greater and v >= threshold) or (not is_greater and v <= threshold): return score, True
    return 0, True

def _grade_from_score(score):
    score = float(score) if pd.notna(score) else 0.0
    for threshold, grade in GRADE_RULES:
        if score >= threshold: return grade
    return "D"

def evaluate_investment_score(stock_row, market=None):
    # 가중치 평가
    scores = {
        "score_per": _score_metric(stock_row.get("per"), [(0, 0, False), (8, 15, False), (12, 12, False), (18, 8, False), (25, 4, False)]),
        "score_pbr": _score_metric(stock_row.get("pbr"), [(0, 0, False), (0.8, 10, False), (1.2, 8, False), (1.8, 6, False), (3.0, 3, False)]),
        "score_roe": _score_metric(stock_row.get("roe"), [(20, 20, True), (15, 16, True), (10, 12, True), (5, 6, True)]),
        "score_peg": _score_metric(stock_row.get("peg"), [(0.7, 20, False), (1.0, 16, False), (1.5, 12, False), (2.0, 6, False)]),
        "score_cagr": _score_metric(stock_row.get("cagr"), [(25, 15, True), (18, 12, True), (12, 9, True), (5, 5, True)]),
        "score_rsi": _score_metric(stock_row.get("rsi"), [(65, 1, True), (55, 3, True), (35, 5, True), (25, 3, True)]),
        "score_peak_diff": _score_metric(stock_row.get("peak_diff"), [(-60, 1, False), (-45, 3, False), (-10, 5, False)])
    }
    
    eps3y = stock_row.get("eps3y", "-")
    eps_score, eps_ok = (0, True) if eps3y == "적자" else (10, True) if eps3y == "↑" else (5, True) if eps3y == "→" else (1, True) if eps3y == "↓" else (0, False)
    
    total_score = sum(s[0] for s in scores.values()) + eps_score
    grade = _grade_from_score(total_score)

    # 평가결과 합산 매핑
    result = {k: v[0] for k, v in scores.items()}
    result.update({"score_eps3y": eps_score, "score": total_score, "grade": grade})
    
    # AI 한줄 요약 (간소화)
    head = "최상위 후보" if total_score >= 90 else "상위 후보" if total_score >= 80 else "관찰 후보"
    result["summary"] = f"[{market}] {head}. 200일선 괴리율 {stock_row.get('diff', 0):.1f}% 기록 중."
    result["confidence"] = 85.0 # 스케일 축소
    
    return result

# ==========================================
# 5. [신규] 일괄(Batch) 주가 데이터 수집기
# ==========================================
def _fetch_batch_history(symbols, start_date, end_date):
    """모든 종목의 주가를 단 한 번의 yfinance 요청으로 쓸어옵니다."""
    try:
        df = yf.download(symbols, start=start_date, end=end_date, group_by='ticker', progress=False)
        return df
    except Exception as e:
        print(f"Batch download failed: {e}")
        return pd.DataFrame()

# ==========================================
# 6. [신규] 멀티스레드 기반 재무제표 수집기
# ==========================================
def _fetch_fundamental_worker(sym):
    """개별 종목의 재무지표를 독립적으로 가져옵니다 (멀티스레딩용)"""
    try:
        t_obj = yf.Ticker(sym)
        return sym, t_obj.info, t_obj.financials
    except:
        return sym, {}, None

# ==========================================
# 7. 메인 스크리닝 엔진 (극단적 최적화 완료)
# ==========================================
def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
        
        # 1. 1일 1회 로컬 캐시 탐색 (기존 로직 유지)
        valid_cache_file = _find_latest_valid_cache(market_text)
        if valid_cache_file:
            app_queue.put({"type": "progress", "value": 30, "text": f"📦 [{market_text}] 캐시 데이터 고속 로드 중..."})
            df_cached = pd.read_csv(valid_cache_file).head(top_n)
            for idx, row in df_cached.iterrows():
                if stop_requested_func(): return
                app_queue.put({"type": "data", "data": row.to_dict()})
                time.sleep(0.01)
            app_queue.put({"type": "done", "count": len(df_cached), "text": f"🎉 [{market_text}] 고속 로드 완료!"})
            return

        # 2. 분석 대상 심볼 추출 (FDR 활용)
        tickers_to_screen = []
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"
            app_queue.put({"type": "progress", "value": 5, "text": f"{market_text} 시총 명단 불러오는 중..."})
            
            df_kr = fdr.StockListing(market_type)
            df_kr = df_kr.dropna(subset=["Marcap"]).sort_values(by="Marcap", ascending=False).head(top_n)
            
            for idx, r in df_kr.iterrows():
                code = str(r["Code"]).zfill(6)
                tickers_to_screen.append({
                    "symbol": code, "yf_symbol": f"{code}.KQ" if market_type == "KOSDAQ" else f"{code}.KS",
                    "name": r["Name"], "rank": len(tickers_to_screen) + 1,
                    "market_cap": int(r["Marcap"] / 100000000)
                })
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({
                    "symbol": ticker, "yf_symbol": ticker, "name": info["name"], 
                    "rank": info["rank"], "market_cap": info["market_cap"]
                })

        # 3. YF 주가 데이터 일괄(Batch) 다운로드
        app_queue.put({"type": "progress", "value": 10, "text": f"🚀 2년치 주가 데이터 일괄 다운로드 중..."})
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        yf_symbols = [t["yf_symbol"] for t in tickers_to_screen]
        batch_hist = _fetch_batch_history(yf_symbols, start_date, end_date)
        
        # 4. 멀티스레딩으로 재무데이터 고속 수집
        app_queue.put({"type": "progress", "value": 30, "text": f"⚡ 멀티스레딩으로 재무제표 동시 수집 중..."})
        fundamentals_map = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_sym = {executor.submit(_fetch_fundamental_worker, sym): sym for sym in yf_symbols}
            for future in concurrent.futures.as_completed(future_to_sym):
                sym, info, fin = future.result()
                fundamentals_map[sym] = {"info": info, "financials": fin}
        
        # 5. 데이터 병합 및 계산 로직
        new_collected_rows = []
        us_10y_bond_val = _get_us_10y_yield()
        
        for idx, stock in enumerate(tickers_to_screen, 1):
            if stop_requested_func():
                app_queue.put({"type": "stopped", "count": idx - 1})
                return

            sym, yf_sym = stock["symbol"], stock["yf_symbol"]
            app_queue.put({"type": "progress", "value": int(30 + (idx / top_n) * 60), "text": f"분석 중: {stock['name']}"})

            # 일괄 다운로드 데이터에서 개별 종목 추출
            try:
                if len(yf_symbols) > 1:
                    close_series = batch_hist[yf_sym]['Close'].dropna()
                else:
                    close_series = batch_hist['Close'].dropna()
                    
                if close_series.empty or len(close_series) < 200: continue
            except: continue

            current_price = float(close_series.iloc[-1])
            ma200 = float(close_series.rolling(200).mean().iloc[-1])
            diff_val = ((current_price - ma200) / ma200) * 100
            rsi_val = calculate_rsi(close_series)
            peak_price = float(close_series.max())
            peak_diff = ((current_price - peak_price) / peak_price) * 100

            f_data = fundamentals_map.get(yf_sym, {"info": {}})
            info = f_data["info"]
            
            per_val = info.get("trailingPE", float('nan'))
            pbr_val = info.get("priceToBook", float('nan'))
            roe_val = info.get("returnOnEquity", 0) * 100 if info.get("returnOnEquity") else float('nan')
            eps_growth = (info.get("earningsGrowth", 0) or 0) * 100
            
            row_data = {
                "rank": stock["rank"], "symbol": sym, "name": stock["name"], "data_date": end_date,
                "market_cap": stock["market_cap"], "price": current_price, "ma200": ma200,
                "diff": diff_val, "rsi": rsi_val, "per": per_val, "pbr": pbr_val,
                "peak": peak_price, "peak_diff": peak_diff, "roe": roe_val, "peg": float('nan'),
                "eps3y": "-", "cagr": float('nan'), "eps_growth": eps_growth,
                "us_10y_bond": us_10y_bond_val, "hist_per_avg": per_val,
                "foreign_supply": _get_foreigner_supply(info, market)
            }

            eval_result = evaluate_investment_score(row_data, market=market)
            row_data.update(eval_result)

            new_collected_rows.append(row_data)
            app_queue.put({"type": "data", "data": row_data})
            time.sleep(0.01)

        # 6. 저장 및 종료
        if not stop_requested_func() and new_collected_rows:
            df_to_cache = pd.DataFrame(new_collected_rows)
            df_to_cache.to_csv(_get_daily_cache_path(market_text), index=False, encoding="utf-8-sig")
            app_queue.put({"type": "done", "count": top_n, "text": f"🎉 [{market_text}] 스크리닝 최적화 완료!"})
            
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 오류 발생: {e}"})