import os
import json
import time
import random
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

from config import DEFAULT_US_TICKERS, US_NAME_MAP, US_MARKETCAP_CACHE_FILE

# ==========================================
# [1] 세션 및 차단 방지 설정
# ==========================================
def get_custom_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    })
    return session

# ==========================================
# [2] 유틸리티 함수
# ==========================================
def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    initial_cache = {}
    for i, ticker in enumerate(DEFAULT_US_TICKERS, 1):
        initial_cache[ticker] = {"rank": i, "name": US_NAME_MAP.get(ticker, ticker), "market_cap": 0}
    return initial_cache

def calculate_rsi(series, period=14):
    if len(series) < period:
        return 50.0
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else 50.0

# ==========================================
# [3] 데이터 수집 로직 (상세 분석)
# ==========================================
def analyze_single_stock(stock, market, opt_fundamental, opt_peak, kr_fundamental_map, session):
    symbol = stock["symbol"]
    name = stock["name"]
    
    # 랜덤 지연 (차단 방지)
    time.sleep(random.uniform(0.1, 0.3))
    
    try:
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        
        # 데이터 페칭
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            df = fdr.DataReader(symbol, start=start_date, end=end_date)
        else:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False, session=session)
            
        if df is None or df.empty or len(df) < 10:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        last_date_obj = df.index[-1]
        date_str = last_date_obj.strftime('%Y-%m-%d') if hasattr(last_date_obj, 'strftime') else str(last_date_obj)[:10]

        close_series = df['Close']
        current_price = float(close_series.iloc[-1])
        
        # 기술적 지표
        ma200_series = close_series.rolling(window=200).mean()
        current_ma200 = float(ma200_series.iloc[-1]) if len(close_series) >= 200 else float('nan')
        diff_val = ((current_price - current_ma200) / current_ma200) * 100 if pd.notna(current_ma200) and current_ma200 != 0 else float('nan')
        rsi_val = calculate_rsi(close_series, 14)

        # 재무 지표 초기화
        per_val, pbr_val, roe_val, peg_val = float('nan'), float('nan'), float('nan'), float('nan')
        eps3y_str, cagr_val = "-", float('nan')

        t_obj = None
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            suffix = ".KQ" if market == "한국(코스닥)" else ".KS"
            t_obj = yf.Ticker(f"{symbol}{suffix}", session=session)
        else:
            t_obj = yf.Ticker(symbol, session=session)

        if opt_fundamental:
            try:
                info = t_obj.info
                # PER 보완 (trailing -> forward)
                per_val = info.get('trailingPE') or info.get('forwardPE')
                # PBR 보완 (priceToBook -> 직접 계산)
                pbr_val = info.get('priceToBook')
                if (pd.isna(pbr_val) or pbr_val is None) and info.get('bookValue'):
                    pbr_val = current_price / info.get('bookValue')
                
                # ROE 보완 (returnOnEquity -> 직접 계산)
                roe_val = info.get('returnOnEquity')
                if (pd.isna(roe_val) or roe_val is None):
                    # 재무제표 기반 계산 시도
                    financials = t_obj.financials
                    if financials is not None and not financials.empty:
                        try:
                            net_income = financials.loc['Net Income'].iloc[0]
                            equity = info.get('totalStockholderEquity') or info.get('bookValue') * info.get('sharesOutstanding', 1)
                            if net_income and equity:
                                roe_val = net_income / equity
                        except: pass
                
                if pd.notna(roe_val) and roe_val is not None:
                    roe_val = float(roe_val) * 100

                # PEG
                peg_val = info.get('pegRatio')
            except:
                pass

            # 한국 종목 추가 보완 (FinanceDataReader 데이터 활용)
            if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                f_info = kr_fundamental_map.get(symbol, {})
                if pd.isna(per_val) or per_val is None:
                    per_raw = f_info.get("per")
                    if pd.notna(per_raw) and per_raw != 0: per_val = per_raw
                if pd.isna(pbr_val) or pbr_val is None:
                    pbr_raw = f_info.get("pbr")
                    if pd.notna(pbr_raw) and pbr_raw != 0: pbr_val = pbr_raw

            # EPS 성장률 분석
            try:
                financials = t_obj.financials
                if financials is not None and not financials.empty:
                    eps_rows = [r for r in financials.index if 'EPS' in str(r)]
                    if eps_rows:
                        eps_series = financials.loc[eps_rows[0]].dropna().sort_index()
                        if len(eps_series) >= 3:
                            v = eps_series.values
                            eps3y_str = "↑" if v[-1] > v[-2] > v[-3] else "↓"
                            if all(val <= 0 for val in v[-3:]): eps3y_str = "적자"
                            
                            # CAGR 계산
                            if len(eps_series) >= 4 and v[-4] > 0 and v[-1] > 0:
                                cagr_val = ((v[-1] / v[-4]) ** (1/3) - 1) * 100
            except: pass

        peak_price, peak_diff = float('nan'), float('nan')
        if opt_peak:
            peak_price = float(close_series.max())
            peak_diff = ((current_price - peak_price) / peak_price) * 100

        return {
            "rank": stock["rank"], "symbol": symbol, "name": name, "data_date": date_str, "market_cap": stock["market_cap"],
            "price": current_price, "ma200": current_ma200, "diff": diff_val, "rsi": rsi_val,
            "per": per_val, "pbr": pbr_val, "peak": peak_price, "peak_diff": peak_diff,
            "roe": roe_val, "peg": peg_val, "eps3y": eps3y_str, "cagr": cagr_val
        }
    except Exception as e:
        print(f"Error analyzing {name}: {e}")
        return None

# ==========================================
# [4] 메인 워커 (병렬 처리)
# ==========================================
def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        session = get_custom_session()
        tickers_to_screen = []
        kr_fundamental_map = {}
        
        # (1) 대상 종목 리스트 업
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = 'KOSDAQ' if market == "한국(코스닥)" else 'KOSPI'
            app_queue.put({"type": "progress", "value": 5, "text": f"{market} 상위 {top_n}위 로드 중..."})
            df_kr = fdr.StockListing(market_type)
            df_kr = df_kr.dropna(subset=['Marcap']).sort_values(by='Marcap', ascending=False).head(top_n)
            
            for idx, row in enumerate(df_kr.iterrows(), 1):
                r_data = row[1]
                tickers_to_screen.append({
                    "symbol": r_data['Code'], "name": r_data['Name'], "rank": idx, 
                    "market_cap": int(r_data['Marcap'] / 100000000) if not pd.isna(r_data['Marcap']) else 0
                })
                kr_fundamental_map[r_data['Code']] = {"per": r_data.get('PER'), "pbr": r_data.get('PBR')}
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({"symbol": ticker, "name": info["name"], "rank": info["rank"], "market_cap": info["market_cap"]})

        total_stocks = len(tickers_to_screen)
        processed_count = 0
        
        # (2) 병렬 분석 실행 (ThreadPoolExecutor)
        # 차단 방지를 위해 max_workers를 5~8개로 제한
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {
                executor.submit(analyze_single_stock, stock, market, opt_fundamental, opt_peak, kr_fundamental_map, session): stock 
                for stock in tickers_to_screen
            }
            
            for future in as_completed(future_to_stock):
                if stop_requested_func():
                    executor.shutdown(wait=False)
                    app_queue.put({"type": "stopped", "count": processed_count})
                    return

                res = future.result()
                processed_count += 1
                
                if res:
                    app_queue.put({"type": "data", "data": res})
                
                app_queue.put({
                    "type": "progress", 
                    "value": int((processed_count / total_stocks) * 100), 
                    "text": f"분석 완료: {res['name'] if res else '정보 없음'} [{processed_count}/{total_stocks}]"
                })

        if not stop_requested_func():
            app_queue.put({"type": "done", "count": total_stocks, "text": f"{market} 스크리닝 완료!"})
            
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 오류: {e}"})
