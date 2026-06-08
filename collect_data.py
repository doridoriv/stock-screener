import os
import time
import queue
import threading
import pandas as pd
from datetime import datetime
import analyzer
from config import CACHE_DIR

def collect_all_markets():
    markets = ["미국", "한국(코스피)", "한국(코스닥)"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    for market in markets:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {market} 시장 분석 및 캐싱 수집 시작...")
        app_queue = queue.Queue()
        stop_event = threading.Event()
        
        us_cache_data = analyzer.load_us_market_cap_cache()
        
        t_worker = threading.Thread(
            target=analyzer.screening_worker, 
            args=(market, 100, app_queue, lambda: stop_event.is_set(), True, True, us_cache_data)
        )
        t_worker.start()
        
        results = []
        while t_worker.is_alive() or not app_queue.empty():
            try:
                msg = app_queue.get(timeout=1)
                if msg.get("type") == "data":
                    data_row = msg["data"]
                    grade, comment = analyzer.evaluate_stock_grade(data_row)
                    data_row["grade"] = grade
                    data_row["comment"] = comment
                    results.append(data_row)
                elif msg.get("type") == "done":
                    break
            except queue.Empty:
                continue
        
        stop_event.set()
        t_worker.join()
        
        if results:
            df = pd.DataFrame(results)
            csv_path1 = os.path.join(CACHE_DIR, f"screener_data_{market}.csv")
            csv_path2 = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
            df.to_csv(csv_path1, index=False, encoding="utf-8-sig")
            df.to_csv(csv_path2, index=False, encoding="utf-8-sig")
            print(f"✅ {market} 저장 완료 -> {csv_path2} ({len(df)}개 종목 저장됨)")
        else:
            print(f"❌ {market} 데이터 수집 결과가 비어있습니다.")

if __name__ == "__main__":
    collect_all_markets()