import os
import json
import time
from datetime import datetime, timedelta
import concurrent.futures

import pandas as pd
import numpy as np
import yfinance as yf
import FinanceDataReader as fdr

from config import (
    DEFAULT_US_TICKERS,
    US_NAME_MAP,
    US_MARKETCAP_CACHE_FILE,
    GRADE_RULES,
)

# ==========================================
# 1. 코어 보조 지표 수집
# ==========================================
def _get_us_10y_yield():
    try:
        hist = yf.Ticker("^TNX").history(period="1d")
        return round(float(hist['Close'].iloc[-1]), 2) if not hist.empty else 4.25
    except:
        return 4.25

def _get_foreigner_supply(info, market):
    try:
        if market == "미국":
            return round(float(info.get("institutionalPercentShares", 0) * 100), 2)
        else:
            held = info.get("sharesPercentSharesOut", 0)
            if held: return round(float(held * 100), 2)
    except: pass
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
                if market_text in ["코스피", "코스닥"] and now.time() < datetime.strptime("15:40", "%H:%M").time(): continue
                if market_text == "미국" and now.time() < datetime.strptime("06:30", "%H:%M").time(): continue
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
# 3. 데이터 수집 워커 (멀티스레드)
# ==========================================
def _fetch_fundamental_worker(sym):
    try:
        info = yf.Ticker(sym).info
        return sym, info
    except:
        return sym, {}

# ==========================================
# 4. [핵심] Pandas & NumPy 벡터화 스크리닝 엔진
# ==========================================
def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
        
        # 1. 캐시 체크
        valid_cache_file = _find_latest_valid_cache(market_text)
        if valid_cache_file:
            df_cached = pd.read_csv(valid_cache_file).head(top_n)
            app_queue.put({"type": "data", "data": df_cached.to_dict(orient='records')})
            app_queue.put({"type": "done", "text": f"🎉 [{market_text}] 고속 캐시 로드 완료!"})
            return

        # 2. 명단 추출
        app_queue.put({"type": "progress", "value": 10, "text": "시총 명단 로드 중..."})
        tickers_info = []
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"
            df_kr = fdr.StockListing(market_type).dropna(subset=["Marcap"]).sort_values(by="Marcap", ascending=False).head(top_n)
            for idx, r in df_kr.iterrows():
                code = str(r["Code"]).zfill(6)
                tickers_info.append({"yf_symbol": f"{code}.KQ" if market_type == "KOSDAQ" else f"{code}.KS", "symbol": code, "name": r["Name"], "market_cap": int(r["Marcap"]/100000000)})
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_info.append({"yf_symbol": ticker, "symbol": ticker, "name": info["name"], "market_cap": info["market_cap"]})
        
        base_df = pd.DataFrame(tickers_info)
        yf_symbols = base_df['yf_symbol'].tolist()

        # 3. YF 주가 일괄 다운로드 및 행렬(Matrix) 기술적 지표 연산
        app_queue.put({"type": "progress", "value": 30, "text": "주가 매트릭스 병렬 연산 중..."})
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        
        # 다운로드 후 데이터프레임 구조화
        batch_hist = yf.download(yf_symbols, start=start_date, progress=False)
        closes = batch_hist['Close']
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=yf_symbols[0])

        # ⭐ [마법의 공간] for문 50바퀴를 단 5줄의 행렬 연산으로 끝냅니다.
        current_prices = closes.iloc[-1]
        ma200 = closes.rolling(window=200).mean().iloc[-1]
        diff_val = ((current_prices - ma200) / ma200) * 100
        peak = closes.max()
        peak_diff = ((current_prices - peak) / peak) * 100

        # RSI 한 번에 계산
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).iloc[-1].fillna(50.0)

        tech_df = pd.DataFrame({'price': current_prices, 'ma200': ma200, 'diff': diff_val, 'peak': peak, 'peak_diff': peak_diff, 'rsi': rsi}).reset_index()
        tech_df = tech_df.rename(columns={'index': 'yf_symbol', 'Ticker': 'yf_symbol'})

        # 4. 멀티스레드 재무 데이터 로드
        app_queue.put({"type": "progress", "value": 60, "text": "재무제표 멀티스레딩 수집 중..."})
        fund_rows = []
        us_10y = _get_us_10y_yield()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for sym, info in executor.map(_fetch_fundamental_worker, yf_symbols):
                fund_rows.append({
                    'yf_symbol': sym,
                    'per': info.get("trailingPE", np.nan),
                    'pbr': info.get("priceToBook", np.nan),
                    'roe': info.get("returnOnEquity", 0) * 100 if info.get("returnOnEquity") else np.nan,
                    'eps_growth': (info.get("earningsGrowth", 0) or 0) * 100,
                    'hist_per_avg': info.get("trailingPE", np.nan),
                    'foreign_supply': _get_foreigner_supply(info, market)
                })
        
        fund_df = pd.DataFrame(fund_rows)

        # 5. 데이터 병합 (Merge)
        df = pd.merge(base_df, tech_df, on='yf_symbol', how='left')
        df = pd.merge(df, fund_df, on='yf_symbol', how='left')
        
        app_queue.put({"type": "progress", "value": 80, "text": "AI 가중치 모델링 및 스코어링 중..."})

        # ⭐ [스코어링 벡터 연산] 수십 개의 조건문을 NumPy의 np.select 로 1초 만에 컷
        df['score_per'] = np.select([df['per']<=0, df['per']<=8, df['per']<=12, df['per']<=18, df['per']<=25], [0, 15, 12, 8, 4], default=0)
        df['score_pbr'] = np.select([df['pbr']<=0, df['pbr']<=0.8, df['pbr']<=1.2, df['pbr']<=1.8, df['pbr']<=3.0], [0, 10, 8, 6, 3], default=0)
        df['score_roe'] = np.select([df['roe']>=20, df['roe']>=15, df['roe']>=10, df['roe']>=5], [20, 16, 12, 6], default=0)
        df['score_rsi'] = np.select([df['rsi']>=65, df['rsi']>=55, df['rsi']>=35, df['rsi']>=25], [1, 3, 5, 3], default=1)
        df['score_peak_diff'] = np.select([df['peak_diff']< -60, df['peak_diff']<= -45, df['peak_diff']<= -10], [1, 3, 5], default=0)
        
        # 합산 및 등급 맵핑
        df['score'] = df['score_per'] + df['score_pbr'] + df['score_roe'] + df['score_rsi'] + df['score_peak_diff']
        df['grade'] = np.select([df['score']>=85, df['score']>=70, df['score']>=55, df['score']>=40], ['S', 'A', 'B', 'C'], default='D')
        
        # 기타 기본값 매핑
        df['data_date'] = datetime.now().strftime("%Y-%m-%d")
        df['us_10y_bond'] = us_10y
        df['peg'] = np.nan
        df['eps3y'] = "-"
        df['cagr'] = np.nan
        df['rank'] = range(1, len(df) + 1)

        # 6. 저장 및 UI 전송
        final_data = df.to_dict(orient='records')
        df.to_csv(_get_daily_cache_path(market_text), index=False, encoding="utf-8-sig")
        
        app_queue.put({"type": "data", "data": final_data})
        app_queue.put({"type": "done", "text": "🎉 스크리닝 완료! (NumPy Matrix 연산 적용)"})
        
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 오류 발생: {e}"})