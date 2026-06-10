import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

opt_fundamental = st.sidebar.checkbox("기본적 분석 포함 (PER/PBR)", value=True)
opt_peak = st.sidebar.checkbox("고점 대비 하락율 포함", value=True)

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []

# 검색 버튼
if st.sidebar.button("🔄 스크리닝 시작"):
    st.session_state.data = []  
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
    stop_event = threading.Event()
    
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(
            market, 
            top_n, 
            app_queue, 
            lambda: stop_event.is_set(), 
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
                table_placeholder.dataframe(df, use_container_width=True)
                
            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                break
                
            elif m_type == "error":
                st.error(msg["text"])
                break
                
            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
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
    st.info("사이드바의 [스크리닝 시작] 버튼을 눌러 분석을 시작하세요.")