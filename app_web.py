import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE, CACHE_DIR

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# ==============================================================================
# [디자인 개선] 버튼들을 메인 영역 상단에 여유로운 너비로 가로 배치 (우측 공백 확보)
# ==============================================================================
col1, col2, col3, col_empty = st.columns([1.2, 1.2, 1.2, 5])

with col1:
    btn_search = st.button("🔍 검색", use_container_width=True)

with col2:
    btn_load = st.button("📂 불러오기", use_container_width=True)

with col3:
    btn_stop = st.button("⏹ 검색 중지", use_container_width=True)

# 사이드바 설정 (불필요한 체크박스는 제거하고 핵심 설정만 유지)
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

# [요청사항 1] 기본적 분석 및 고점대비 하락율은 무조건 포함(True) 처리
opt_fundamental = True
opt_peak = True

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []

if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

# 검색 중지 로직 처리
if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    st.toast("⏹ 스크리닝 중지 신호를 보냈습니다.", icon="⚠️")

# 불러오기 로직 처리
if btn_load:
    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
    if os.path.exists(file_path):
        try:
            loaded_df = pd.read_csv(file_path)
            st.session_state.data = loaded_df.to_dict(orient='records')
            st.toast(f"📂 {market} 시장의 최근 백업 데이터를 불러왔습니다.", icon="✅")
        except Exception as e:
            st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
    else:
        st.warning(f"💾 {market} 시장에 자동 저장된 데이터가 존재하지 않습니다.")

# 검색 시작 로직 처리
if btn_search:
    st.session_state.data = []  
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
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
                df = pd.DataFrame(st.session_state.data)
                column_order = [
                    "rank", "symbol", "name", "data_date", "market_cap", "price", 
                    "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
                ]
                available_cols = [c for c in column_order if c in df.columns]
                df = df[available_cols]
                table_placeholder.dataframe(df, use_container_width=True)
                
            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
            elif m_type == "error":
                st.error(msg["text"])
                break
                
            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
                
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                break

# 결과 출력 레이아웃
if st.session_state.data:
    st.subheader("📊 분석 결과")
    final_df = pd.DataFrame(st.session_state.data)
    
    column_order = [
        "rank", "symbol", "name", "data_date", "market_cap", "price", 
        "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
    ]
    available_cols = [c for c in column_order if c in final_df.columns]
    final_df = final_df[available_cols]
    
    st.dataframe(
        final_df,
        use_container_width=True,
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
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")