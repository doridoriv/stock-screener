import os
import queue
import time
from datetime import datetime
import pandas as pd

import analyzer
import market_analyzer
from config import CACHE_DIR, FIXED_TOP_N

def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name, default, minimum=1, maximum=FIXED_TOP_N):
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def run_auto_screening(market, top_n=FIXED_TOP_N, force_scrape=None, save_cache=None):
    """
    웹 UI 없이 백그라운드에서 지정된 시장의 데이터를 수집하고
    기존 웹앱과 100% 호환되는 경로에 CSV 파일(일일 스냅샷)로 자동 저장합니다.
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [START] {market} 시장 백그라운드 자동 분석 시작...")
    
    # 1. 스레드 통신용 큐 및 중지 이벤트 시뮬레이션 설정
    if force_scrape is None:
        force_scrape = _env_bool("SCREENING_FORCE_SCRAPE", True)
    if save_cache is None:
        save_cache = _env_bool("SCREENING_SAVE_CACHE", True)

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
            stop_requested_func=stop_check_func,
            opt_fundamental=True,
            opt_peak=True,
            us_market_cap_data=us_market_cap_data,
            force_scrape=force_scrape,
            save_cache=save_cache
        )
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 엔진 가동 중 치명적 오류 발생: {e}")
        return False

    # 4. 큐(Queue)에 쌓인 데이터 처리 (로그 출력 및 수집 완료 대기)
    collected_rows = []
    had_error = False
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
                had_error = True
                print(f" > [{market}] 수집 중 에러 발생: {msg['text']}")
        except queue.Empty:
            time.sleep(0.5)
            if app_queue.empty():
                break

    # 5. 수집 결과 로그 출력
    market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
    collected_df = pd.DataFrame(collected_rows)
    data_dates = collected_df.get("data_date", pd.Series(dtype=str)).dropna().astype(str)
    if not data_dates.empty:
        target_date_str = data_dates.iloc[0].replace("-", "")
    else:
        target_date_str = analyzer.get_latest_market_date(market_text)
    file_path = os.path.join(CACHE_DIR, f"snapshot_{market_text}_{target_date_str}.csv")
    cache_valid, cache_reasons = analyzer.validate_cache_dataframe(collected_df, expected_rows=top_n)
    
    if had_error:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 수집 중 에러가 발생하여 기존 캐시를 성공으로 처리하지 않습니다.\n")
        return False
    elif not cache_valid:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 캐시 검증 실패: {'; '.join(cache_reasons)}\n")
        return False
    elif save_cache and os.path.exists(file_path):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [OK] {market} 자동 저장 완료! 저장경로: {file_path}")
        print(f"   (목표 수: {FIXED_TOP_N}개)\n")
        return True
    elif not save_cache and collected_rows:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [OK] {market} small verification completed; cache save skipped")
        print(f"   (target: {top_n} rows)\n")
        return True
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FAIL] {market} 수집 결과 저장을 실패했거나 파일이 없습니다.\n")
        return False

if __name__ == "__main__":
    print("=========================================================")
    print(f"> 장마감 후 주식 대시보드 자동 스크리닝 배치 스케줄러 가동")
    print("=========================================================")

    scope = os.getenv("SCREENING_MARKETS", "ALL").upper()
    top_n = _env_int("SCREENING_TOP_N", FIXED_TOP_N)
    force_scrape = _env_bool("SCREENING_FORCE_SCRAPE", True)
    save_cache = _env_bool("SCREENING_SAVE_CACHE", True)
    FIXED_TOP_N = top_n
    results = []
    if scope in ["ALL", "KR", "KOREA"]:
        results.append(run_auto_screening("한국(코스피)", top_n=FIXED_TOP_N))
        results.append(run_auto_screening("한국(코스닥)", top_n=FIXED_TOP_N))
    if scope in ["ALL", "US", "USA"]:
        results.append(run_auto_screening("미국", top_n=FIXED_TOP_N))

    try:
        panel = market_analyzer.save_market_panel_cache()
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"[OK] 시장환경 캐시 저장 완료: {market_analyzer.MARKET_CONTEXT_CACHE_FILE} "
            f"({panel.get('market_score')}점 / {panel.get('score_state')})"
        )
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WARN] 시장환경 캐시 저장 실패: {e}")
     
    print("=========================================================")
    if results and all(results):
        print(f"> 모든 시장의 배치가 안전하게 완료되었습니다.")
    else:
        print(f"> 일부 시장의 배치가 실패했습니다. 위의 [FAIL] 로그를 확인하세요.")
    print("=========================================================")
