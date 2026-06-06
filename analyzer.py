import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from config import DEFAULT_US_TICKERS, US_NAME_MAP, US_MARKETCAP_CACHE_FILE

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    initial_cache = {}
    for i, ticker in enumerate(DEFAULT_US_TICKERS, 1):
        initial_cache[ticker] = {
            "rank": i, 
            "name": US_NAME_MAP.get(ticker, ticker), 
            "market_cap": 0
        }
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
    
    if not pd.isna(val):
        return float(val)
    else:
        return 50.0

def get_per_grade(val):
    if pd.isna(val) or val is None:
        return "정보없음"
    if val < 0:
        return "적자"
    if val <= 10:
        return "초저평가"
    if val <= 20:
        return "적정"
    if val <= 35:
        return "고평가"
    return "초고평가"

def get_pbr_grade(val):
    if pd.isna(val) or val is None:
        return "정보없음"
    if val < 0:
        return "적자"
    if val <= 1.0:
        return "저평가"
    if val <= 2.5:
        return "적정"
    return "고평가"

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental=True, opt_peak=True, us_cache=None):
    try:
        stocks = []
        if market == "미국":
            if us_cache:
                for t, info in us_cache.items():
                    stocks.append({
                        "symbol": t, 
                        "name": info["name"], 
                        "rank": info["rank"], 
                        "market_cap": info["market_cap"]
                    })
            else:
                for i, t in enumerate(DEFAULT_US_TICKERS, 1):
                    stocks.append({
                        "symbol": t, 
                        "name": US_NAME_MAP.get(t, t), 
                        "rank": i, 
                        "market_cap": 0
                    })
        else:
            df_krx = fdr.StockListing("KRX")
            df_krx = df_krx.dropna(subset=["Marcap"])
            df_krx = df_krx.sort_values(by="Marcap", ascending=False)
            
            count = 0
            for idx, row in df_krx.iterrows():
                count += 1
                stocks.append({
                    "symbol": row["Code"], 
                    "name": row["Name"], 
                    "rank": count, 
                    "market_cap": int(row["Marcap"] / 100000000)
                })
                if count >= 300:
                    break

        stocks = stocks[:top_n]
        total_stocks = len(stocks)

        end_date = datetime.today()
        start_date = end_date - timedelta(days=365)
        
        for idx, stock in enumerate(stocks):
            if stop_requested_func():
                app_queue.put({
                    "type": "stopped", 
                    "count": idx, 
                    "text": "사용자 요청으로 중지되었습니다."
                })
                return

            symbol = stock["symbol"]
            name = stock["name"]
            
            app_queue.put({
                "type": "progress", 
                "value": int(((idx + 1) / total_stocks) * 100), 
                "text": f"[{idx + 1}/{total_stocks}] {name} ({symbol}) 분석 중..."
            })

            try:
                if market == "미국":
                    df = yf.download(symbol, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), progress=False)
                else:
                    df = fdr.DataReader(symbol, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))

                if df.empty or len(df) < 10:
                    continue

                close_series = df["Close"].squeeze()
                current_price = float(close_series.iloc[-1])
                date_str = df.index[-1].strftime('%Y-%m-%d')

                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1]) if not pd.isna(ma200_series.iloc[-1]) else 0.0

                diff_val = 0.0
                if current_ma200 > 0:
                    diff_val = ((current_price - current_ma200) / current_ma200) * 100

                rsi_val = calculate_rsi(close_series)

                per_str, pbr_str = "정보없음", "정보없음"
                if opt_fundamental:
                    if market == "한국":
                        per_str = "정보없음"
                        pbr_str = "정보없음"
                    else:
                        try:
                            ticker_ob = yf.Ticker(symbol)
                            info = ticker_ob.info
                            per_val = info.get("trailingPE")
                            pbr_val = info.get("priceToBook")

                            per_str = get_per_grade(per_val)
                            pbr_str = get_pbr_grade(pbr_val)
                        except: 
                            per_str, pbr_str = "정보없음", "정보없음"

                peak_str, peak_diff_str = "비활성", "비활성"
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100
                    peak_str = f"${peak_price:.2f}" if market == "미국" else f"{int(peak_price):,}원"
                    
                    # Streamlit 정렬 방해를 막기 위해 기호(🔴, 🔵 등)를 모두 제거하고 순수 수치/텍스트만 전달
                    if peak_diff > 0: 
                        peak_diff_str = f"+{peak_diff:.2f}%"
                    elif peak_diff < 0: 
                        peak_diff_str = f"{peak_diff:.2f}%"
                    else: 
                        peak_diff_str = "0.00%"

                app_queue.put({
                    "type": "data", 
                    "data": {
                        "rank": stock["rank"], 
                        "symbol": symbol, 
                        "name": name, 
                        "data_date": date_str, 
                        "market_cap": stock["market_cap"],
                        "price": current_price, 
                        "ma200": current_ma200, 
                        "diff": diff_val, 
                        "rsi": rsi_val,
                        "per": per_str, 
                        "pbr": pbr_str, 
                        "peak": peak_str, 
                        "peak_diff": peak_diff_str
                    }
                })
            except: 
                continue
            time.sleep(0.05)

        if not stop_requested_func():
            app_queue.put({
                "type": "done", 
                "count": total_stocks, 
                "text": f"{market} 상위 {top_n}종목 스크리닝 완료!"
            })
    except Exception as e:
        app_queue.put({
            "type": "error", 
            "text": f"엔진 치명적 오류 발생: {str(e)}"
        })