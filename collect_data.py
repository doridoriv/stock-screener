import os
import time
import queue
import threading
import pandas as pd
from datetime import datetime
import analyzer
from config import (
    CACHE_DIR, DEFAULT_US_TICKERS, 
    DEFAULT_KOSPI_TICKERS, DEFAULT_KOSDAQ_TICKERS
)

def collect_all_markets():
    markets = ["미국", "한국(코스피)", "한국(코스닥)"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    for market in markets:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {market} 시장 백업 수집 연산 시동...")
        app_queue = queue.Queue()
        stop_event = threading.Event()
        
        # [방법 B 기반 고정 티커 할당]
        if market == "미국":
            t_count = len(DEFAULT_US_TICKERS)
        elif "코스피" in market:
            t_count = len(DEFAULT_KOSPI_TICKERS)
        else:
            t_count = len(DEFAULT_KOSDAQ_TICKERS)

        us_cache_data = analyzer.load_us_market_cap_cache() if market == "미국" else None

        t_worker = threading.Thread(
            target=analyzer.screening_worker, 
            args=(market, t_count, app_queue, lambda: stop_event.is_set(), True, True, us_cache_data)
        )
        t_worker.start()
        
        results = []
        while t_worker.is_alive() or not app_queue.empty():
            try:
                msg = app_queue.get(timeout=1)
                if msg.get("type") == "data":
                    results.append(msg["data"])
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
            print(f"✅ {market} 캐시 파일 자동 빌드 세이브 완료: {len(df)}개 종목 저장")

if __name__ == "__main__":
    collect_all_markets()