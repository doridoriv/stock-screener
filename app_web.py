import os
import queue
import threading
import time
from datetime import datetime

import pandas as pd
import numpy as np
import streamlit as st

import analyzer
import market_analyzer
from config import APP_TITLE, CACHE_DIR

# 세션 상태 초기화 (사이드바 상태 및 검색 가동 플래그 관리)
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "expanded"

if "searching" not in st.session_state:
    st.session_state.searching = False

if "data" not in st.session_state:
    st.session_state.data = []

st.set_page_config(
    page_title=APP_TITLE, 
    layout="wide", 
    initial_sidebar_state=st.session_state.sidebar_state
)

# 반응형 최적화를 위한 CSS 스타일 레이아웃
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 2rem;
            max-width: 100%;
        }

        @media (max-width: 768px) {
            .block-container {
                padding-left: 0.8rem;
                padding-right: 0.8rem;
            }

            [data-testid="stDataFrame"] {
                font-size: 0.82rem;
            }

            [data-testid="stDataFrame"] [role="gridcell"],
            [data-testid="stDataFrame"] [role="columnheader"] {
                padding: 0.18rem 0.30rem !important;
            }
        }

        [data-testid="stDataFrame"] {
            width: 100%;
            overflow-x: auto;
            font-size: 0.90rem;
        }

        [data-testid="stDataFrame"] [role="gridcell"],
        [data-testid="stDataFrame"] [role="columnheader"] {
            padding: 0.22rem 0.40rem !important;
            line-height: 1.15 !important;
        }

        [data-testid="stDataFrame"] [role="gridcell division"] div,
        [data-testid="stDataFrame"] [role="columnheader"] div {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

if "market_panel" not in st.session_state:
    st.session_state.market_panel = None

if "market_panel_updated" not in st.session_state:
    st.session_state.market_panel_updated = None

st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)
sort_mode = st.sidebar.selectbox(
    "정렬 기준",
    ["점수", "시가총액", "PER", "PBR", "ROE", "PEG", "최고점대비", "200일괴리율"],
    index=0,
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
        "점수": False, "시가총액": False, "PER": True, "PBR": True,
        "ROE": False, "PEG": True, "최고점대비": True, "200일괴리율": True,
    }
    sort_col_map = {
        "점수": "score", "시가총액": "market_cap", "PER": "per", "PBR": "pbr",
        "ROE": "roe", "PEG": "peg", "최고점대비": "peak_diff", "200일괴리율": "diff",
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

    # [💡 핵심 수정 패치] PyArrow 직렬화 에러(ArrowTypeError) 방지를 위한 문자열 강제 전처리
    text_columns = ["symbol", "name", "grade", "eps3y", "summary", "detail_text", "missing_fields"]
    for col in text_columns:
        if col in formatted_df.columns:
            formatted_df[col] = formatted_df[col].fillna("").astype(str).str.strip()

    if "symbol" in formatted_df.columns and "name" in formatted_df.columns:
        urls = []
        for idx, row in formatted_df.iterrows():
            sym = row["symbol"]
            row_name = row["name"]

            if not sym or sym == "nan" or sym == "":
                urls.append("")
                continue

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
                    suffix = ".N" if sym in nyse_tickers else ".O"
                    base_url = f"https://m.stock.naver.com/worldstock/stock/{sym}{suffix}/total"
                url = f"{base_url}?ticker={sym}&name={row_name}"
            else:
                code_str = "".join(filter(str.isdigit, sym)).zfill(6)
                if not code_str or code_str == "000000":
                    code_str = sym.zfill(6)
                url = f"https://finance.naver.com/item/main.naver?code={code_str}&ticker={code_str}&name={row_name}"
            
            urls.append(str(url))

        formatted_df["symbol"] = pd.Series(urls, index=formatted_df.index, dtype=str)
        formatted_df["name"] = pd.Series(urls, index=formatted_df.index, dtype=str)

    required_missing_cols = ["eps_growth", "hist_per_avg", "us_10y_bond", "foreign_supply"]
    for c in required_missing_cols:
        if c not in formatted_df.columns:
            formatted_df[c] = pd.Series([np.nan] * len(formatted_df), dtype="float64")

    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명",
        "score": "종합점수", "grade": "등급",
        "eps_growth": "EPS성장률(%)", "hist_per_avg": "과거평균PER",
        "us_10y_bond": "美10년물금리", "foreign_supply": "외인/기관지분(%)",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비(%)", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI", "per": "현재PER", "pbr": "PBR", "roe": "ROE(%)", "peg": "PEG",
        "eps3y": "EPS 3년 추세", "cagr": "CAGR(%)", "confidence": "신뢰도(%)",
        "summary": "AI한줄해석"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)

    styler = formatted_df.style
    format_dict = {}

    if "EPS성장률(%)" in formatted_df.columns:
        format_dict["EPS성장률(%)"] = lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0 else f"{x:.1f}%" if pd.notna(x) else "-"
    if "과거평균PER" in formatted_df.columns:
        format_dict["과거평균PER"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "美10년물금리" in formatted_df.columns:
        format_dict["美10년물금리"] = lambda x: f"{x:.2f}%" if pd.notna(x) else "-"
    if "외인/기관지분(%)" in formatted_df.columns:
        format_dict["외인/기관지분(%)"] = lambda x: f"{x:.2f}%" if pd.notna(x) else "-"

    if "순위" in formatted_df.columns: format_dict["순위"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "종합점수" in formatted_df.columns: format_dict["종합점수"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "시가총액(억)" in formatted_df.columns: format_dict["시가총액(억)"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "-"
    if "현재가" in formatted_df.columns: format_dict["현재가"] = lambda x: (f"${x:,.2f}" if is_us else f"{int(x):,}원") if pd.notna(x) else "-"
    if "200일선" in formatted_df.columns: format_dict["200일선"] = lambda x: (f"${x:,.2f}" if is_us else f"{int(x):,}원") if pd.notna(x) else "-"
    if "최고점" in formatted_df.columns: format_dict["최고점"] = lambda x: (f"${x:,.2f}" if is_us else f"{int(x):,}원") if pd.notna(x) else "-"
    if "최고점대비(%)" in formatted_df.columns: format_dict["최고점대비(%)"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "200일괴리율(%)" in formatted_df.columns: format_dict["200일괴리율(%)"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "RSI" in formatted_df.columns: format_dict["RSI"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "현재PER" in formatted_df.columns: format_dict["현재PER"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PBR" in formatted_df.columns: format_dict["PBR"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "ROE(%)" in formatted_df.columns: format_dict["ROE(%)"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
    if "PEG" in formatted_df.columns: format_dict["PEG"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "CAGR(%)" in formatted_df.columns: format_dict["CAGR(%)"] = lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0 else f"{x:.1f}%" if pd.notna(x) else "-"
    if "신뢰도(%)" in formatted_df.columns: format_dict["신뢰도(%)"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"

    styler = styler.format(format_dict)
    styler = styler.set_properties(**{"text-align": "center", "white-space": "nowrap"})

    def color_per(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v <= 10: return "color: #1976D2; font-weight: bold;"
            if v <= 20: return "color: #E65100; font-weight: bold;"
            return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_score(val):
        try:
            v = float(val)
            if pd.isna(v): return ""
            if v >= 80: return "color: #1976D2; font-weight: bold;"
            if v >= 60: return "color: #2E7D32; font-weight: bold;"
            return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_grade(val):
        s = str(val).strip().upper()
        if s in ["S", "A"]: return "color: #1976D2; font-weight: bold;"
        if s == "B": return "color: #2E7D32; font-weight: bold;"
        return "color: #D32F2F; font-weight: bold;"

    def apply_strict_color_rules(val):
        try:
            v = float(val)
            if v > 0: return "color: #D32F2F; font-weight: bold;"
            if v < 0: return "color: #1976D2; font-weight: bold;"
        except: pass
        return "color: #212121;"

    if "현재PER" in formatted_df.columns: styler = styler.map(color_per, subset=["현재PER"])
    if "종합점수" in formatted_df.columns: styler = styler.map(color_score, subset=["종합점수"])
    if "등급" in formatted_df.columns: styler = styler.map(color_grade, subset=["등급"])

    target_cols = [c for c in ["최고점대비(%)", "200일괴리율(%)"] if c in formatted_df.columns]
    if target_cols: styler = styler.map(apply_strict_color_rules, subset=target_cols)

    return styler


link_config = {
    "순위": st.column_config.NumberColumn("순위", format="%d"),
    "티커": st.column_config.LinkColumn("티커", display_text=r"ticker=([^&]*)"),
    "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]*)"),
    "종합점수": st.column_config.NumberColumn("종합점수"),
    "등급": st.column_config.TextColumn("등급"),
    "EPS성장률(%)": st.column_config.NumberColumn("EPS성장률(%)"),
    "과거평균PER": st.column_config.NumberColumn("과거평균PER"),
    "美10년물금리": st.column_config.NumberColumn("美10년물금리"),
    "외인/기관지분(%)": st.column_config.NumberColumn("외인/기관지분(%)"),
    "시가총액(억)": st.column_config.NumberColumn("시가총액(억)"),
    "현재가": st.column_config.NumberColumn("현재가"),
    "최고점": st.column_config.NumberColumn("최고점"),
    "최고점대비(%)": st.column_config.NumberColumn("최고점대비(%)"),
    "200일선": st.column_config.NumberColumn("200일선"),
    "200일괴리율(%)": st.column_config.NumberColumn("200일괴리율(%)"),
    "RSI": st.column_config.NumberColumn("RSI"),
    "현재PER": st.column_config.NumberColumn("현재PER"),
    "PBR": st.column_config.NumberColumn("PBR"),
    "ROE(%)": st.column_config.NumberColumn("ROE(%)"),
    "PEG": st.column_config.NumberColumn("PEG"),
    "EPS 3년 추세": st.column_config.TextColumn("EPS 3년 추세"),
    "CAGR(%)": st.column_config.NumberColumn("CAGR(%)"),
    "신뢰도(%)": st.column_config.NumberColumn("신뢰도(%)", format="%.1f%%"),
    "AI한줄해석": st.column_config.TextColumn("AI한줄해석"),
    "점수상세": st.column_config.TextColumn("점수상세"),
    "누락지표": st.column_config.TextColumn("누락지표"),
}

STANDARD_COLUMN_ORDER = [
    "rank", "symbol", "name", "score", "grade",
    "eps_growth", "hist_per_avg", "us_10y_bond", "foreign_supply",
    "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", 
    "per", "pbr", "roe", "peg", "eps3y", "cagr", "confidence", 
    "summary", "detail_text", "missing_fields"
]


def _display_market_panel(panel: dict):
    if not panel:
        st.info("시장상황판 데이터가 없습니다.")
        return

    if panel.get("error"):
        st.warning(f"시장상황판 계산 실패: {panel['error']}")
        return

    cols = st.columns([1.1, 1.1, 1.1, 1.1])
    with cols[0]: st.metric("시장점수", f"{panel.get('market_score', 0):.1f}")
    with cols[1]: st.metric("시장상태", panel.get("market_state", "-"))
    with cols[2]: st.metric("가용도", f"{panel.get('confidence', 0):.1f}%")
    with cols[3]:
        updated = st.session_state.market_panel_updated.strftime("%H:%M:%S") if st.session_state.market_panel_updated else "-"
        st.metric("갱신시각", updated)

    st.caption(panel.get("summary", ""))

    rows = panel.get("rows", [])
    if rows:
        view_df = pd.DataFrame(rows)
        view_df["latest"] = view_df["latest"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        view_df["ret20"] = view_df["ret20"].apply(lambda x: f"{x:+.1f}%" if pd.notna(x) else "-")
        view_df["ret60"] = view_df["ret60"].apply(lambda x: f"{x:+.1f}%" if pd.notna(x) else "-")
        view_df["risk_score"] = view_df["risk_score"].apply(lambda x: f"{int(x)}" if pd.notna(x) else "-")
        view_df["effect"] = view_df["effect"].fillna("-")
        view_df["trend"] = view_df["trend"].fillna("-")
        
        st.dataframe(
            view_df[["label", "symbol", "trend", "effect", "risk_score", "latest", "ret20", "ret60"]],
            width="stretch",
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
    btn_search = st.button("🔍 검색")

with col2:
    btn_load = st.button("📂 불러오기")

with col3:
    btn_stop = st.button("⏹ 검색 중지")

if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
    st.session_state.searching = False
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
        st.warning(f"💾 {market} 시장에 자동 저장된 백업 데이터가 존재하지 않습니다. 먼저 [🔍 검색]을 실행하세요.")

# [세션 기반 검색 가동 트리거 제어]
if btn_search:
    st.session_state.searching = True
    st.session_state.data = []  # 기존 데이터 초기화
    if st.session_state.sidebar_state == "expanded":
        st.session_state.sidebar_state = "collapsed"
        st.rerun()

if st.session_state.searching:
    loop_progress_bar = st.progress(0)
    success_progress_bar = st.progress(0)
    status_text = st.empty()
    success_text = st.empty()
    header_placeholder = st.empty()
    table_placeholder = st.empty()

    app_queue = queue.Queue()
    st.session_state.stop_event = threading.Event()
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    current_stop_event = st.session_state.stop_event

    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, top_n, app_queue, lambda: current_stop_event.is_set(), opt_fundamental, opt_peak, us_market_cap_data),
        daemon=True,
    )
    worker_thread.start()

    # 스레드로부터 데이터 수집 루프 시작
    temp_data_list = []
    while True:
        try:
            msg = app_queue.get_nowait()
            m_type = msg.get("type")

            if m_type == "progress":
                loop_progress_bar.progress(msg["value"] / 100)
                status_text.text(msg["text"])

            elif m_type == "data":
                temp_data_list.append(msg["data"])
                # 실시간 화면 동기화를 위해 세션에도 동시 적재
                st.session_state.data = list(temp_data_list)
                
                df = pd.DataFrame(temp_data_list)
                if df.empty:
                    continue

                success_count = len(temp_data_list)
                success_rate = min(1.0, success_count / max(top_n, 1))
                latest_name = str(msg["data"].get("name", "-"))

                success_progress_bar.progress(success_rate)
                success_text.markdown(
                    f"**현재 성공한 종목 수:** {success_count} / {top_n}  \n**최근 완료:** {latest_name}"
                )

                if "score" in df.columns:
                    df = _sort_dataframe(df, sort_mode)
                else:
                    if "market_cap" in df.columns and len(df) > 0:
                        df = df.sort_values(by="market_cap", ascending=False)
                        df["rank"] = range(1, len(df) + 1)

                available_cols = [c for c in STANDARD_COLUMN_ORDER if c in df.columns]
                display_df = df[available_cols]
                styled_live_df = style_screener_dataframe(display_df, market)
                date_val = df["data_date"].iloc[0] if "data_date" in df.columns and len(df) > 0 else "-"
                
                header_placeholder.markdown(
                    f"""
                    <div style='display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px;'>
                        <h3 style='margin: 0;'>📊 실시간 분석 결과</h3>
                        <div style='display: flex; gap: 8px; flex-wrap: wrap;'>
                            <span style='background-color: #F0F2F6; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1F2937;'>📅 기준일 {date_val}</span>
                            <span style='background-color: #E8F5E9; padding: 6px 12px; border-radius: 8px; font-weight: bold; color: #1B5E20;'>✅ 성공 {success_count} / {top_n}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                
                table_placeholder.dataframe(
                    styled_live_df,
                    width="stretch",
                    hide_index=True,
                    column_config=link_config,
                )

            elif m_type == "done":
                loop_progress_bar.progress(1.0)
                status_text.success(msg["text"])
                
                st.session_state.data = list(temp_data_list)
                
                if st.session_state.data:
                    final_save_df = pd.DataFrame(st.session_state.data)
                    final_save_df = _sort_dataframe(final_save_df, sort_mode) if "score" in final_save_df.columns else final_save_df
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding="utf-8-sig")
                
                st.session_state.searching = False
                time.sleep(0.5)  # 저장 보장 안정성 갭
                st.rerun()
                break

            elif m_type == "error":
                st.error(msg["text"])
                st.session_state.searching = False
                break

            elif m_type == "stopped":
                st.warning(f"분석 중지: {len(temp_data_list)}개 완료")
                st.session_state.data = list(temp_data_list)
                
                if st.session_state.data:
                    final_save_df = pd.DataFrame(st.session_state.data)
                    final_save_df = _sort_dataframe(final_save_df, sort_mode) if "score" in final_save_df.columns else final_save_df
                    file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{market}.csv")
                    final_save_df.to_csv(file_path, index=False, encoding="utf-8-sig")
                
                st.session_state.searching = False
                time.sleep(0.5)
                st.rerun()
                break

        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive() and app_queue.empty():
                st.session_state.data = list(temp_data_list)
                st.session_state.searching = False
                break

# 최종 메인 뷰어 테이블 렌더링 파트
if st.session_state.data and not st.session_state.searching:
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
            unsafe_allow_html=True,
        )

    available_cols = [c for c in STANDARD_COLUMN_ORDER if c in final_df.columns]
    display_final_df = final_df[available_cols]
    styled_final_df = style_screener_dataframe(display_final_df, market)

    st.dataframe(
        styled_final_df,
        width="stretch",
        height=650,
        hide_index=True,
        column_config=link_config,
        selection_mode="row",
    )

    if not final_df.empty:
        st.markdown("### 🔎 점수 상세보기")
        detail_options = final_df.apply(lambda r: f"{r['symbol']} | {r['name']}", axis=1).tolist()
        selected_label = st.selectbox("종목 선택", detail_options)
        selected_row = final_df.iloc[detail_options.index(selected_label)]

        d1, d2, d3, d4 = st.columns(4)
        with d1: st.metric("점수", f"{int(selected_row.get('score', 0))}")
        with d2: st.metric("등급", str(selected_row.get("grade", "-")))
        with d3: st.metric("신뢰도", f"{float(selected_row.get('confidence', 0)):.1f}%")
        with d4:
            rsi_val = selected_row.get("rsi", None)
            st.metric("RSI", f"{float(rsi_val):.1f}" if pd.notna(rsi_val) else "-")

        st.info(str(selected_row.get("summary", "-")))
        st.caption(str(selected_row.get("detail_text", "-")))

        # 하단 상세 지표 대조표 확장
        detail_table = pd.DataFrame(
            [
                ["EPS 성장률(%)", "-", selected_row.get("eps_growth", "-")],
                ["과거 평균 PER", "-", selected_row.get("hist_per_avg", "-")],
                ["미국 10년물 금리", "-", selected_row.get("us_10y_bond", "-")],
                ["외인/기관 지분율(%)", "-", selected_row.get("foreign_supply", "-")],
                ["현재 PER", selected_row.get("score_per", 0), selected_row.get("per", "-")],
                ["PBR", selected_row.get("score_pbr", 0), selected_row.get("pbr", "-")],
                ["ROE", selected_row.get("score_roe", 0), selected_row.get("roe", "-")],
                ["PEG", selected_row.get("score_peg", 0), selected_row.get("peg", "-")],
                ["EPS3Y", selected_row.get("score_eps3y", 0), selected_row.get("eps3y", "-")],
                ["CAGR", selected_row.get("score_cagr", 0), selected_row.get("cagr", "-")],
                ["누락지표", "-", selected_row.get("missing_fields", "") or "-"],
            ],
            columns=["항목", "가중점수", "원본값"],
        )
        
        detail_table["가중점수"] = detail_table["가중점수"].astype(str)
        detail_table["원본값"] = detail_table["원본값"].astype(str)
        
        st.dataframe(detail_table, width="stretch", hide_index=True)

    csv_df = display_final_df.copy()
    csv = csv_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv,
        file_name=f"screener_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
elif not st.session_state.searching:
    st.session_state.sidebar_state = "expanded"
    st.info("상단의 [🔍 검색] 버튼을 눌러 분석을 시작하세요.")