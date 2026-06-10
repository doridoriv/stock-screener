import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import queue
import threading
import time
from datetime import datetime

# 기존 통합된 설정을 config.py에서 로드
from config import APP_TITLE, COL_INFOS
# 최적화된 분석 로직 로드
from analyzer import screening_worker, load_us_market_cap_cache

# ==========================================
# [1] UI 헬퍼 및 스타일링
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")

def get_csv_filename(market_val):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if "미국" in market_val else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

def style_screener_dataframe(df, market_type):
    formatted_df = df.copy()
    is_us = ("미국" in market_type)
    
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
                    suffix = ".N" if sym in nyse_tickers else ".O"
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
        "market_cap": "시가총액", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율",
        "rsi": "RSI", "per": "PER", "pbr": "PBR", "roe": "ROE", "peg": "PEG", "eps3y": "EPS3Y", "cagr": "CAGR"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)
    
    styler = formatted_df.style
    format_dict = {}
    if "순위" in formatted_df.columns: format_dict["순위"] = lambda x: f"{int(x)}" if pd.notna(x) else "-"
    if "시가총액" in formatted_df.columns: format_dict["시가총액"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "-"
    if "현재가" in formatted_df.columns: format_dict["현재가"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "200일선" in formatted_df.columns: format_dict["200일선"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점" in formatted_df.columns: format_dict["최고점"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점대비" in formatted_df.columns: format_dict["최고점대비"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "200일괴리율" in formatted_df.columns: format_dict["200일괴리율"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%" if pd.notna(x) else "-"
    if "RSI" in formatted_df.columns: format_dict["RSI"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PER" in formatted_df.columns: format_dict["PER"] = lambda x: f"{x:.1f}" if pd.notna(x) else "-"
    if "PBR" in formatted_df.columns: format_dict["PBR"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "ROE" in formatted_df.columns: format_dict["ROE"] = lambda x: f"{x:.1f}%" if pd.notna(x) else "-"
    if "PEG" in formatted_df.columns: format_dict["PEG"] = lambda x: f"{x:.2f}" if pd.notna(x) else "-"
    if "EPS3Y" in formatted_df.columns: format_dict["EPS3Y"] = lambda x: str(x) if pd.notna(x) else "-"
    if "CAGR" in formatted_df.columns: format_dict["CAGR"] = lambda x: f"+{x:.1f}%" if pd.notna(x) and x >= 0 else f"{x:.1f}%" if pd.notna(x) else "-"
        
    styler = styler.format(format_dict)
    styler = styler.set_properties(**{'text-align': 'center', 'white-space': 'nowrap'})
    
    def color_per(val):
        try:
            v = float(val); 
            if pd.isna(v): return ""
            if v <= 10: return "color: #0D47A1; font-weight: bold;"
            elif v <= 20: return "color: #1976D2; font-weight: bold;"
            elif v <= 40: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_pbr(val):
        try:
            v = float(val); 
            if pd.isna(v): return ""
            if v <= 1.0: return "color: #0D47A1; font-weight: bold;"
            elif v <= 1.5: return "color: #1976D2; font-weight: bold;"
            elif v <= 3.0: return "color: #E65100; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_roe(val):
        try:
            v = float(val); 
            if pd.isna(v): return ""
            if v >= 20: return "color: #0D47A1; font-weight: bold;"
            elif v >= 10: return "color: #1976D2; font-weight: bold;"
            else: return "color: #D32F2F; font-weight: bold;"
        except: return ""

    def color_rsi(val):
        try:
            v = float(val); 
            if pd.isna(v): return ""
            if v <= 30: return "color: #0D47A1; font-weight: bold;"
            elif v >= 70: return "color: #D32F2F; font-weight: bold;"
            else: return ""
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
    if "ROE" in formatted_df.columns: styler = styler.map(color_roe, subset=["ROE"])
    if "RSI" in formatted_df.columns: styler = styler.map(color_rsi, subset=["RSI"])
        
    target_cols = [c for c in ["최고점대비", "200일괴리율"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
    return styler

def draw_stock_chart(symbol, market_type):
    try:
        is_us = ("미국" in market_type)
        ticker_sym = symbol
        if not is_us:
            suffix = ".KS" if "코스피" in market_type or market_type == "한국" else ".KQ"
            ticker_sym = f"{symbol}{suffix}"
            
        df = yf.download(ticker_sym, period="1y", interval="1d", progress=False)
        if df.empty: return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                           vertical_spacing=0.03, subplot_titles=(f'{symbol} 주가 차트', '거래량'), 
                           row_width=[0.2, 0.7])

        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        
        # 200일 이동평균선 추가
        ma200 = df['Close'].rolling(window=200).mean()
        fig.add_trace(go.Scatter(x=df.index, y=ma200, line=dict(color='orange', width=2), name='200 MA'), row=1, col=1)

        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume'), row=2, col=1)

        fig.update_layout(xaxis_rangeslider_visible=False, height=500, margin=dict(l=10, r=10, t=30, b=10))
        return fig
    except:
        return None

# ==========================================
# [2] 메인 Streamlit 앱
# ==========================================
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown("""
<style>
[data-testid="stDataFrame"] div[role="gridcell"],
[data-testid="stDataFrame"] div[role="columnheader"] {
    white-space: nowrap !important;
}
.main-header { font-size: 2.2rem; font-weight: 800; color: #1E3A8A; margin-bottom: 0.5rem; }
.sub-header { font-size: 1.1rem; color: #64748B; margin-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

if "us_market_cap_data" not in st.session_state:
    st.session_state.us_market_cap_data = load_us_market_cap_cache()
if "data" not in st.session_state:
    st.session_state.data = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

st.markdown(f'<div class="main-header">🚀 {APP_TITLE}</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">실시간 주식 분석 및 저평가 우량주 발굴 시스템 (병렬 가속 엔진 탑재)</div>', unsafe_allow_html=True)

# 사이드바 설정
st.sidebar.header("⚙️ 분석 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"], index=0)
top_n = st.sidebar.slider("분석 종목 수 (상위 시총 기준)", 1, 100, 50)
opt_fundamental = st.sidebar.checkbox("재무 지표 분석 (PER/PBR/ROE)", value=True)
opt_peak = st.sidebar.checkbox("고점 대비 하락률 분석", value=True)

# 메인 컨트롤 버튼
col_c1, col_c2, col_c3, col_c_empty = st.columns([1, 1, 1, 4])
with col_c1:
    btn_search = st.button("🔍 분석 시작", use_container_width=True, type="primary", disabled=st.session_state.is_running)
with col_c2:
    btn_load = st.button("📂 불러오기", use_container_width=True, disabled=st.session_state.is_running)
with col_c3:
    btn_stop = st.button("⏹ 중지", use_container_width=True, disabled=not st.session_state.is_running)

if btn_stop:
    st.session_state.stop_requested = True
    st.toast("중지 요청됨. 현재 작업 중인 종목 완료 후 중단됩니다.")

if btn_load:
    filename = get_csv_filename(market)
    if os.path.exists(filename):
        try:
            st.session_state.data = pd.read_csv(filename, encoding='utf-8-sig').to_dict('records')
            st.success(f"📂 {len(st.session_state.data)}개 종목 데이터를 성공적으로 불러왔습니다.")
        except Exception as e:
            st.error(f"불러오기 실패: {e}")
    else:
        st.warning("오늘 저장된 백업 데이터가 없습니다.")

# 분석 실행 로직
if btn_search:
    st.session_state.data = []
    st.session_state.is_running = True
    st.session_state.stop_requested = False
    
    app_queue = queue.Queue()
    stop_fn = lambda: st.session_state.stop_requested
    
    worker_thread = threading.Thread(
        target=screening_worker,
        args=(market, top_n, app_queue, stop_fn, opt_fundamental, opt_peak, st.session_state.us_market_cap_data),
        daemon=True
    )
    worker_thread.start()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    while True:
        try:
            msg = app_queue.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "progress":
                progress_bar.progress(msg["value"] / 100)
                status_text.text(msg["text"])
            elif m_type == "data":
                st.session_state.data.append(msg["data"])
            elif m_type in ["done", "stopped"]:
                st.session_state.is_running = False
                if st.session_state.data:
                    final_df = pd.DataFrame(st.session_state.data)
                    final_df.to_csv(get_csv_filename(market), index=False, encoding='utf-8-sig')
                if m_type == "done":
                    st.success(f"분석 완료! 총 {len(st.session_state.data)}개 종목이 처리되었습니다.")
                else:
                    st.warning(f"분석 중지됨. {len(st.session_state.data)}개까지 저장되었습니다.")
                break
            elif m_type == "error":
                st.session_state.is_running = False
                st.error(msg["text"])
                break
        except queue.Empty:
            time.sleep(0.1)
            if not worker_thread.is_alive(): break
    
    st.rerun()

# 결과 표시 구역
if st.session_state.data:
    df_display = pd.DataFrame(st.session_state.data)
    
    # 시총 순 정렬 및 순위 재부여
    if "market_cap" in df_display.columns:
        df_display = df_display.sort_values(by="market_cap", ascending=False)
        df_display["rank"] = range(1, len(df_display) + 1)
        
    column_order = [c["id"] for c in COL_INFOS if c["id"] in df_display.columns]
    df_display = df_display[column_order]
    
    date_val = st.session_state.data[0].get("data_date", "-")
    
    st.divider()
    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        st.subheader(f"📊 {market} 분석 결과 (기준일: {date_val})")
    with col_h2:
        csv = df_display.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 CSV 저장", data=csv, file_name=f"screener_{market}_{date_val}.csv", use_container_width=True)

    link_config = {
        "티커": st.column_config.LinkColumn("티커", display_text=r"ticker=([^&]*)", width="small"),
        "종목명": st.column_config.LinkColumn("종목명", display_text=r"name=([^&]*)", width="medium"),
    }
    
    styled_df = style_screener_dataframe(df_display, market)
    
    event = st.dataframe(
        styled_df,
        use_container_width=True,
        height=500,
        hide_index=True,
        column_config=link_config,
        on_select="rerun",
        selection_mode="single_row"
    )

    # 행 선택 시 차트 표시
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_row = df_display.iloc[selected_idx]
        symbol = selected_row['symbol']
        name = selected_row['name']
        
        st.divider()
        st.subheader(f"📈 {name} ({symbol}) 상세 분석")
        
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("현재가", f"${selected_row['price']:,.2f}" if "미국" in market else f"{int(selected_row['price']):,}원")
        m_col2.metric("200일괴리율", f"{selected_row['diff']:.2f}%" if pd.notna(selected_row['diff']) else "-")
        m_col3.metric("RSI", f"{selected_row['rsi']:.1f}")
        if pd.notna(selected_row.get('per')):
            m_col4.metric("PER", f"{selected_row['per']:.1f}")
            
        with st.spinner(f"{name} 차트 로드 중..."):
            fig = draw_stock_chart(symbol, market)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("차트 데이터를 불러올 수 없습니다.")
else:
    if not st.session_state.is_running:
        st.info("상단의 [🔍 분석 시작] 버튼을 클릭하여 스크리닝을 시작하세요.")
