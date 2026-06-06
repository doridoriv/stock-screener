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
    if pd.isna(val) or val == "N/A" or val == "None":
        return "정보없음"
    try:
        v = float(val)
        if v < 0:
            return f"{v:.1f} (적자)"
        elif v <= 10:
            return f"{v:.1f} (초저평가)"
        elif v <= 20:
            return f"{v:.1f} (적정)"
        elif v <= 40:
            return f"{v:.1f} (고평가)"
        else:
            return f"{v:.1f} (초고평가)"
    except:
        return "정보없음"

def get_pbr_grade(val):
    if pd.isna(val) or val == "N/A" or val == "None":
        return "정보없음"
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        v = float(val)
        if v < 0:
            return f"{v:.2f} (자본잠식)"
        elif v <= 1.0:
            return f"{v:.2f} (절대저평가)"
        elif v <= 1.5:
            return f"{v:.2f} (적정)"
        elif v <= 3.0:
            return f"{v:.2f} (고평가)"
        else:
            return f"{v:.2f} (초고평가)"
    except:
        return "정보없음"

def fetch_stock_data(market, symbol, start_date, end_date):
    try:
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            df = fdr.DataReader(symbol, start=start_date, end=end_date)
        else:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
        
        if df.empty or len(df) < 200:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
            
        return df
    except:
        return None

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        tickers_to_screen = []
        kr_fundamental_map = {}
        
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            if market == "한국(코스닥)":
                market_type = 'KOSDAQ'
                market_text = "코스닥"
            else:
                market_type = 'KOSPI'
                market_text = "코스피"
            
            app_queue.put({
                "type": "progress", 
                "value": 5, 
                "text": f"{market_text} 상위 {top_n}위 종목 로드 중..."
            })
            df_kr = fdr.StockListing(market_type)
            df_kr = df_kr.dropna(subset=['Marcap']).sort_values(by='Marcap', ascending=False).head(top_n)
            
            for idx, row in enumerate(df_kr.iterrows(), 1):
                r_data = row[1]
                if not pd.isna(r_data['Marcap']):
                    mcap_val = int(r_data['Marcap'] / 100000000)
                else:
                    mcap_val = 0
                tickers_to_screen.append({
                    "symbol": r_data['Code'], 
                    "name": r_data['Name'], 
                    "rank": idx, 
                    "market_cap": mcap_val
                })
                kr_fundamental_map[r_data['Code']] = {
                    "per": r_data['PER'] if 'PER' in r_data else "N/A",
                    "pbr": r_data['PBR'] if 'PBR' in r_data else "N/A",
                    "bps": r_data['BPS'] if 'BPS' in r_data else "N/A"
                }
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({
                    "symbol": ticker, 
                    "name": info["name"], 
                    "rank": info["rank"], 
                    "market_cap": info["market_cap"]
                })

        total_stocks = len(tickers_to_screen)
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        for idx, stock in enumerate(tickers_to_screen, 1):
            if stop_requested_func():
                app_queue.put({
                    "type": "stopped", 
                    "count": idx - 1
                })
                return

            symbol = stock["symbol"]
            name = stock["name"]
            
            app_queue.put({
                "type": "progress", 
                "value": int((idx / total_stocks) * 100), 
                "text": f"분석 중: {name} [{idx}/{total_stocks}]"
            })

            try:
                df = fetch_stock_data(market, symbol, start_date, end_date)
                if df is None: 
                    continue

                last_date_obj = df.index[-1]
                if hasattr(last_date_obj, 'strftime'):
                    date_str = last_date_obj.strftime('%Y-%m-%d')
                else:
                    date_str = str(last_date_obj)[:10]

                if market == "미국" and stock["market_cap"] == 0:
                    try:
                        mc = yf.Ticker(symbol).info.get('marketCap', 0)
                        stock["market_cap"] = int(mc / 100000000)
                    except: 
                        pass

                close_series = df['Close']
                current_price = float(close_series.iloc[-1])
                
                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1])
                if pd.isna(current_ma200) or current_ma200 == 0: 
                    continue

                diff_val = ((current_price - current_ma200) / current_ma200) * 100
                rsi_val = calculate_rsi(close_series, 14)

                per_str, pbr_str = "비활성", "비활성"
                if opt_fundamental:
                    if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                        f_info = kr_fundamental_map.get(symbol, {"per": "N/A", "pbr": "N/A", "bps": "N/A"})
                        per_val = f_info.get("per", "N/A")
                        
                        if pd.isna(per_val) or str(per_val) in ["N/A", "0", "nan", "None"]:
                            try:
                                if market == "한국(코스닥)":
                                    suffix = ".KQ"
                                else:
                                    suffix = ".KS"
                                t_obj = yf.Ticker(f"{symbol}{suffix}")
                                info = t_obj.info
                                per_val = info.get('trailingPE') or info.get('forwardPE') or 'N/A'
                            except: 
                                per_val = "N/A"
                            
                        per_str = get_per_grade(per_val)
                        pbr_str = "-"
                    else:
                        try:
                            t_obj = yf.Ticker(symbol)
                            info = t_obj.info
                            per_val = info.get('trailingPE', 'N/A')
                            pbr_val = info.get('priceToBook', 'N/A')
                            
                            if (pbr_val == 'N/A' or pbr_val is None) and info.get('bookValue'):
                                try:
                                    pbr_val = current_price / float(info.get('bookValue'))
                                except:
                                    pbr_val = 'N/A'

                            per_str = get_per_grade(per_val)
                            pbr_str = get_pbr_grade(pbr_val)
                        except: 
                            per_str = "정보없음"
                            pbr_str = "정보없음"

                peak_str, peak_diff_str = "비활성", "비활성"
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100
                    if market == "미국":
                        peak_str = f"${peak_price:.2f}"
                    else:
                        peak_str = f"{int(peak_price):,}원"
                    
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
            "text": f"엔진 오류 발생: {e}"
        })