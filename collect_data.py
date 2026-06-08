import os
import time
import queue
import threading
import pandas as pd
from datetime import datetime
import analyzer
from config import (
    CACHE_DIR, 
    DEFAULT_US_TICKERS, 
    DEFAULT_KOSPI_TICKERS, 
    KOSPI_NAME_MAP, 
    DEFAULT_KOSDAQ_TICKERS, 
    KOSDAQ_NAME_MAP
)

def collect_all_markets():
    markets = ["미국", "한국(코스피)", "한국(코스닥)"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    for market in markets:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {market} 시장 분석 및 캐싱 수집 시작...")
        app_queue = queue.Queue()
        stop_event = threading.Event()
        
        if market == "미국":
            tickers = [{"rank": i+1, "symbol": t, "name": analyzer.US_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_US_TICKERS)]
        elif market == "한국(코스피)":
            tickers = [{"rank": i+1, "symbol": t, "name": KOSPI_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_KOSPI_TICKERS)]
        elif market == "한국(코스닥)":
            tickers = [{"rank": i+1, "symbol": t, "name": KOSDAQ_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_KOSDAQ_TICKERS)]
        else:
            continue

        t_worker = threading.Thread(
            target=analyzer.screening_worker, 
            args=(market, tickers, app_queue, stop_event, True, True)
        )
        t_worker.start()
        
        results = []
        while t_worker.is_alive() or not app_queue.empty():
            try:
                msg = app_queue.get(timeout=1)
                if msg.get("type") == "data":
                    data_row = msg["data"]
                    results.append(data_row)
                elif msg.get("type") == "done":
                    break
            except queue.Empty:
                continue
        
        stop_event.set()
        t_worker.join()
        
        if results:
            df = pd.DataFrame(results)
            if "market_cap" in df.columns and len(df) > 0:
                df = df.sort_values(by="market_cap", ascending=False)
                df["rank"] = range(1, len(df) + 1)
            
            csv_path = os.path.join(CACHE_DIR, f"screener_data_{market}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"✅ {market} 저장 완료: {csv_path}")
        else:
            print(f"⚠️ {market} 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    collect_all_markets()