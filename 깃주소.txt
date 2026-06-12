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

if "us_market_cap_data" not in st.session_state:
    st.session_state.us_market_cap_data = analyzer.load_us_market_cap_cache()

if "current_session_data" not in st.session_state:
    st.session_state.current_session_data = []

if "is_running" not in st.session_state:
    st.session_state.is_running = False

if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

def get_csv_filename(market_val):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if market_val == "미국" else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(f"🚀 {APP_TITLE}")

st.markdown("""
<style>
[data-testid="stDataFrame"] div[role="gridcell"],
[data-testid="stDataFrame"] div[role="columnheader"] {
    white-space: nowrap !important;
}
</style>
""", unsafe_allow_html=True)

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

if st.session_state.current_session_data:
    raw_records = st.session_state.current_session_data
    is_us = (market_var == "미국")
    
    display_df = pd.DataFrame(raw_records)
    column_keys = ["rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr"]
    available_keys = [k for k in column_keys if k in display_df.columns]
    display_df = display_df[available_keys]
    
    date_val = raw_records[0].get("data_date", "-") if len(raw_records) > 0 else "-"
    
    head_col1, head_col2 = st.columns([6, 2])
    with head_col1:
        st.subheader("📊 분석 결과")
    with head_col2:
        st.markdown(f"<div style='text-align: right; margin-top: 10px;'><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>", unsafe_allow_html=True)
        
    col_headers = [col["text"] for col in COL_INFOS if col["id"] in available_keys]
    display_df.columns = col_headers
    
    styler = display_df.style
    
    format_dict = {}
    if "순위" in display_df.columns: format_dict["순위"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "시가총액" in display_df.columns: format_dict["시가총액"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "-"
    if "현재가" in display_df.columns: format_dict["현재가"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점" in display_df.columns: format_dict["최고점"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점대비" in display_df.columns: format_dict["최고점대비"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "200일선" in display_df.columns: format_dict["200일선"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "200일괴리율" in display_df.columns: format_dict["200일괴리율"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "RSI" in display_df.columns: format_dict["RSI"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PER" in display_df.columns: format_dict["PER"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PBR" in display_df.columns: format_dict["PBR"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "ROE" in display_df.columns: format_dict["ROE"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
    if "PEG" in display_df.columns: format_dict["PEG"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "EPS3Y" in display_df.columns: format_dict["EPS3Y"] = lambda x: str(x) if pd.notna(x) else "-"
    if "CAGR" in display_df.columns: format_dict["CAGR"] = lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0 else f"{x:.1f}%" if pd.notna(x) else "-"

    styler = styler.format(format_dict)
    styler = styler.set_properties(**{'text-align': 'center', 'white-space': 'nowrap'})
    
    def color_per(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v <= 5: return "color: #0D47A1; font-weight: bold;"
            elif v <= 10: return "color: #1976D2; font-weight: bold;"
            elif v <= 15: return "color: #0288D1; font-weight: bold;"
            elif v <= 20: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_pbr(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v <= 0.5: return "color: #0D47A1; font-weight: bold;"
            elif v <= 1.0: return "color: #1976D2; font-weight: bold;"
            elif v <= 2.0: return "color: #0288D1; font-weight: bold;"
            elif v <= 3.0: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_peg(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v <= 0.5: return "color: #0D47A1; font-weight: bold;"
            elif v <= 1.0: return "color: #1976D2; font-weight: bold;"
            elif v <= 1.5: return "color: #0288D1; font-weight: bold;"
            elif v <= 2.0: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_roe(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v >= 20: return "color: #0D47A1; font-weight: bold;"
            elif v >= 15: return "color: #1976D2; font-weight: bold;"
            elif v >= 10: return "color: #0288D1; font-weight: bold;"
            elif v >= 5: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_rsi(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v >= 70: return "color: #D32F2F; font-weight: bold;"
            elif v >= 50: return "color: #E65100; font-weight: bold;"
            elif v >= 30: return "color: #1976D2; font-weight: bold;"
            else: return "color: #0D47A1; font-weight: bold;"
        except: return ""

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
        
    if "PER" in display_df.columns: styler = styler.map(color_per, subset=["PER"])
    if "PBR" in display_df.columns: styler = styler.map(color_pbr, subset=["PBR"])
    if "PEG" in display_df.columns: styler = styler.map(color_peg, subset=["PEG"])
    if "ROE" in display_df.columns: styler = styler.map(color_roe, subset=["ROE"])
    if "RSI" in display_df.columns: styler = styler.map(color_rsi, subset=["RSI"])
        
    target_cols = [c for c in ["최고점대비", "200일괴리율"] if c in display_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
        
    st.dataframe(
        styler,
        use_container_width=True,
        height=680,
        hide_index=True,
        selection_mode="row"
    )