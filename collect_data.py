import os
import time
import queue
import threading
import pandas as pd
from datetime import datetime
import analyzer
from config import CACHE_DIR, DEFAULT_US_TICKERS
import FinanceDataReader as fdr

def collect_all_markets():
    markets = ["미국", "한국(코스피)", "한국(코스닥)"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    for market in markets:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {market} 시장 분석 및 캐싱 수집 시작...")
        app_queue = queue.Queue()
        stop_event = threading.Event()
        
        # 각 마켓별 타겟 티커 추출 구조 설정
        if market == "미국":
            tickers = [{"rank": i+1, "symbol": t, "name": analyzer.US_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_US_TICKERS)]
        else:
            m_code = "KOSPI" if "코스피" in market else "KOSDAQ"
            try:
                df_kr = fdr.StockListing(m_code)
                df_kr = df_kr.dropna(subset=['Marcap']).sort_values(by='Marcap', ascending=False).head(100)
                tickers = []
                for idx, row in df_kr.iterrows():
                    tickers.append({
                        "rank": len(tickers) + 1,
                        "symbol": str(row['Code']),
                        "name": str(row['Name']),
                        "market_cap": round(row['Marcap'] / 100000000)
                    })
            except Exception as e:
                print(f"⚠️ {market} 주식 목록 데이터 로드 실패: {e}")
                continue

        # analyzer.py 내부 멀티스레딩 워커 엔진에 바인딩 구동
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
                    # 수집 완료 시점 즉시 등급 및 한줄평 산출 맵핑 연산 수행
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
            csv_path = os.path.join(CACHE_DIR, f"screener_data_{market}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"✅ {market} 저장 완료 -> {csv_path} ({len(df)}개 종목 저장됨)")
        else:
            print(f"❌ {market} 데이터 수집 결과가 비어있습니다.")

if __name__ == "__main__":
    collect_all_markets()