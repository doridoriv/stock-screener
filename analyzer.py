import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from config import DEFAULT_US_TICKERS, US_NAME_MAP, US_MARKETCAP_CACHE_FILE, CACHE_DIR

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

def screening_worker(market, tickers, app_queue, stop_event, opt_fundamental=True, opt_peak=True, us_market_cap_data=None):
    date_str = datetime.now().strftime('%Y-%m-%d')
    
    for idx, stock in enumerate(tickers):
        if stop_event.is_set():
            break
            
        symbol = stock["symbol"]
        name = stock["name"]
        
        try:
            ticker_obj = yf.Ticker(symbol)
            hist = ticker_obj.history(period="2y")
            
            if hist.empty:
                continue
                
            close_series = hist['Close']
            current_price = float(close_series.iloc[-1])
            
            if len(close_series) >= 200:
                current_ma200 = float(close_series.rolling(window=200).mean().iloc[-1])
                diff_val = ((current_price - current_ma200) / current_ma200) * 100
            else:
                current_ma200 = float('nan')
                diff_val = float('nan')
                
            rsi_val = calculate_rsi(close_series)
            
            per_val = float('nan')
            pbr_val = float('nan')
            roe_val = float('nan')
            peg_val = float('nan')
            cagr_val = float('nan')
            eps3y_str = "N/A"
            mcap_val = stock.get("market_cap", 0)
            
            if opt_fundamental:
                info = ticker_obj.info
                per_val = info.get('trailingPE', info.get('forwardPE', float('nan')))
                pbr_val = info.get('priceToBook', float('nan'))
                roe_val = info.get('returnOnEquity', float('nan'))
                if pd.notna(roe_val):
                    roe_val = roe_val * 100
                    
                raw_mcap = info.get('marketCap', 0)
                if raw_mcap and raw_mcap > 0:
                    if ".KS" in symbol or ".KQ" in symbol:
                        mcap_val = round(raw_mcap / 100000000, 2)
                    else:
                        mcap_val = round(raw_mcap / 100000000, 2)
                
                eps_current = info.get('trailingEps', float('nan'))
                if pd.notna(eps_current) and eps_current > 0:
                    eps3y_str = "성장"
                    cagr_val = info.get('pegRatio', 1.0) * 10.0
                elif eps_current <= 0:
                    eps3y_str = "적자"
                    cagr_val = 0.0
                    
                if pd.notna(per_val) and per_val > 0 and pd.notna(cagr_val) and cagr_val > 0 and eps3y_str != "적자":
                    peg_val = per_val / cagr_val
                else:
                    peg_val = info.get('pegRatio', float('nan'))

            peak_price = float('nan')
            peak_diff = float('nan')
            if opt_peak:
                peak_price = float(close_series.max())
                peak_diff = ((current_price - peak_price) / peak_price) * 100

            app_queue.put({"type": "data", "data": {
                "rank": stock["rank"], "symbol": symbol, "name": name, "data_date": date_str, "market_cap": mcap_val,
                "price": current_price, "ma200": current_ma200, "diff": diff_val, "rsi": rsi_val,
                "per": per_val, "pbr": pbr_val, "peak": peak_price, "peak_diff": peak_diff,
                "roe": roe_val, "peg": peg_val, "eps3y": eps3y_str, "cagr": cagr_val
            }})
        except:
            continue
        time.sleep(0.05)
        
    app_queue.put({"type": "done"})