import streamlit as st
import pandas as pd
import queue
import threading
import os
import re
import time
from datetime import datetime
import yfinance as yf

from config import APP_TITLE, COL_INFOS, CACHE_DIR
import analyzer

# ==============================================================================
# 1. 전역 세션 상태(Session State) 관리부
# ==============================================================================
if "us_market_cap_data" not in st.session_state:
    st.session_state.us_market_cap_data = analyzer.load_us_market_cap_cache()

if "current_session_data" not in st.session_state:
    st.session_state.current_session_data = []

if "is_running" not in st.session_state:
    st.session_state.is_running = False

if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

# ==============================================================================
# 2. 기존 코어 비즈니스 메소드 이관 정의
# ==============================================================================
def get_csv_filename(market_val):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if market_val == "미국" else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

# ==============================================================================
# 3. Streamlit 웹 인터페이스 및 컨트롤 레이아웃 구성
# ==============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(f"🚀 {APP_TITLE}")

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns([1.5, 2, 1.5, 1.5, 1.5])

with col_m1:
    market_var = st.selectbox("시장 선택", ["미국", "한국"], index=0)

with col_m2:
    top_n_val = st.slider("검색 순위 범위", min_value=1, max_value=100, value=50)

with col_m3:
    btn_run = st.button("🔄 새로 검색", use_container_width=True, type="primary")

with col_m4:
    btn_load = st.button("📂 불러오기", use_container_width=True)

with col_m5:
    btn_stop = st.button("⏹ 중지", use_container_width=True, disabled=not st.session_state.is_running)

if btn_stop:
    st.session_state.stop_requested = True
    st.warning("사용자가 중지를 요청했습니다. 현재 종목까지만 처리하고 종료합니다...")

if btn_load:
    filename = get_csv_filename(market_var)
    if not os.path.exists(filename):
        st.error("오늘 저장된 스크리닝 결과가 없습니다.\n[새로 검색]을 먼저 진행해 주세요.")
    else:
        try:
            df_loaded = pd.read_csv(filename, encoding='utf-8-sig')
            st.session_state.current_session_data = df_loaded.to_dict('records')
            st.success(f"📂 저장된 결과를 성공적으로 불러왔습니다! ({len(st.session_state.current_session_data)} 종목)")
        except Exception as e:
            st.error(f"파일을 불러오는 중 오류가 발생했습니다:\n{e}")

# ==============================================================================
# 4. 실시간 스크리닝 백그라운드 스레드 및 모니터링 엔진
# ==============================================================================
if btn_run:
    st.session_state.is_running = True
    st.session_state.stop_requested = False
    st.session_state.current_session_data = []
    
    q = queue.Queue()
    stop_fn = lambda: st.session_state.stop_requested
    
    threading.Thread(
        target=analyzer.screening_worker,
        args=(market_var, top_n_val, q, stop_fn, True, True, st.session_state.us_market_cap_data),
        daemon=True
    ).start()
    
    progress_bar = st.progress(0)
    status_label = st.empty()
    table_placeholder = st.empty()
    
    while True:
        try:
            msg = q.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "progress":
                p_val = msg["value"]
                progress_bar.progress(int(p_val) / 100 if p_val <= 100 else 1.0)
                status_label.text(msg["text"])
                
            elif m_type == "data":
                st.session_state.current_session_data.append(msg["data"])
                
            elif m_type in ["done", "stopped"]:
                if st.session_state.current_session_data and not st.session_state.stop_requested:
                    try:
                        df_backup = pd.DataFrame(st.session_state.current_session_data)
                        df_backup.to_csv(get_csv_filename(market_var), index=False, encoding='utf-8-sig')
                    except:
                        pass
                
                st.session_state.is_running = False
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                if m_type == "stopped":
                    st.warning(f"중지됨: 총 {msg['count']}개 종목까지만 분석되었습니다.")
                else:
                    st.success(f"완료! (기준일: {today_str}) 총 {msg['count']}개 종목 분석 완료 (자동 백업됨)")
                break
                
            elif m_type == "error":
                st.session_state.is_running = False
                st.error(msg["text"])
                break
                
        except queue.Empty:
            time.sleep(0.05)
            
    st.session_state.is_running = False
    st.rerun()

# ==============================================================================
# 5. 데이터 가공 및 테이블 인젝션
# ==============================================================================
if st.session_state.current_session_data:
    raw_records = st.session_state.current_session_data
    is_us = (market_var == "미국")
    
    display_df = pd.DataFrame(raw_records)
    column_keys = ["rank", "symbol", "name", "data_date", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"]
    display_df = display_df[column_keys]
    
    # [수정] gui.py 결과 렌더링 시에도 시가총액 순위(rank) 기준으로 오름차순 정렬을 강제 적용합니다.
    if "rank" in display_df.columns:
        display_df = display_df.sort_values(by="rank", ascending=True)
        
    col_headers = [col["text"] for col in COL_INFOS]
    display_df.columns = col_headers
    
    peak_diff_column_name = COL_INFOS[7]["text"]
    diff_column_name = COL_INFOS[9]["text"]
    
    styler = display_df.style
    
    def format_market_cap(x):
        return f"{x:,}억" if pd.notna(x) and x > 0 else "N/A"
    
    def format_price(x):
        if pd.isna(x): return "-"
        return f"${x:,.2f}" if is_us else f"{int(x):,}원"
        
    def format_peak(x):
        if pd.isna(x) or x == "비활성": return "비활성"
        try:
            val = float(x)
            return f"${val:,.2f}" if is_us else f"{int(val):,}원"
        except:
            return str(x)
            
    def format_peak_diff(x):
        if pd.isna(x) or x == "비활성": return "비활성"
        try:
            val = float(x)
            return f"+{val:.2f}%" if val > 0 else f"{val:.2f}%"
        except:
            return str(x)
            
    def format_ma200(x):
        if pd.isna(x): return "-"
        return f"${x:,.2f}" if is_us else f"{int(x):,}원"
        
    def format_diff(x):
        if pd.isna(x): return "0.00%"
        try:
            val = float(x)
            return f"+{val:.2f}%" if val > 0 else f"{val:.2f}%"
        except:
            return "0.00%"
            
    def format_rsi(x):
        if pd.isna(x): return "-"
        try:
            rsi_val = float(x)
            if rsi_val >= 70: return f"{rsi_val:.1f} (과열)"
            elif rsi_val <= 30: return f"{rsi_val:.1f} (과매도)"
            elif rsi_val >= 50: return f"{rsi_val:.1f} (보통)"
            else: return f"{rsi_val:.1f} (침체)"
        except:
            return str(x)
            
    styler = styler.format({
        COL_INFOS[4]["text"]: format_market_cap,
        COL_INFOS[5]["text"]: format_price,
        COL_INFOS[6]["text"]: format_peak,
        COL_INFOS[7]["text"]: format_peak_diff,
        COL_INFOS[8]["text"]: format_ma200,
        COL_INFOS[9]["text"]: format_diff,
        COL_INFOS[10]["text"]: format_rsi,
        COL_INFOS[11]["text"]: lambda x: analyzer.get_per_grade(x),
        COL_INFOS[12]["text"]: lambda x: analyzer.get_pbr_grade(x)
    })
    
    styler = styler.set_properties(**{'text-align': 'center', 'white-space': 'nowrap'})
    
    def apply_strict_color_rules(val):
        try:
            v = float(val)
            if v > 0: return "color: #D32F2F; font-weight: bold;"
            elif v < 0: return "color: #1976D2; font-weight: bold;"
        except:
            if isinstance(val, str):
                if "+" in val: return "color: #D32F2F; font-weight: bold;"
                if "-" in val: return "color: #1976D2; font-weight: bold;"
        return "color: #212121;"
        
    styler = styler.map(apply_strict_color_rules, subset=[peak_diff_column_name, diff_column_name])
        
    gui_column_config = {}
    for col in COL_INFOS:
        col_text = col["text"]
        width = col.get("width", 100)
        gui_column_config[col_text] = st.column_config.Column(col_text, width=width)

    st.dataframe(
        styler,
        width='content',
        height=680,
        hide_index=True,
        selection_mode="row",
        column_config=gui_column_config
    )
}