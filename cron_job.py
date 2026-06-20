import os
import queue
import time
from datetime import datetime
import pandas as pd

import analyzer
from config import CACHE_DIR

def run_auto_screening(market, top_n=50):
    """
    웹 UI 없이 백그라운드에서 지정된 시장의 데이터를 수집하고
    기존 웹앱과 100% 호환되는 경로에 CSV 파일로 자동 저장합니다.
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 {market} 시장 백그라운드 자동 분석 시작...")
    
    # 1. 스레드 통신용 큐 및 중지 이벤트 시뮬레이션 설정 (자동화이므로 중지 체크는 항상 False)
    app_queue = queue.Queue()
    stop_check_func = lambda: False
    
    # 2. 미국 시가총액 캐시 데이터 로드
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    # 3. 수집 엔진(screening_worker) 가동 (동기식 블로킹 실행)
    try:
       
        analyzer.screening_worker(
            market=market,
            top_n=top_n,
            app_queue=app_queue,
            stop_requested_func=stop_check_func, # stop_check_func -> stop_requested_func 로 변경
            opt_fundamental=True,
            opt_peak=True,
            us_market_cap_data=us_market_cap_data
)

        
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {market} 엔진 가동 중 치명적 오류 발생: {e}")
        return

    # 4. 큐(Queue)에 쌓인 데이터 안전하게 가공 및 수집
    collected_rows = []
    while True:
        try:
            msg = app_queue.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "data":
                collected_rows.append(msg["data"])
            elif m_type == "progress":
                # 터미널 창에 진행률 실시간 표시 (로그 확인용)
                print(f" > [{market}] 진행 중... {msg['value']}% | {msg['text']}", end="\r")
            elif m_type in ["done", "stopped"]:
                print(f"\n > [{market}] 수집 루프 정상 종료 신호 수신 ({msg['text']})")
            elif m_type == "error":
                print(f"\n > [{market}] 수집 중 에러 발생: {msg['text']}")
        except queue.Empty:
            # 큐가 비었고 백그라운드 연산이 끝났다면 대기 후 종료
            time.sleep(0.5)
            if app_queue.empty():
                break

    # 5. 수집된 데이터를 기존 웹앱 규격에 맞춰 정렬 후 CSV로 덤프
    if collected_rows:
        df = pd.DataFrame(collected_rows)
        
        # 가중 종합점수 기준 내림차순 정렬
        if "score" in df.columns:
            # 기존 웹앱의 _sort_dataframe 로직 동기화
            df = df.sort_values(by=["score"], ascending=[False])
            df["rank"] = range(1, len(df) + 1)
        else:
            if "market_cap" in df.columns:
                df = df.sort_values(by="market_cap", ascending=False)
                df["rank"] = range(1, len(df) + 1)
        
        # 기존 웹앱이 [📂 불러오기] 버튼을 눌렀을 때 읽어가는 경로와 정확히 일치시킴
        file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ {market} 자동 저장 완료! 저장경로: {file_path}")
        print(f"   (총 {len(df)}개 종목 성공 / 목표 수: {top_n}개)\n")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {market} 수집 결과 데이터가 0건입니다. 저장을 건너뜁니다.\n")

if __name__ == "__main__":
    print("=========================================================")
    print(f"▶ 장마감 후 주식 대시보드 자동 스크리닝 배치 스케줄러 가동")
    print("=========================================================")
    
    # 각 시장별로 상위 50개 종목을 자동으로 수집하여 백업합니다.
    run_auto_screening("한국(코스피)", top_n=50)
    run_auto_screening("한국(코스닥)", top_n=50)
    run_auto_screening("미국", top_n=50)
    
    print("=========================================================")
    print(f"▶ 모든 시장의 배치가 안전하게 완료되었습니다.")
    print("=========================================================")