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

def get_per_grade(val):
    if pd.isna(val) or val == "N/A" or val == "None" or val == "비활성":
        return "정보없음"
    try:
        v = float(val)
        if v < 0: return f"{v:.1f} (적자)"
        elif v <= 10: return f"{v:.1f} (초저평가)"
        elif v <= 20: return f"{v:.1f} (적정)"
        elif v <= 40: return f"{v:.1f} (고평가)"
        else: return f"{v:.1f} (초고평가)"
    except:
        return "정보없음"

def get_pbr_grade(val):
    if pd.isna(val) or val == "N/A" or val == "None" or val == "비활성":
        return "정보없음"
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        v = float(val)
        if v < 0: return f"{v:.2f} (자본잠식)"
        elif v <= 1.0: return f"{v:.2f} (절대저평가)"
        elif v <= 1.5: return f"{v:.2f} (적정)"
        elif v <= 3.0: return f"{v:.2f} (고평가)"
        else: return f"{v:.2f} (초고평가)"
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
            market_type = 'KOSDAQ' if market == "한국(코스닥)" else 'KOSPI'
            market_text = "코스닥" if market == "한국(코스닥)" else "코스피"
            
            app_queue.put({"type": "progress", "value": 5, "text": f"{market_text} 상위 {top_n}위 종목 로드 중..."})
            df_kr = fdr.StockListing(market_type)
            df_kr = df_kr.dropna(subset=['Marcap']).sort_values(by='Marcap', ascending=False).head(top_n)
            
            for idx, row in enumerate(df_kr.iterrows(), 1):
                r_data = row[1]
                mcap_val = int(r_data['Marcap'] / 100000000) if not pd.isna(r_data['Marcap']) else 0
                tickers_to_screen.append({
                    "symbol": r_data['Code'], "name": r_data['Name'], "rank": idx, "market_cap": mcap_val
                })
                kr_fundamental_map[r_data['Code']] = {
                    "per": r_data['PER'] if 'PER' in r_data else "N/A",
                    "pbr": r_data['PBR'] if 'PBR' in r_data else "N/A",
                    "bps": r_data['BPS'] if 'BPS' in r_data else "N/A"
                }
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({"symbol": ticker, "name": info["name"], "rank": info["rank"], "market_cap": info["market_cap"]})

        total_stocks = len(tickers_to_screen)
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        for idx, stock in enumerate(tickers_to_screen, 1):
            if stop_requested_func():
                app_queue.put({"type": "stopped", "count": idx - 1})
                return

            symbol = stock["symbol"]
            name = stock["name"]
            
            app_queue.put({"type": "progress", "value": int((idx / total_stocks) * 100), "text": f"분석 중: {name} [{idx}/{total_stocks}]"})

            try:
                df = fetch_stock_data(market, symbol, start_date, end_date)
                if df is None: continue

                last_date_obj = df.index[-1]
                date_str = last_date_obj.strftime('%Y-%m-%d') if hasattr(last_date_obj, 'strftime') else str(last_date_obj)[:10]

                if market == "미국" and stock["market_cap"] == 0:
                    try:
                        mc = yf.Ticker(symbol).info.get('marketCap', 0)
                        stock["market_cap"] = int(mc / 100000000)
                    except: pass

                close_series = df['Close']
                current_price = float(close_series.iloc[-1])
                
                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1])
                if pd.isna(current_ma200) or current_ma200 == 0: continue

                diff_val = ((current_price - current_ma200) / current_ma200) * 100
                rsi_val = calculate_rsi(close_series, 14)

                per_val, pbr_val = float('nan'), float('nan')
                roe_val, peg_val = float('nan'), float('nan')
                eps3y_str = "-"
                cagr_val = float('nan')

                t_obj = None
                if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                    suffix = ".KQ" if market == "한국(코스닥)" else ".KS"
                    t_obj = yf.Ticker(f"{symbol}{suffix}")
                else:
                    t_obj = yf.Ticker(symbol)

                if opt_fundamental:
                    if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                        f_info = kr_fundamental_map.get(symbol, {"per": "N/A", "pbr": "N/A", "bps": "N/A"})
                        per_val_raw = f_info.get("per", "N/A")
                        
                        if pd.isna(per_val_raw) or str(per_val_raw) in ["N/A", "0", "nan", "None"]:
                            try:
                                info = t_obj.info
                                per_val_raw = info.get('trailingPE') or info.get('forwardPE') or float('nan')
                            except: per_val_raw = float('nan')
                            
                        try: per_val = float(per_val_raw) if not pd.isna(per_val_raw) else float('nan')
                        except: per_val = float('nan')
                        
                        try: pbr_val = float(f_info.get("pbr", float('nan')))
                        except: pbr_val = float('nan')
                        if pd.isna(pbr_val) or pbr_val == 0:
                            try:
                                info = t_obj.info
                                pbr_val = info.get('priceToBook', float('nan'))
                            except: pass
                    else:
                        try:
                            info = t_obj.info
                            per_val_raw = info.get('trailingPE', float('nan'))
                            pbr_val_raw = info.get('priceToBook', float('nan'))
                            
                            if (pbr_val_raw == 'N/A' or pbr_val_raw is None or pd.isna(pbr_val_raw)) and info.get('bookValue'):
                                try:
                                    pbr_val_raw = current_price / float(info.get('bookValue'))
                                except:
                                    pbr_val_raw = float('nan')

                            try: per_val = float(per_val_raw) if per_val_raw != 'N/A' else float('nan')
                            except: per_val = float('nan')
                            try: pbr_val = float(pbr_val_raw) if pbr_val_raw != 'N/A' else float('nan')
                            except: pbr_val = float('nan')
                        except: 
                            per_val, pbr_val = float('nan'), float('nan')

                # ROE 데이터 추출
                try:
                    if t_obj is not None:
                        info = t_obj.info
                        if info and 'returnOnEquity' in info and info['returnOnEquity'] is not None:
                            roe_val = float(info['returnOnEquity']) * 100
                except:
                    pass

                # EPS3Y 및 CAGR 연간 데이터 기반 판정 코드
                try:
                    if t_obj is not None:
                        financials = t_obj.financials
                        if financials is not None and not financials.empty:
                            eps_rows = [r for r in financials.index if 'Diluted EPS' in str(r) or 'Basic EPS' in str(r)]
                            if eps_rows:
                                eps_series = financials.loc[eps_rows[0]].dropna()
                                eps_series = eps_series.sort_index(ascending=True)
                                
                                if len(eps_series) >= 3:
                                    recent_eps = eps_series.values[-3:]
                                    v1, v2, v3 = recent_eps[0], recent_eps[1], recent_eps[2]
                                    
                                    if v1 < v2 < v3:
                                        eps3y_str = "↑"
                                    else:
                                        eps3y_str = "↓"
                                        
                                    if v1 <= 0 and v2 <= 0 and v3 <= 0:
                                        eps3y_str = "적자"
                                        
                                    if len(eps_series) >= 4:
                                        eps_start = eps_series.values[-4]
                                        eps_end = eps_series.values[-1]
                                        if eps_start > 0 and eps_end > 0:
                                            cagr_val = ((eps_end / eps_start) ** (1/3) - 1) * 100
                                    else:
                                        eps_start = eps_series.values[-3]
                                        eps_end = eps_series.values[-1]
                                        if eps_start > 0 and eps_end > 0:
                                            cagr_val = ((eps_end / eps_start) ** (1/2) - 1) * 100
                except:
                    pass

                # PEG 계산 (PEG = PER / EPS CAGR(3년))
                if pd.notna(per_val) and per_val > 0 and pd.notna(cagr_val) and cagr_val > 0 and eps3y_str != "적자":
                    try:
                        peg_val = per_val / cagr_val
                    except:
                        peg_val = float('nan')

                peak_price, peak_diff = float('nan'), float('nan')
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100

                app_queue.put({"type": "data", "data": {
                    "rank": stock["rank"], "symbol": symbol, "name": name, "data_date": date_str, "market_cap": stock["market_cap"],
                    "price": current_price, "ma200": current_ma200, "diff": diff_val, "rsi": rsi_val,
                    "per": per_val, "pbr": pbr_val, "peak": peak_price, "peak_diff": peak_diff,
                    "roe": roe_val, "peg": peg_val, "eps3y": eps3y_str, "cagr": cagr_val
                }})
            except: continue
            time.sleep(0.05)

        if not stop_requested_func():
            app_queue.put({"type": "done", "count": total_stocks, "text": f"{market} 상위 {top_n}종목 스크리닝 완료!"})
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 오류 발생: {e}"})

# ====================================================================
# 깃허브 액션즈(스케줄러) 연동용 메인 컨트롤러 코드 자동 탑재 (수정/보완)
# ====================================================================
if __name__ == "__main__":
    import queue
    from config import CACHE_DIR
    
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        
    us_cache_data = load_us_market_cap_cache()
    target_markets = ["한국(코스피)", "한국(코스닥)", "미국"]
    
    print(f"[{datetime.now()}] >>> 깃허브 자동 정기 스크리닝 배치 작업을 시작합니다.")
    
    for target_m in target_markets:
        print(f"[{datetime.now()}] 진행 중: {target_m} 시장 데이터 수집 및 분석 처리중...")
        sync_queue = queue.Queue()
        
        screening_worker(
            market=target_m,
            top_n=50,
            app_queue=sync_queue,
            stop_requested_func=lambda: False,
            opt_fundamental=True,
            opt_peak=True,
            us_market_cap_data=us_cache_data
        )
        
        batch_records = []
        while not sync_queue.empty():
            packet = sync_queue.get()
            if packet.get("type") == "data":
                batch_records.append(packet["data"])
            elif packet.get("type") == "error":
                print(f"    [!] 에러 발생 ({target_m}): {packet.get('text')}")
                
        if batch_records:
            final_batch_df = pd.DataFrame(batch_records)
            if "market_cap" in final_batch_df.columns and len(final_batch_df) > 0:
                final_batch_df = final_batch_df.sort_values(by="market_cap", ascending=False)
                final_batch_df["rank"] = range(1, len(final_batch_df) + 1)
                
            out_file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{target_m}.csv")
            final_batch_df.to_csv(out_file_path, index=False, encoding='utf-8-sig')
            print(f"    [✓] 완료: {target_m} 시장 파일 저장 성공 ({len(final_batch_df)}개 종목) -> {out_file_path}")
        else:
            print(f"    [!] 경고: {target_m} 시장의 분석 결과 데이터가 비어있습니다.")
            
    print(f"[{datetime.now()}] >>> 모든 시장의 스케줄러 배치 작업이 안전하게 완료되었습니다.")