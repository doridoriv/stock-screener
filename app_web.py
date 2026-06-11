import os
import queue
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st

import analyzer
import market_analyzer
from config import APP_TITLE, CACHE_DIR

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

if "data" not in st.session_state:
    st.session_state.data = []

if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

if "market_panel" not in st.session_state:
    st.session_state.market_panel = None

if "market_panel_updated" not in st.session_state:
    st.session_state.market_panel_updated = None

def _fmt_signed_pct(value, decimals=1, show_arrow=False):
    try:
        v = float(value)
        if pd.isna(v):
            return "-"
        if show_arrow:
            if v > 0:
                return f"↑ +{v:.{decimals}f}%"
            if v < 0:
                return f"↓ {v:.{decimals}f}%"
            return f"→ {0:.{decimals}f}%"
        if v > 0:
            return f"+{v:.{decimals}f}%"
        if v < 0:
            return f"{v:.{decimals}f}%"
        return f"{0:.{decimals}f}%"
    except:
        return "-"

st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)
sort_mode = st.sidebar.selectbox(
    "정렬 기준",
    ["점수", "시가총액", "PER", "PBR", "ROE", "PEG", "최고점대비", "200일괴리율"],
    index=0
)
opt_fundamental = st.sidebar.checkbox("기본 재무지표 사용", value=True)
opt_peak = st.sidebar.checkbox("최고점 비교 사용", value=True)
show_market_panel = st.sidebar.checkbox("시장상황판 표시", value=True)
refresh_market = st.sidebar.button("🔄 시장상황판 새로고침")

if refresh_market or st.session_state.market_panel is None:
    with st.spinner("시장상황판 계산 중..."):
        try:
            st.session_state.market_panel = market_analyzer.build_market_panel()
            st.session_state.market_panel_updated = datetime.now()
        except Exception as e:
            st.session_state.market_panel = {"error": str(e), "rows": []}

def _sort_dataframe(df: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    ascending_map = {
        "점수": False,
        "시가총액": False,
        "PER": True,
        "PBR": True,
        "ROE": False,
        "PEG": True,
        "최고점대비": True,
        "200일괴리율": True,
    }
    sort_col_map = {
        "점수": "score",
        "시가총액": "market_cap",
        "PER": "per",
        "PBR": "pbr",
        "ROE": "roe",
        "PEG": "peg",
        "최고점대비": "peak_diff",
        "200일괴리율": "diff",
    }

    sort_col = sort_col_map.get(sort_key, "score")
    ascending = ascending_map.get(sort_key, False)

    if sort_col not in df.columns:
        sort_col = "score" if "score" in df.columns else df.columns[0]
        ascending = False

    sort_cols = [sort_col]
    ascending_list = [ascending]

    if "score" in df.columns and sort_col != "score":
        sort_cols.append("score")
        ascending_list.append(False)

    if "confidence" in df.columns:
        sort_cols.append("confidence")
        ascending_list.append(False)

    if "market_cap" in df.columns and sort_col != "market_cap":
        sort_cols.append("market_cap")
        ascending_list.append(False)

    try:
        df = df.sort_values(by=sort_cols, ascending=ascending_list)
    except:
        try:
            df = df.sort_values(by=sort_col, ascending=ascending)
        except:
            pass

    df["rank"] = range(1, len(df) + 1)
    return df

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
                        "WFC", "AXP", "GE", "NKE", "LIN", "PM", "ABT", "CAT", "TXN", "MS",
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
        "rank": "순위",
        "symbol": "티커",
        "name": "종목명",
        "market_cap": "시가총액\n(억)",
        "price": "현재가",
        "peak": "최고점",
        "peak_diff": "최고점\n괴리율",
        "ma200": "200일선",
        "diff": "200일\n괴리율",
        "rsi": "RSI\n(과열/침체)",
        "per": "PER\n(주가/수익)",
        "pbr": "PBR\n(주가/자산)",
        "roe": "ROE\n(자본수익률)",
        "peg": "PEG\n(성장성/PER)",
        "eps3y": "EPS3Y\n(3년성장)",
        "cagr": "CAGR\n(연평균성장)",
        "score": "점수",
        "grade": "등급",
        "confidence": "신뢰도\n(%)",
        "summary": "AI한줄해석",
        "detail_text": "점수상세",
        "missing_fields": "누락지표",
    }
    formatted_df = formatted_df.rename(columns=rename_dict)

    styler = formatted_df.style
    format_dict = {}

    if "순위" in formatted_df.columns:
        format_dict["순위"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "시가총액\n(억)" in formatted_df.columns:
        format_dict["시가총액\n(억)"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "-"
    if "현재가" in formatted_df.columns:
        format_dict["현재가"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "200일선" in formatted_df.columns:
        format_dict["200일선"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점" in formatted_df.columns:
        format_dict["최고점"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점\n괴리율" in formatted_df.columns:
        format_dict["최고점\n괴리율"] = lambda x: _fmt_signed_pct(x, 2)
    if "200일\n괴리율" in formatted_df.columns:
        format_dict["200일\n괴리율"] = lambda x: _fmt_signed_pct(x, 2)
    if "RSI\n(과열/침체)" in formatted_df.columns:
        format_dict["RSI\n(과열/침체)"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PER\n(주가/수익)" in formatted_df.columns:
        format_dict["PER\n(주가/수익)"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PBR\n(주가/자산)" in formatted_df.columns:
        format_dict["PBR\n(주가/자산)"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "ROE\n(자본수익률)" in formatted_df.columns:
        format_dict["ROE\n(자본수익률)"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
    if "PEG\n(성장성/PER)" in formatted_df.columns:
        format_dict["PEG\n(성장성/PER)"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "EPS3Y\n(3년성장)" in formatted_df.columns:
        format_dict["EPS3Y\n(3년성장)"] = lambda x: str(x) if pd.notna(x) else "-"
    if "CAGR\n(연평균성장)" in formatted_df.columns:
        format_dict["CAGR\n(연평균성장)"] = lambda x: _fmt_signed_pct(x, 1, show_arrow=True)
    if "점수" in formatted_df.columns:
        format_dict["점수"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "등급" in formatted_df.columns:
        format_dict["등급"] = lambda x: str(x) if pd.notna(x) else "-"
    if "신뢰도\n(%)" in formatted_df.columns:
        format_dict["신뢰도\n(%)"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"

    styler = styler.format(format_dict)
    styler = styler.set_properties(**{"text-align": "center", "white-space": "nowrap"})

    def color_per(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v <= 5:
                return "color: #0D47A1; font-weight: bold;"
            elif v <= 10:
                return "color: #1976D2; font-weight: bold;"
            elif v <= 15:
                return "color: #0288D1; font-weight: bold;"
            elif v <= 20:
                return "color: #E65100; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def color_pbr(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v <= 0.5:
                return "color: #0D47A1; font-weight: bold;"
            elif v <= 1.0:
                return "color: #1976D2; font-weight: bold;"
            elif v <= 2.0:
                return "color: #0288D1; font-weight: bold;"
            elif v <= 3.0:
                return "color: #E65100; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def color_peg(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v <= 0.5:
                return "color: #0D47A1; font-weight: bold;"
            elif v <= 1.0:
                return "color: #1976D2; font-weight: bold;"
            elif v <= 1.5:
                return "color: #0288D1; font-weight: bold;"
            elif v <= 2.0:
                return "color: #E65100; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def color_roe(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v >= 20:
                return "color: #0D47A1; font-weight: bold;"
            elif v >= 15:
                return "color: #1976D2; font-weight: bold;"
            elif v >= 10:
                return "color: #0288D1; font-weight: bold;"
            elif v >= 5:
                return "color: #E65100; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def color_rsi(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v >= 70:
                return "color: #D32F2F; font-weight: bold;"
            elif v >= 50:
                return "color: #E65100; font-weight: bold;"
            elif v >= 30:
                return "color: #1976D2; font-weight: bold;"
            else:
                return "color: #0D47A1; font-weight: bold;"
        except:
            return ""

    def color_score(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v >= 90:
                return "color: #0D47A1; font-weight: bold;"
            elif v >= 80:
                return "color: #1976D2; font-weight: bold;"
            elif v >= 70:
                return "color: #2E7D32; font-weight: bold;"
            elif v >= 60:
                return "color: #EF6C00; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def color_grade(val):
        s = str(val).strip().upper()
        if s == "S":
            return "color: #0D47A1; font-weight: bold;"
        if s == "A":
            return "color: #1976D2; font-weight: bold;"
        if s == "B":
            return "color: #2E7D32; font-weight: bold;"
        if s == "C":
            return "color: #EF6C00; font-weight: bold;"
        if s == "D":
            return "color: #D32F2F; font-weight: bold;"
        return ""

    def color_confidence(val):
        try:
            v = float(val)
            if pd.isna(v):
                return ""
            if v >= 90:
                return "color: #0D47A1; font-weight: bold;"
            elif v >= 75:
                return "color: #1976D2; font-weight: bold;"
            elif v >= 60:
                return "color: #2E7D32; font-weight: bold;"
            elif v >= 45:
                return "color: #EF6C00; font-weight: bold;"
            else:
                return "color: #D32F2F; font-weight: bold;"
        except:
            return ""

    def apply_strict_color_rules(val):
        try:
            v = float(val)
            if v > 0:
                return "color: #D32F2F; font-weight: bold;"
            elif v < 0:
                return "color: #1976D2; font-weight: bold;"
        except:
            if isinstance(val, str):
                if "+" in val or "↑" in val:
                    return "color: #D32F2F; font-weight: bold;"
                if "-" in val or "↓" in val:
                    return "color: #1976D2; font-weight: bold;"
        return "color: #212121;"

    if "PER\n(주가/수익)" in formatted_df.columns:
        styler = styler.map(color_per, subset=["PER\n(주가/수익)"])
    if "PBR\n(주가/자산)" in formatted_df.columns:
        styler = styler.map(color_pbr, subset=["PBR\n(주가/자산)"])
    if "PEG\n(성장성/PER)" in formatted_df.columns:
        styler = styler.map(color_peg, subset=["PEG\n(성장성/PER)"])
    if "ROE\n(자본수익률)" in formatted_df.columns:
        styler = styler.map(color_roe, subset=["ROE\n(자본수익률)"])
    if "RSI\n(과열/침체)" in formatted_df.columns:
        styler = styler.map(color_rsi, subset=["RSI\n(과열/침체)"])
    if "점수" in formatted_df.columns:
        styler = styler.map(color_score, subset=["점수"])
    if "등급" in formatted_df.columns:
        styler = styler.map(color_grade, subset=["등급"])
    if "신뢰도\n(%)" in formatted_df.columns:
        styler = styler.map(color_confidence, subset=["신뢰도\n(%)"])

    target_cols = [c for c in ["최고점\n괴리율", "200일\n괴리율"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)

    return styler

link_config = {
    "순위": st.column_config.NumberColumn("순위", width="small", format="%d"),
    "티커": st.column_config.LinkColumn("티커", display_text=r"ticker=([^&]*)", width="small"),
    "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]*)", width="medium"),
    "시가총액\n(억)": st.column_config.NumberColumn("시가총액\n(억)", width="small"),
    "현재가": st.column_config.NumberColumn("현재가", width="small"),
    "최고점": st.column_config.NumberColumn("최고점", width="small"),
    "최고점\n괴리율": st.column_config.NumberColumn("최고점\n괴리율", width="small"),
    "200일선": st.column_config.NumberColumn("200일선", width="small"),
    "200일\n괴리율": st.column_config.NumberColumn("200일\n괴리율", width="small"),
    "RSI\n(과열/침체)": st.column_config.NumberColumn("RSI\n(과열/침체)", width="small"),
    "PER\n(주가/수익)": st.column_config.NumberColumn("PER\n(주가/수익)", width="small"),
    "PBR\n(주가/자산)": st.column_config.NumberColumn("PBR\n(주가/자산)", width="small"),
    "ROE\n(자본수익률)": st.column_config.NumberColumn("ROE\n(자본수익률)", width="small"),
    "PEG\n(성장성/PER)": st.column_config.NumberColumn("PEG\n(성장성/PER)", width="small"),
    "EPS3Y\n(3년성장)": st.column_config.TextColumn("EPS3Y\n(3년성장)", width="medium"),
    "CAGR\n(연평균성장)": st.column_config.NumberColumn("CAGR\n(연평균성장)", width="small"),
    "점수": st.column_config.NumberColumn("점수", width="small"),
    "등급": st.column_config.TextColumn("등급", width="small"),
    "신뢰도\n(%)": st.column_config.NumberColumn("신뢰도\n(%)", width="small", format="%.1f%%"),
    "AI한줄해석": st.column_config.TextColumn("AI한줄해석", width="large"),
    "점수상세": st.column_config.TextColumn("점수상세", width="large"),
    "누락지표": st.column_config.TextColumn("누락지표", width="medium"),
}

def _display_market_panel(panel: dict):
    if not panel:
        st.info("시장상황판 데이터가 없습니다.")
        return

    if panel.get("error"):
        st.warning(f"시장상황판 계산 실패: {panel['error']}")
        return

    cols = st.columns([1.1, 1.1, 1.1, 1.1])
    with cols[0]:
        st.metric("시장점수", f"{panel.get('market_score', 0):.1f}")
    with cols[1]:
        st.metric("시장상태", panel.get("market_state", "-"))
    with cols[2]:
        st.metric("가용도", f"{panel.get('confidence', 0):.1f}%")
    with cols[3]:
        updated = st.session_state.market_panel_updated.strftime("%H:%M:%S") if st.session_state.market_panel_updated else "-"
        st.metric("갱신시각", updated)

    st.caption("Trend = 시장추세 / Effect = 시장심리 / Risk = 위험도")
    if panel.get("market_state_note"):
        st.caption(f"판단: {panel.get('market_state_note', '-')}")
    st.caption(panel.get("summary", ""))

    rows = panel.get("rows", [])
    if rows:
        view_df = pd.DataFrame(rows)
        view_df["latest"] = view_df["latest"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        view_df["ret20"] = view_df["ret20"].apply(lambda x: _fmt_signed_pct(x, 1) if pd.notna(x) else "-")
        view_df["ret60"] = view_df["ret60"].apply(lambda x: _fmt_signed_pct(x, 1) if pd.notna(x) else "-")
        view_df["risk_score"] = view_df["risk_score"].apply(lambda x: f"{int(x)}" if pd.notna(x) else "-")
        view_df["trend"] = view_df["trend"].fillna("-")
        view_df["effect"] = view_df["effect"].fillna("-")
        view_df["trend_note"] = view_df["trend_note"].fillna("-")
        view_df["effect_note"] = view_df["effect_note"].fillna("-")
        display_rows = view_df[["label", "symbol", "trend", "trend_note", "effect", "effect_note", "risk_score", "latest", "ret20", "ret60"]].rename(columns={
            "label": "항목",
            "symbol": "티커",
            "trend": "Trend\n(추세)",
            "trend_note": "Trend메모",
            "effect": "Effect\n(심리)",
            "effect_note": "Effect메모",
            "risk_score": "Risk\n(위험도)",
            "latest": "Latest\n(현재가)",
            "ret20": "Ret 20D\n(1달수익률)",
            "ret60": "Ret 60D\n(3달수익률)",
        })
        st.dataframe(
            display_rows,
            use_container_width=True,
            hide_index=True,
        )

st.markdown("### 📌 시장상황판")
if show_market_panel:
    _display_market_panel(st.session_state.market_panel)
else:
    st.caption("시장상황판이 숨김 상태입니다.")

st.markdown("---")

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
            st.session_state.data = loaded_df.to_dict(orient="records")
            st.toast(f"📂 {market} 시장의 최근 자동저장 데이터를 불러왔습니다.", icon="✅")
        except Exception as e:
            st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
    else:
        st.warning(f"💾 {market} 시장에 자동 저장된 백업 데이터가 존재하지 않습니다.")

DISPLAY_COLUMN_ORDER = [
    "rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff",
    "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr", "score", "grade", "confidence",
    "summary", "detail_text", "missing_fields"
]

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
                if df.empty:
                    continue

                if "score" in df.columns:
                    df = _sort_dataframe(df, sort_mode)
                else:
                    column_order = ["rank", "symbol", "name", "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr"]
                    available_cols = [c for c in column_order if c in df.columns]
                    if "market_cap" in df.columns and len(df) > 0:
                        df = df.sort_values(by="market_cap", ascending=False)
                        df["rank"] = range(1, len(df) + 1)
                    display_df = df[available_cols]
                    styled_live_df = style_screener_dataframe(display_df, market)
                    date_val = df["data_date"].iloc[0] if "data_date" in df.columns and len(df) > 0 else "-"
                    header_placeholder.markdown(
                        f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><h3>📊 실시간 분석 결과</h3><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>",
                        unsafe_allow_html=True
                    )
                    table_placeholder.dataframe(
                        styled_live_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config=link_config,
                        selection_mode="row"
                    )
                    continue

                column_order = DISPLAY_COLUMN_ORDER
                available_cols = [c for c in column_order if c in df.columns]
                display_df = df[available_cols]
                styled_live_df = style_screener_dataframe(display_df, market)
                date_val = df["data_date"].iloc[0] if "data_date" in df.columns and len(df) > 0 else "-"
                header_placeholder.markdown(
                    f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><h3>📊 실시간 분석 결과</h3><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>",
                    unsafe_allow_html=True
                )
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
                    if "score" in final_save_df.columns:
                        final_save_df = _sort_dataframe(final_save_df, sort_mode)
                    elif "market_cap" in final_save_df.columns and len(final_save_df) > 0:
                        final_save_df = final_save_df.sort_values(by="market_cap", ascending=False)
                        final_save_df["rank"] = range(1, len(final_save_df) + 1)
                    save_cols = [c for c in DISPLAY_COLUMN_ORDER if c in final_save_df.columns]
                    final_save_df = final_save_df[save_cols]
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding="utf-8-sig")
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
                    if "score" in final_save_df.columns:
                        final_save_df = _sort_dataframe(final_save_df, sort_mode)
                    elif "market_cap" in final_save_df.columns and len(final_save_df) > 0:
                        final_save_df = final_save_df.sort_values(by="market_cap", ascending=False)
                        final_save_df["rank"] = range(1, len(final_save_df) + 1)
                    save_cols = [c for c in DISPLAY_COLUMN_ORDER if c in final_save_df.columns]
                    final_save_df = final_save_df[save_cols]
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding="utf-8-sig")
                break

        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                break

if st.session_state.data:
    final_df = pd.DataFrame(st.session_state.data)

    if "score" in final_df.columns:
        final_df = _sort_dataframe(final_df, sort_mode)
    elif "market_cap" in final_df.columns and len(final_df) > 0:
        final_df = final_df.sort_values(by="market_cap", ascending=False)
        final_df["rank"] = range(1, len(final_df) + 1)

    date_val = final_df["data_date"].iloc[0] if "data_date" in final_df.columns and len(final_df) > 0 else "-"

    head_col1, head_col2 = st.columns([6, 2])
    with head_col1:
        st.subheader("📊 분석 결과")
    with head_col2:
        st.markdown(
            f"<div style='text-align: right; margin-top: 10px;'><span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span></div>",
            unsafe_allow_html=True
        )

    column_order = DISPLAY_COLUMN_ORDER
    available_cols = [c for c in column_order if c in final_df.columns]

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

    if not final_df.empty:
        st.markdown("### 🔎 점수 상세보기")
        detail_options = final_df.apply(lambda r: f"{r['symbol']} | {r['name']}", axis=1).tolist()
        selected_label = st.selectbox("종목 선택", detail_options)

        selected_row = final_df.iloc[detail_options.index(selected_label)]

        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.metric("점수", f"{int(selected_row.get('score', 0))}")
        with d2:
            st.metric("등급", str(selected_row.get("grade", "-")))
        with d3:
            conf = selected_row.get("confidence", 0)
            st.metric("신뢰도", f"{float(conf):.1f}%")
        with d4:
            rsi_val = selected_row.get("rsi", None)
            st.metric("RSI", f"{float(rsi_val):.1f}" if pd.notna(rsi_val) else "-")

        st.info(str(selected_row.get("summary", "-")))
        st.caption(str(selected_row.get("detail_text", "-")))

        detail_table = pd.DataFrame([
            ["PER", selected_row.get("score_per", 0), selected_row.get("per", "-")],
            ["PBR", selected_row.get("score_pbr", 0), selected_row.get("pbr", "-")],
            ["ROE", selected_row.get("score_roe", 0), selected_row.get("roe", "-")],
            ["PEG", selected_row.get("score_peg", 0), selected_row.get("peg", "-")],
            ["EPS3Y", selected_row.get("score_eps3y", 0), selected_row.get("eps3y", "-")],
            ["CAGR", selected_row.get("score_cagr", 0), selected_row.get("cagr", "-")],
            ["RSI", selected_row.get("score_rsi", 0), selected_row.get("rsi", "-")],
            ["최고점대비", selected_row.get("score_peak_diff", 0), selected_row.get("peak_diff", "-")],
            ["누락지표", "-", selected_row.get("missing_fields", "") or "-"],
        ], columns=["항목", "점수", "원본값"])
        st.dataframe(detail_table, use_container_width=True, hide_index=True)

    rename_dict = {
        "rank": "순위",
        "symbol": "티커",
        "name": "종목명",
        "market_cap": "시가총액\n(억)",
        "price": "현재가",
        "peak": "최고점",
        "peak_diff": "최고점\n괴리율",
        "ma200": "200일선",
        "diff": "200일\n괴리율",
        "rsi": "RSI\n(과열/침체)",
        "per": "PER\n(주가/수익)",
        "pbr": "PBR\n(주가/자산)",
        "roe": "ROE\n(자본수익률)",
        "peg": "PEG\n(성장성/PER)",
        "eps3y": "EPS3Y\n(3년성장)",
        "cagr": "CAGR\n(연평균성장)",
        "score": "점수",
        "grade": "등급",
        "confidence": "신뢰도\n(%)",
        "summary": "AI한줄해석",
        "detail_text": "점수상세",
        "missing_fields": "누락지표",
    }
    csv_df = final_df.rename(columns=rename_dict)
    csv_save_cols = [rename_dict.get(c, c) for c in DISPLAY_COLUMN_ORDER if c in final_df.columns]
    csv_df = csv_df[csv_save_cols]
    csv = csv_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
else:
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")