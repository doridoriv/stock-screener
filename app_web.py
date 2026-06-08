import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE, CACHE_DIR

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

opt_fundamental = True
opt_peak = True

if "data" not in st.session_state:
    st.session_state.data = []

if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

col1, col2, col3, col_empty = st.columns([1.2, 1.2, 1.2, 5])

with col1:
    btn_search = st.button("🔍 검색", use_container_width=True)

with col2:
    btn_load = st.button("📂 불러오기", use_container_width=True)

with col3:
    btn_stop = st.button("⏹ 검색 중지", use_container_width=True)

if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    st.toast("⏹ 스크리닝 중지 신호를 보냈습니다.", icon="⚠️")

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

def style_screener_dataframe(df, market_type):
    formatted_df = df.copy()
    is_us = (market_type == "미국")
    
    if "symbol" in formatted_df.columns and "name" in formatted_df.columns:
        urls = []
        for idx, row in formatted_df.iterrows():
            sym = str(row["symbol"]).strip()
            row_name = str(row["name"]).strip()
            
            if is_us:
                if sym == "BRK-B":
                    base_url = "https://m.stock.naver.com/worldstock/stock/BRKb/total"
                else:
                    nyse_tickers = {
                        "BRK-B", "WMT", "LLY", "JPM", "V", "XOM", "UNH", "MA", "HD", "PG",
                        "ORCL", "BAC", "CVX", "KO", "PEP", "CRM", "MCD", "IBM", "TMO", "ACN",
                        "WFC", "AXP", "GE", "NKE", "LIN", "PM", "ABT", "CAT", "TXN", "NOW", "MS",
                        "DIS", "HON", "UNP", "GS", "PFE", "RTX", "LOW", "NEE", "SPGI", "COP",
                        "GEV", "LMT", "TJX", "BLK", "T", "ABBV", "GILD", "C", "BMY"
                    }
                    if sym in nyse_tickers:
                        suffix = ".N"
                    else:
                        suffix = ".O"
                    base_url = f"https://m.stock.naver.com/worldstock/stock/{sym}{suffix}/total"
                url = f"{base_url}?ticker={sym}&name={row_name}"
            else:
                code_str = str(sym).zfill(6)
                url = f"https://finance.naver.com/item/main.naver?code={code_str}&ticker={code_str}&name={row_name}"
            urls.append(url)
        formatted_df["symbol"] = urls
        formatted_df["name"] = urls
            
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI", "per": "PER", "pbr": "PBR", "roe": "ROE", "peg": "PEG", "eps3y": "EPS3Y", "cagr": "CAGR"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)
    
    styler = formatted_df.style
    format_dict = {}
    if "순위" in formatted_df.columns: format_dict["순위"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "시가총액(억)" in formatted_df.columns: format_dict["시가총액(억)"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "-"
    if "현재가" in formatted_df.columns: format_dict["현재가"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "200일선" in formatted_df.columns: format_dict["200일선"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점" in formatted_df.columns: format_dict["최고점"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점대비" in formatted_df.columns: format_dict["최고점대비"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "200일괴리율(%)" in formatted_df.columns: format_dict["200일괴리율(%)"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "RSI" in formatted_df.columns: format_dict["RSI"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PER" in formatted_df.columns: format_dict["PER"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PBR" in formatted_df.columns: format_dict["PBR"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "ROE" in formatted_df.columns: format_dict["ROE"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
    if "PEG" in formatted_df.columns: format_dict["PEG"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "EPS3Y" in formatted_df.columns: format_dict["EPS3Y"] = lambda x: str(x) if pd.notna(x) else "-"
    if "CAGR" in formatted_df.columns: format_dict["CAGR"] = lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0 else f"{x:.1f}%" if pd.notna(x) else "-"
        
    styler = styler.format(format_dict)
    styler = styler.set_properties(**{'text-align': 'center', 'white-space': 'nowrap'})
    
    # 지표별 조건부 스위칭 색상 테이블 바인딩
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
        
    if "PER" in formatted_df.columns: styler = styler.map(color_per, subset=["PER"])
    if "PBR" in formatted_df.columns: styler = styler.map(color_pbr, subset=["PBR"])
    if "PEG" in formatted_df.columns: styler = styler.map(color_peg, subset=["PEG"])
    if "ROE" in formatted_df.columns: styler = styler.map(color_roe, subset=["ROE"])
    if "RSI" in formatted_df.columns: styler = styler.map(color_rsi, subset=["RSI"])
        
    target_cols = [c for c in ["최고점대비", "200일괴리율(%)"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
    return styler

link_config = {
    "순위": st.column_config.NumberColumn("순위", width="small", format="%d"),
    "티커": st.column_config.LinkColumn("티커", display_text=r"ticker=([^&]*)", width="small"),
    "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]*)", width="medium"),
    "시가총액(억)": st.column_config.NumberColumn("시가총액(억)", width="small"),
    "현재가": st.column_config.NumberColumn("현재가", width="small"),
    "최고점": st.column_config.NumberColumn("최고점", width="small"),
    "최고점대비": st.column_config.NumberColumn("최고점대비", width="small"),
    "200일선": st.column_config.NumberColumn("200일선", width="small"),
    "200일괴리율(%)": st.column_config.NumberColumn("200일괴리율(%)", width="small"),
    "RSI": st.column_config.NumberColumn("RSI", width="small"),
    "PER": st.column_config.NumberColumn("PER", width="small"),
    "PBR": st.column_config.NumberColumn("PBR", width="small"),
    "ROE": st.column_config.NumberColumn("ROE", width="small"),
    "PEG": st.column_config.NumberColumn("PEG", width="small"),
    "EPS3Y": st.column_config.TextColumn("EPS3Y", width="small"),
    "CAGR": st.column_config.NumberColumn("CAGR", width="small")
}

if btn_search:
    st.session_state.data = []  
    progress_bar = st.progress(0)
    status_text = st.empty()
    header_placeholder = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
    st.session_state.stop_event = threading.Event()
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    current_stop_event = st.session_state.stop_event
    
    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, top_n, app_queue, lambda: current_stop_event.is_set(), opt_fundamental, opt_peak, us_market_cap_data),
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
                column_order = ["rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr"]
                available_cols = [c for c in column_order if c in df.columns]
                
                if "market_cap" in df.columns and len(df) > 0:
                    df = df.sort_values(by="market_cap", ascending=False)
                    df["rank"] = range(1, len(df) + 1)
                
                display_df = df[available_cols]
                styled_live_df = style_screener_dataframe(display_df, market)
                
                date_val = df["data_date"].iloc[0] if "data_date" in df.columns and len(df) > 0 else "-"
                header_placeholder.markdown(f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><h3>📊 실시간 분석 결과</h3><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>", unsafe_allow_html=True)
                
                table_placeholder.dataframe(
                    styled_live_df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config=link_config,
                    selection_mode="row"
                )
                
            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                header_placeholder.empty()
                table_placeholder.empty()
                
                if st.session_state.data:
                    final_save_df = pd.DataFrame(st.session_state.data)
                    if "market_cap" in final_save_df.columns and len(final_save_df) > 0:
                        final_save_df = final_save_df.sort_values(by="market_cap", ascending=False)
                        final_save_df["rank"] = range(1, len(final_save_df) + 1)
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
            elif m_type == "error":
                st.error(msg["text"])
                header_placeholder.empty()
                table_placeholder.empty()
                break
                
            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
                header_placeholder.empty()
                table_placeholder.empty()
                
                if st.session_state.data:
                    final_save_df = pd.DataFrame(st.session_state.data)
                    if "market_cap" in final_save_df.columns and len(final_save_df) > 0:
                        final_save_df = final_save_df.sort_values(by="market_cap", ascending=False)
                        final_save_df["rank"] = range(1, len(final_save_df) + 1)
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding='utf-8-sig')
                break
                
        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                break

if st.session_state.data:
    final_df = pd.DataFrame(st.session_state.data)
    date_val = final_df["data_date"].iloc[0] if "data_date" in final_df.columns and len(final_df) > 0 else "-"
    
    head_col1, head_col2 = st.columns([6, 2])
    with head_col1:
        st.subheader("📊 분석 결과")
    with head_col2:
        st.markdown(f"<div style='text-align: right; margin-top: 10px;'><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>", unsafe_allow_html=True)
        
    column_order = ["rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr"]
    available_cols = [c for c in column_order if c in final_df.columns]
    
    if "market_cap" in final_df.columns and len(final_df) > 0:
        final_df = final_df.sort_values(by="market_cap", ascending=False)
        final_df["rank"] = range(1, len(final_df) + 1)
        
    display_final_df = final_df[available_cols]
    styled_final_df = style_screener_dataframe(display_final_df, market)
    
    st.dataframe(
        styled_final_df,
        use_container_width=True,
        height=650,
        hide_index=True,
        column_config=link_config,
        selection_mode="row"
    )
    
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI", "per": "PER", "pbr": "PBR", "roe": "ROE", "peg": "PEG", "eps3y": "EPS3Y", "cagr": "CAGR"
    }
    csv_df = display_final_df.rename(columns=rename_dict)
    csv = csv_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")