import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

# Streamlit 백그라운드 스레드 경고를 완벽히 제거하기 위한 컨텍스트 주입 함수를 임포트합니다.
from streamlit.runtime.scriptrunner import add_script_run_context

import analyzer
from config import APP_TITLE, CACHE_DIR

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

# 사이드바 체크박스를 삭제하고 항상 기본 활성화(True) 상태로 고정
opt_fundamental = True
opt_peak = True

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []

# 검색 중지 연동을 위한 전역 스레드 이벤트 객체 세션 초기화
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

# ==============================================================================
# 버튼 3개를 본문 상단 툴바 형태로 가로 배치 (글씨 잘림 방지 및 우측 여백 제어)
# ==============================================================================
col1, col2, col3, col_empty = st.columns([1.2, 1.2, 1.2, 5])

with col1:
    btn_search = st.button("🔍 검색", use_container_width=True)

with col2:
    btn_load = st.button("📂 불러오기", use_container_width=True)

with col3:
    btn_stop = st.button("⏹ 검색 중지", use_container_width=True)

# 검색 중지 버튼 클릭 시 작동하는 시각적 피드백 및 백엔드 로직
if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    st.toast("⏹ 스크리닝 중지 신호를 보냈습니다.", icon="⚠️")

# 불러오기 버튼 클릭 시 자동 저장된 백업 데이터를 파일에서 읽어오는 로직
if btn_load:
    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
    if os.path.exists(file_path):
        try:
            loaded_df = pd.read_csv(file_path)
            st.session_state.data = loaded_df.to_dict(orient='records')
            st.toast(f"📂 {market} 시장의 최근 자동저장 데이터를 불러왔습니다.", icon="✅")
        except Exception as e:
            st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
    else:
        st.warning(f"💾 {market} 시장에 자동 저장된 백업 데이터가 존재하지 않습니다.")

# ==============================================================================
# 데이터 포맷팅 및 스타일러 정의
# ==============================================================================
def style_screener_dataframe(df, market_type):
    formatted_df = df.copy()
    is_us = (market_type == "미국")
    
    if "market_cap" in formatted_df.columns:
        formatted_df["market_cap"] = formatted_df["market_cap"].apply(
            lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "N/A"
        )
    if "price" in formatted_df.columns:
        formatted_df["price"] = formatted_df["price"].apply(
            lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
        )
    if "ma200" in formatted_df.columns:
        formatted_df["ma200"] = formatted_df["ma200"].apply(
            lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
        )
    if "diff" in formatted_df.columns:
        formatted_df["diff"] = formatted_df["diff"].apply(
            lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%"
        )
    if "rsi" in formatted_df.columns:
        def format_rsi(v):
            if pd.isna(v): return "-"
            if v >= 70: return f"{v:.1f} (과열)"
            elif v <= 30: return f"{v:.1f} (과매도)"
            elif v >= 50: return f"{v:.1f} (보통)"
            else: return f"{v:.1f} (침체)"
        formatted_df["rsi"] = formatted_df["rsi"].apply(format_rsi)
        
    for col in formatted_df.columns:
        formatted_df[col] = formatted_df[col].astype(str)
        
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)
    
    styler = formatted_df.style.set_properties(**{
        'text-align': 'center',
        'white-space': 'nowrap'
    })
    
    def apply_strict_color_rules(val):
        if isinstance(val, str):
            if "+" in val or "🔴" in val:
                return "color: #D32F2F; font-weight: bold;"
            if "-" in val or "🔵" in val:
                return "color: #1976D2; font-weight: bold;"
        return "color: #212121;"
        
    target_cols = [c for c in ["최고점대비", "200일괴리율(%)"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
        
    return styler

# 검색 버튼 트래킹 및 메인 코어 루프 엔진 실행
if btn_search:
    st.session_state.data = []  
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
    st.session_state.stop_event = threading.Event()
    
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    # [핵심 수정] 스레드가 우회 참조할 수 있도록 세션 스토리지의 이벤트 객체를 로컬 변수로 바인딩합니다.
    current_stop_event = st.session_state.stop_event
    
    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(
            market, 
            top_n, 
            app_queue, 
            lambda: current_stop_event.is_set(), # st.session_state 대신 로컬 변수를 참조하여 경고 근절
            opt_fundamental, 
            opt_peak, 
            us_market_cap_data
        ),
        daemon=True
    )
    # [핵심 수정] 백그라운드 스레드에 Streamlit 실행 환경 컨텍스트를 명시적으로 주입합니다.
    add_script_run_context(worker_thread)
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
                
                styled_live_df = style_screener_dataframe(df, market)
                table_placeholder.dataframe(styled_live_df, width='stretch', hide_index=True)
                
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

# 최종 결과 출력부
if st.session_state.data:
    st.subheader("📊 분석 결과")
    final_df = pd.DataFrame(st.session_state.data)
    
    column_order = [
        "rank", "symbol", "name", "data_date", "market_cap", "price", 
        "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
    ]
    available_cols = [c for c in column_order if c in final_df.columns]
    final_df = final_df[available_cols]
    
    styled_final_df = style_screener_dataframe(final_df, market)
    
    st.dataframe(
        styled_final_df,
        width='stretch',
        height=650,
        hide_index=True
    )
    
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
    }
    csv_df = final_df.rename(columns=rename_dict)
    csv = csv_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")