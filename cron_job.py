import os
import queue
import time
from datetime import datetime
import pandas as pd

import analyzer
from config import CACHE_DIR, FIXED_TOP_N

def run_auto_screening(market, top_n=FIXED_TOP_N):
    """
    웹 UI 없이 백그라운드에서 지정된 시장의 데이터를 수집하고
    기존 웹앱과 100% 호환되는 경로에 CSV 파일(일일 스냅샷)로 자동 저장합니다.
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [START] {market} 시장 백그라운드 자동 분석 시작...")
    
    # 1. 스레드 통신용 큐 및 중지 이벤트 시뮬레이션 설정
    app_queue = queue.Queue()
    stop_check_func = lambda: False
    
    # 2. 미국 시가총액 캐시 데이터 로드
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    # 3. 수집 엔진(screening_worker) 가동 (동기식 블로킹 실행)
    try:
        analyzer.screening_worker(
            market=market,
            top_n=FIXED_TOP_N,
            app_queue=app_queue,
            stop_requested_func=stop_check_func,
            opt_fundamental=True,
            opt_peak=True,
            us_market_cap_data=us_market_cap_data
        )
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 엔진 가동 중 치명적 오류 발생: {e}")
        return

    # 4. 큐(Queue)에 쌓인 데이터 처리 (로그 출력 및 수집 완료 대기)
    collected_rows = []
    while True:
        try:
            msg = app_queue.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "data":
                collected_rows = msg["data"]
            elif m_type == "progress":
                print(f" > [{market}] 진행 중... {msg['value']}% | {msg['text']}")
            elif m_type in ["done", "stopped"]:
                print(f" > [{market}] 수집 완료 신호 수신 ({msg['text']})")
            elif m_type == "error":
                print(f" > [{market}] 수집 중 에러 발생: {msg['text']}")
        except queue.Empty:
            time.sleep(0.5)
            if app_queue.empty():
                break

    # 5. 수집 결과 로그 출력
    market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
    target_date_str = analyzer.get_latest_market_date(market_text)
    file_path = os.path.join(CACHE_DIR, f"snapshot_{market_text}_{target_date_str}.csv")
    
    if os.path.exists(file_path):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [OK] {market} 자동 저장 완료! 저장경로: {file_path}")
        print(f"   (목표 수: {FIXED_TOP_N}개)\n")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 수집 결과 저장을 실패했거나 파일이 없습니다.\n")

if __name__ == "__main__":
    print("=========================================================")
    print(f"> 장마감 후 주식 대시보드 자동 스크리닝 배치 스케줄러 가동")
    print("=========================================================")
    
    # 각 시장별로 상위 100개 종목을 자동으로 수집하여 백업합니다.
    run_auto_screening("한국(코스피)", top_n=FIXED_TOP_N)
    run_auto_screening("한국(코스닥)", top_n=FIXED_TOP_N)
    run_auto_screening("미국", top_n=FIXED_TOP_N)
    
    print("=========================================================")
    print(f"> 모든 시장의 배치가 안전하게 완료되었습니다.")
    print("=========================================================")
