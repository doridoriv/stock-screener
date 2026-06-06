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

# 사이드바 설정
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


# ==============================================================================
# HTML 테이블 렌더러
# st.dataframe은 Canvas 기반 Shadow DOM이라 외부 CSS가 전혀 침투하지 못합니다.
# st.html()로 순수 HTML <table>을 직접 렌더링하여 컬럼 너비를 완전 제어합니다.
# ==============================================================================

# 컬럼 헤더 라벨 / 너비(px) / 정렬 정의
COL_DEFS = [
    ("rank",       "순위",          48,  "center"),
    ("symbol",     "티커",          72,  "center"),
    ("name",       "종목명",       155,  "left"),
    ("data_date",  "기준일",        88,  "center"),
    ("market_cap", "시가총액(억)", 105,  "right"),
    ("price",      "현재가",        88,  "right"),
    ("peak",       "최고점",        88,  "right"),
    ("peak_diff",  "최고점대비",    88,  "center"),
    ("ma200",      "200일선",       88,  "right"),
    ("diff",       "200일괴리율",  100,  "center"),
    ("rsi",        "RSI(14)",      100,  "center"),
    ("per",        "PER 등급",     125,  "left"),
    ("pbr",        "PBR 등급",     125,  "left"),
]

def build_url(sym, name, is_us):
    sym = str(sym).strip()
    name = str(name).strip()
    if is_us:
        if sym == "BRK-B":
            base = "https://m.stock.naver.com/worldstock/stock/BRKb/total"
        else:
            nyse = {
                "WMT","LLY","JPM","V","XOM","UNH","MA","HD","PG",
                "ORCL","BAC","CVX","KO","PEP","CRM","MCD","IBM","TMO","ACN",
                "WFC","AXP","GE","NKE","LIN","PM","ABT","CAT","TXN","MS",
                "DIS","HON","UNP","GS","PFE","RTX","LOW","NEE","SPGI","COP",
                "GEV","LMT","TJX","BLK","T","ABBV","GILD","C","BMY"
            }
            suffix = ".N" if sym in nyse else ".O"
            base = f"https://m.stock.naver.com/worldstock/stock/{sym}{suffix}/total"
        return base
    else:
        code = str(sym).zfill(6)
        return f"https://finance.naver.com/item/main.naver?code={code}"

def fmt_value(key, val, is_us):
    """각 컬럼 키에 맞는 표시 문자열과 색상 반환 → (text, color)"""
    color = "#212121"
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A", color

    if key == "rank":
        return str(int(val)), color

    if key == "market_cap":
        return (f"{int(val):,}억" if val > 0 else "N/A"), color

    if key in ("price", "ma200", "peak"):
        if is_us:
            return f"${float(val):,.2f}", color
        else:
            return f"{int(val):,}원", color

    if key in ("peak_diff", "diff"):
        v = float(val)
        text = f"+{v:.2f}%" if v > 0 else f"{v:.2f}%"
        color = "#D32F2F" if v > 0 else ("#1976D2" if v < 0 else "#212121")
        return text, color

    if key == "rsi":
        v = float(val)
        if v >= 70:   label = "과열"
        elif v <= 30: label = "과매도"
        elif v >= 50: label = "보통"
        else:         label = "침체"
        return f"{v:.1f} ({label})", color

    if key == "per":
        return analyzer.get_per_grade(val), color

    if key == "pbr":
        return analyzer.get_pbr_grade(val), color

    return str(val), color


TABLE_CSS = """
<style>
.screener-wrap {
    overflow-x: auto;
    overflow-y: auto;
    max-height: 650px;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
}
.screener-table {
    border-collapse: collapse;
    font-size: 13px;
    font-family: 'Noto Sans KR', sans-serif;
    table-layout: fixed;
    width: max-content;
}
.screener-table thead th {
    position: sticky;
    top: 0;
    background: #f5f7fa;
    border-bottom: 2px solid #d0d7de;
    padding: 6px 8px;
    white-space: nowrap;
    font-weight: 600;
    color: #24292f;
    z-index: 2;
}
.screener-table tbody tr:hover {
    background: #f0f4ff;
}
.screener-table tbody tr:nth-child(even) {
    background: #fafafa;
}
.screener-table tbody tr:nth-child(even):hover {
    background: #f0f4ff;
}
.screener-table td {
    padding: 5px 8px;
    border-bottom: 1px solid #ebebeb;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.screener-table a {
    color: #1976D2;
    text-decoration: none;
    font-weight: 500;
}
.screener-table a:hover {
    text-decoration: underline;
}
</style>
"""

def render_html_table(records, market_type):
    is_us = (market_type == "미국")

    # 헤더
    header_cells = ""
    for _, label, width, align in COL_DEFS:
        header_cells += f'<th style="width:{width}px;text-align:{align};">{label}</th>'

    # 바디
    rows_html = ""
    for row in records:
        cells = ""
        url = build_url(row.get("symbol",""), row.get("name",""), is_us)
        for key, label, width, align in COL_DEFS:
            val = row.get(key)
            text, color = fmt_value(key, val, is_us)

            if key == "symbol":
                sym_display = str(row.get("symbol","")).strip()
                cells += (f'<td style="width:{width}px;text-align:{align};color:{color};">'
                          f'<a href="{url}" target="_blank">{sym_display}</a></td>')
            elif key == "name":
                name_display = str(row.get("name","")).strip()
                cells += (f'<td style="width:{width}px;text-align:{align};color:{color};">'
                          f'<a href="{url}" target="_blank">{name_display}</a></td>')
            else:
                cells += (f'<td style="width:{width}px;text-align:{align};">'
                          f'<span style="color:{color};font-weight:{"bold" if color != "#212121" else "normal"};">'
                          f'{text}</span></td>')
        rows_html += f"<tr>{cells}</tr>"

    html = f"""
{TABLE_CSS}
<div class="screener-wrap">
  <table class="screener-table">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""
    return html


# ==============================================================================
# 검색 실행
# ==============================================================================
if btn_search:
    st.session_state.data = []

    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()

    app_queue = queue.Queue()
    st.session_state.stop_event = threading.Event()

    us_market_cap_data = analyzer.load_us_market_cap_cache()
    current_stop_event = st.session_state.stop_event

    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, top_n, app_queue,
              lambda: current_stop_event.is_set(),
              opt_fundamental, opt_peak, us_market_cap_data),
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
                table_placeholder.html(render_html_table(st.session_state.data, market))

            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                table_placeholder.empty()
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break

            elif m_type == "error":
                st.error(msg["text"])
                table_placeholder.empty()
                break

            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
                table_placeholder.empty()
                if st.session_state.data:
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    pd.DataFrame(st.session_state.data).to_csv(file_path, index=False, encoding='utf-8-sig')
                break

        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                break


# ==============================================================================
# 최종 결과 출력
# ==============================================================================
if st.session_state.data:
    st.subheader("📊 분석 결과")
    st.html(render_html_table(st.session_state.data, market))

    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
    }
    final_df = pd.DataFrame(st.session_state.data)
    column_order = ["rank","symbol","name","data_date","market_cap","price",
                    "peak","peak_diff","ma200","diff","rsi","per","pbr"]
    available_cols = [c for c in column_order if c in final_df.columns]
    csv_df = final_df[available_cols].rename(columns=rename_dict)
    csv = csv_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")
