import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import (
    APP_TITLE, 
    CACHE_DIR, 
    DEFAULT_US_TICKERS, 
    DEFAULT_KOSPI_TICKERS, 
    KOSPI_NAME_MAP, 
    DEFAULT_KOSDAQ_TICKERS, 
    KOSDAQ_NAME_MAP
)

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
        st.success("⏹ 검색 중지 요청이 전송되었습니다.")

def make_link(row, market_val):
    sym = str(row['symbol'])
    if "한국" in market_val or ".KS" in sym or ".KQ" in sym:
        code = sym.split('.')[0]
        return f"https://finance.naver.com/item/main.naver?code={code}"
    else:
        return f"https://finance.yahoo.com/quote/{sym}"

if btn_search:
    st.session_state.data = []
    app_queue = queue.Queue()
    st.session_state.stop_event = threading.Event()
    
    if market == "미국":
        tickers = [{"rank": i+1, "symbol": t, "name": analyzer.US_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_US_TICKERS[:top_n])]
    elif market == "한국(코스피)":
        tickers = [{"rank": i+1, "symbol": t, "name": KOSPI_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_KOSPI_TICKERS[:top_n])]
    elif market == "한국(코스닥)":
        tickers = [{"rank": i+1, "symbol": t, "name": KOSDAQ_NAME_MAP.get(t, t), "market_cap": 0} for i, t in enumerate(DEFAULT_KOSDAQ_TICKERS[:top_n])]
        
    t_worker = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, tickers, app_queue, st.session_state.stop_event, opt_fundamental, opt_peak)
    )
    t_worker.start()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    collected_count = 0
    while t_worker.is_alive() or not app_queue.empty():
        if st.session_state.stop_event.is_set():
            break
        try:
            msg = app_queue.get(timeout=0.5)
            if msg.get("type") == "data":
                st.session_state.data.append(msg["data"])
                collected_count += 1
                progress_val = min(collected_count / len(tickers), 1.0)
                progress_bar.progress(progress_val)
                status_text.text(f"⏳ 분석 중... ({collected_count}/{len(tickers)}) - {msg['data']['name']}")
            elif msg.get("type") == "done":
                break
        except queue.Empty:
            continue
            
    t_worker.join()
    status_text.text("✅ 분석 완료!")
    progress_bar.empty()

if btn_load:
    csv_path = os.path.join(CACHE_DIR, f"screener_data_{market}.csv")
    if os.path.exists(csv_path):
        st.session_state.data = pd.read_csv(csv_path).to_dict(orient="records")
        st.success(f"📂 로컬 캐시 데이터 로드 완료! ({market})")
    else:
        st.error(f"⚠️ 저장된 캐시 파일이 없습니다: {csv_path}")

if st.session_state.data:
    final_df = pd.DataFrame(st.session_state.data)
    date_val = final_df["data_date"].iloc[0] if "data_date" in final_df.columns else datetime.now().strftime('%Y-%m-%d')
    
    st.markdown(f"<div style='text-align: right;'><span style='background-color: #E5E7EB; padding: 5px 10px; border-radius: 5px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>", unsafe_allow_html=True)
    
    column_order = ["rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr"]
    available_cols = [c for c in column_order if c in final_df.columns]
    
    if "market_cap" in final_df.columns and len(final_df) > 0:
        final_df = final_df.sort_values(by="market_cap", ascending=False)
        final_df["rank"] = range(1, len(final_df) + 1)
        
    final_df['link'] = final_df.apply(lambda r: make_link(r, market), axis=1)
    
    if 'link' not in available_cols:
        available_cols.insert(3, 'link')
        
    display_final_df = final_df[available_cols]
    
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명", "link": "링크",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "이격도",
        "rsi": "RSI", "per": "PER", "pbr": "PBR", "roe": "ROE",
        "peg": "PEG", "eps3y": "EPS 추이", "cagr": "성장률"
    }
    
    display_final_df = display_final_df.rename(columns=rename_dict)
    
    link_config = {
        "링크": st.column_config.LinkColumn("네이버/야후 링크", display_text="보기")
    }
    
    st.dataframe(
        display_final_df,
        use_container_width=True,
        height=650,
        hide_index=True,
        column_config=link_config,
        selection_mode="row"
    )