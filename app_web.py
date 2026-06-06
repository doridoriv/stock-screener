import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
# 자동 저장 및 불러오기 경로 지정을 위해 CACHE_DIR를 추가로 가져옵니다.
from config import APP_TITLE, CACHE_DIR

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

# [요청사항 1] 사이드바 체크박스를 삭제하고 기본 활성화(True)로 고정 설정
opt_fundamental = True
opt_peak = True

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []

# 검색 중지 기능을 제어하기 위한 스레드 이벤트 세션 초기화
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

# [요청사항 2, 4, 5] 사이드바 버튼 가로 정렬 배치 레이아웃 구현
col1, col2, col3 = st.sidebar.columns(3)

with col1:
    # [요청사항 2] 스크리닝 시작 버튼의 이름을 "🔍 검색"으로 변경
    btn_search = st.button("🔍 검색", width='stretch')

with col2:
    # [요청사항 4] 검색 버튼 우측에 '불러오기' 버튼 추가
    btn_load = st.button("📂 불러오기", width='stretch')

with col3:
    # [요청사항 5] 불러오기 버튼 우측에 '검색 중지' 버튼 추가
    btn_stop = st.button("⏹ 검색 중지", width='stretch')

# [요청사항 5] 검색 중지 기능 백엔드 로직 연동
if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    st.sidebar.warning("⏹ 스크리닝 중지 신호를 보냈습니다.")

# [요청사항 4] 자동 저장된 최근 분석 결과 파일 불러오기 기능 로직 구현
if btn_load:
    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
    if os.path.exists(file_path):
        try:
            loaded_df = pd.read_csv(file_path)
            st.session_state.data = loaded_df.to_dict(orient='records')
            st.sidebar.success(f"📂 {market} 시장의 최근 자동저장 데이터를 불러왔습니다.")
        except Exception as e:
            st.sidebar.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
    else:
        st.sidebar.warning(f"💾 {market} 시장에 백업된 데이터가 존재하지 않습니다.")

# 검색 버튼 클릭 시 작동하는 코어 엔진 블록
if btn_search:
    st.session_state.data = []  
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
    # 외부 중지 버튼 클릭 시 쓰레드가 감지할 수 있도록 세션 스토리지에 이벤트를 바인딩합니다.
    st.session_state.stop_event = threading.Event()
    
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(
            market, 
            top_n, 
            app_queue, 
            lambda: st.session_state.stop_event.is_set(), 
            opt_fundamental, 
            opt_peak, 
            us_market_cap_data
        ),
        daemon=True
    )
    worker_thread.start()
    
    while True:
        try:
            msg = app_queue.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "progress":
                progress_bar.progress(msg["value"] / 100)
                status_text.text(msg["text"])
                
            elif m_type == "data":
                st.session_state.data.append(msg["data"])
                # 데이터프레임으로 변환하여 실시간 업데이트 (원본 순서 적용)
                df = pd.DataFrame(st.session_state.data)
                column_order = [
                    "rank", "symbol", "name", "data_date", "market_cap", "price", 
                    "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
                ]
                # 존재하는 컬럼만 필터링하여 순서 변경
                available_cols = [c for c in column_order if c in df.columns]
                df = df[available_cols]
                # 시스템 경고 문구 해결을 위해 width='stretch'를 명시적으로 적용합니다.
                table_placeholder.dataframe(df, width='stretch')
                
            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                
                # [요청사항 3] 검색 완료 후 분석 결과를 지정된 캐시 경로에 자동 저장
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
            elif m_type == "error":
                st.error(msg["text"])
                break
                
            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
                
                # [요청사항 3] 중지 시점까지 수집된 데이터를 유실하지 않기 위해 중간 자동 저장 처리
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                break

# 결과 출력
if st.session_state.data:
    st.subheader("📊 분석 결과")
    final_df = pd.DataFrame(st.session_state.data)
    
    # 원본과 동일한 열 순서 설정
    column_order = [
        "rank", "symbol", "name", "data_date", "market_cap", "price", 
        "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
    ]
    # 존재하는 컬럼만 선택
    available_cols = [c for c in column_order if c in final_df.columns]
    final_df = final_df[available_cols]
    
    st.dataframe(
        final_df,
        width='stretch',
        column_config={
            "rank": "순위",
            "symbol": "티커",
            "name": "종목명",
            "data_date": "기준일",
            "market_cap": st.column_config.NumberColumn("시가총액(억)", format="%d"),
            "price": st.column_config.NumberColumn("현재가", format="%.2f"),
            "peak": "최고점",
            "peak_diff": "최고점대비",
            "ma200": st.column_config.NumberColumn("200일선", format="%.2f"),
            "diff": st.column_config.NumberColumn("200일괴리율(%)", format="%.2f"),
            "rsi": st.column_config.NumberColumn("RSI(14)", format="%.1f"),
            "per": "PER 등급",
            "pbr": "PBR 등급"
        }
    )
    
    csv = final_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("사이드바의 [검색] 버튼을 눌러 분석을 시작하세요.")