import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE, CACHE_DIR

st.set_page_config(page_title=APP_TITLE, layout=\"wide\")

# 장표 가로 스크롤 방지 텍스트 줄바꿈 CSS 설정 유지
st.markdown(\"\"\"
<style>
[data-testid=\"stDataFrame\"] div[role=\"gridcell\"],\n[data-testid=\"stDataFrame\"] div[role=\"columnheader\"] {
    white-space: nowrap !important;
}
</style>
\"\"\", unsafe_allow_html=True)

st.title(f\"🚀 {APP_TITLE}\")
st.markdown("웹 브라우저에서 실시간으로 마켓 펀더멘털을 분석하고 종합 가점 등급별 최적 주식을 쇼핑합니다.")

st.sidebar.header(\"🔍 스크리너 설정\")
market = st.sidebar.selectbox(\"시장 선택\", [\"미국\", \"한국(코스피)\", \"한국(코스닥)\"])
top_n = st.sidebar.slider(\"분석 대상 종목 수 (시총 상위)\", 5, 100, 50)

if \"data\" not in st.session_state:
    st.session_state.data = []

if \"stop_event\" not in st.session_state:
    st.session_state.stop_event = None

if \"us_cap_data\" not in st.session_state:
    st.session_state.us_cap_data = analyzer.load_us_market_cap_cache()

col1, col2, col3, col_empty = st.columns([1.2, 1.2, 1.2, 5])

with col1:
    btn_search = st.button(\"🔍 실시간 검색\", use_container_width=True)
with col2:
    btn_load = st.button(\"📂 캐시 불러오기\", use_container_width=True)
with col3:
    btn_stop = st.button(\"⏹ 검색 중지\", use_container_width=True)

# 중지 토글 제어 메커니즘
if btn_stop:
    if st.session_state.stop_event is not None:
        st.session_state.stop_event.set()
        st.warning("⚠️ 사용자의 중지 신호 요청을 백엔드 워커 스레드에 송신했습니다.")

# 데이터 불러오기/수집 제어 트리거 실행 구조
if btn_search:
    st.session_state.data = []
    st.session_state.stop_event = threading.Event()
    
    app_queue = queue.Queue()
    stop_func = lambda: st.session_state.stop_event.is_set()
    
    t_worker = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, top_n, app_queue, stop_func, True, True, st.session_state.us_cap_data)
    )
    t_worker.start()
    
    status_box = st.empty()
    progress_bar = st.progress(0)
    
    collected_records = []
    while t_worker.is_alive() or not app_queue.empty():
        try:
            packet = app_queue.get(timeout=0.1)
            if packet.get("type") == "data":
                collected_records.append(packet["data"])
                status_box.info(f"⚡ 실시간 실적 연산 수집 진행중... 현재 {len(collected_records)}개 종목 완료")
            elif packet.get("type") == "info":
                st.info(packet.get("text"))
            elif packet.get("type") == "error":
                st.error(f"❌ 분석 엔진 크래시: {packet.get('text')}")
            elif packet.get("type") == "done":
                break
        except queue.Empty:
            continue
            
    t_worker.join()
    st.session_state.data = collected_records
    status_box.success(f"🎉 {market} 시장 스크리닝이 완료되었습니다!")
    progress_bar.progress(100)

if btn_load:
    m_type = "US" if "미국" in market else "KOSPI" if "코스피" in market else "KOSDAQ"
    auto_file_path = os.path.join(CACHE_DIR, f"screener_auto_save_{m_type}.csv")
    cron_file_path = os.path.join(CACHE_DIR, f"screener_data_{market}.csv")
    
    target_path = auto_file_path if os.path.exists(auto_file_path) else cron_file_path if os.path.exists(cron_file_path) else None
    
    if target_path and os.path.exists(target_path):
        try:
            loaded_df = pd.read_csv(target_path, encoding='utf-8-sig')
            # 결측 백업용 등급 보완 계산 검증 안전장치
            if "grade" not in loaded_df.columns:
                grades, comments = [], []
                for _, r in loaded_df.iterrows():
                    g, c = analyzer.evaluate_stock_grade(dict(r))
                    grades.append(g)
                    comments.append(c)
                loaded_df["grade"] = grades
                loaded_df["comment"] = comments
            st.session_state.data = loaded_df.to_dict(orient='records')
            st.success(f"📂 로컬 백업 동기화 데이터 캐시 로드 성공 ({len(st.session_state.data)}개 항목)")
        except Exception as e:
            st.error(f"캐시 파일을 불러오는 중 오류 발생: {e}")
    else:
        st.error("📂 분석 완료된 과거 캐시나 로컬 자동 저장 파일을 시스템에서 찾을 수 없습니다. '실시간 검색'을 수행해 주세요.")

# 스타일 가독성 매핑 핸들러 규칙 유지 정의
def style_screener_dataframe(df, m_ctx):
    def color_per(v):
        try:
            val = float(v)
            if pd.isna(val): return ""
            if val <= 5: return "color: #0D47A1; font-weight: bold;"  # 진파랑
            elif val <= 10: return "color: #1976D2; font-weight: bold;"  # 파랑
            elif val <= 15: return "color: #4FC3F7; font-weight: bold;"  # 하늘
            elif val <= 20: return "color: #EF6C00; font-weight: bold;"  # 주황
            else: return "color: #D32F2F; font-weight: bold;"  # 빨강
        except: return ""

    def color_pbr(v):
        try:
            val = float(v)
            if pd.isna(val) or val <= 0: return "color: #757575; font-style: italic;"
            if val <= 1.0: return "background-color: #E3F2FD; color: #0D47A1; font-weight: bold;"
            elif val >= 3.0: return "color: #C62828;"
        except: return ""

    def color_rsi(v):
        try:
            val = float(v)
            if val >= 70: return "color: #D32F2F; font-weight: bold;"
            elif val >= 50: return "color: #EF6C00; font-weight: bold;"
            elif val >= 30: return "color: #1976D2; font-weight: bold;"
            else: return "color: #0D47A1; font-weight: bold;"
        except: return ""

    def color_roe(v):
        try:
            val = float(v)
            if val >= 15: return "background-color: #E8F5E9; color: #2E7D32; font-weight: bold;"
        except: return ""
        
    def color_grade(v):
        if v == "A": return "background-color: #E3F2FD; color: #0D47A1; font-weight: bold; text-align: center;"
        elif v == "B": return "background-color: #E8F5E9; color: #2E7D32; font-weight: bold; text-align: center;"
        elif v == "C": return "background-color: #FFFDE7; color: #F57F17; font-weight: bold; text-align: center;"
        elif v == "D": return "background-color: #FFEBEE; color: #C62828; font-weight: bold; text-align: center;"
        return "text-align: center;"

    styler = df.style
    if "per" in df.columns: styler = styler.map(color_per, subset=["per"])
    if "pbr" in df.columns: styler = styler.map(color_pbr, subset=["pbr"])
    if "rsi" in df.columns: styler = styler.map(color_rsi, subset=["rsi"])
    if "roe" in df.columns: styler = styler.map(color_roe, subset=["roe"])
    if "grade" in df.columns: styler = styler.map(color_grade, subset=["grade"])
    
    fmt_p = "{:.2f}" if "미국" in m_ctx else "{:,.0f}"
    fmt_sign = "${}" if "미국" in m_ctx else "{}원"
    
    styler = styler.format({
        "price": lambda x: fmt_sign.format(fmt_p.format(x)) if pd.notna(x) else "-",
        "market_cap": "{:,.0f}억" if "한국" in m_ctx else "{:,.1f}억불",
        "peak_diff": "{:+.1f}%", "diff": "{:+.1f}%", "rsi": "{:.1f}",
        "per": "{:.1f}", "pbr": "{:.2f}", "roe": "{:.1f}%", "peg": "{:.2f}", "cagr": "{:.1f}%"
    }, na_rep="-")
    return styler

# 메인 렌더링 파이프라인 구간 시작
if st.session_state.data:
    final_df = pd.DataFrame(st.session_state.data)
    
    # 시총 내림차순 정렬 기능 및 고유 순위 재정의 유지
    if "market_cap" in final_df.columns and len(final_df) > 0:
        final_df = final_df.sort_values(by="market_cap", ascending=False)
        final_df["rank"] = range(1, len(final_df) + 1)

    date_val = final_df["data_date"].iloc[0] if "data_date" in final_df.columns and len(final_df) > 0 else datetime.now().strftime('%Y-%m-%d')
    
    # ------------------ [누락되었던 등급제 대시보드 UI 완벽 구현 구간] ------------------
    st.markdown("---")
    st.markdown(f\"\"\"
    <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;'>
        <h3 style='margin: 0;'>📊 종합 스크리닝 요약</h3>
        <span style='background-color: #E5E7EB; padding: 6px 14px; border-radius: 20px; font-weight: bold; font-size: 14px; color: #1F2937;'>📅 기준일 {date_val}</span>
    </div>
    \"\"\", unsafe_allow_html=True)
    
    # 등급 개수 산출 연산
    a_cnt = len(final_df[final_df["grade"] == "A"])
    b_cnt = len(final_df[final_df["grade"] == "B"])
    c_cnt = len(final_df[final_df["grade"] == "C"])
    d_cnt = len(final_df[final_df["grade"] == "D"])
    
    # 메트릭 대시보드 스코어 카드 배치
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric(label="🟦 A등급 (최우선 관찰)", value=f"{a_cnt}개")
    mc2.metric(label="🟩 B등급 (우량 관심)", value=f"{b_cnt}개")
    mc3.metric(label="🟨 C등급 (중립 관망)", value=f"{c_cnt}개")
    mc4.metric(label="🟥 D등급 (투자 주의)", value=f"{d_cnt}개")
    
    # A등급 핵심 탑픽 종목 요약 알림창 노출
    st.markdown("### 🔍 가장 먼저 차트를 열어볼 최우선 후보 (A등급)")
    a_candidates = final_df[final_df["grade"] == "A"]
    if not a_candidates.empty:
        for _, row in a_candidates.iterrows():
            st.success(f"**[{row['symbol']}] {row['name']}** — {row['comment']} (PER: {row['per']:.1f} / PBR: {row['pbr']:.2f} / ROE: {row['roe']:.1f}% / PEG: {row['peg']:.2f})")
    else:
        st.info("💡 현재 조건에서 최고 점수를 획득한 A등급 종목이 없습니다. 검색 대상을 확대하거나 아래 B등급 주식을 눈여겨보세요.")
    # ----------------------------------------------------------------------------------

    st.markdown("### 📋 상세 주식 분석 데이터 시트")
    
    # 네이버 금융 / 야후 파이낸스 반응형 하이퍼링크 매핑 규칙 유지
    if "미국" in market:
        link_template = "https://m.stock.naver.com/worldstock/stock/{symbol}/total"
        final_df["url_symbol"] = final_df["symbol"].apply(lambda s: "BRKb" if s == "BRK-B" else s)
    else:
        link_template = "https://finance.naver.com/item/main.naver?code={symbol}"
        final_df["url_symbol"] = final_df["symbol"]
        
    final_df["link"] = final_df["url_symbol"].apply(lambda s: link_template.format(symbol=s))
    
    link_config = {
        "link": st.column_config.LinkColumn("바로가기", help="클릭 시 네이버 금융 상세 페이지로 이동합니다.", text="금융링크"),
        "grade": st.column_config.TextColumn("등급", width="small")
    }

    column_order = ["rank", "grade", "symbol", "name", "market_cap", "price", "peak_diff", "diff", "rsi", "per", "pbr", "roe", "peg", "eps3y", "cagr", "link"]
    available_cols = [c for c in column_order if c in final_df.columns]
    
    display_final_df = final_df[available_cols]
    styled_final_df = style_screener_dataframe(display_final_df, market)
    
    st.dataframe(
        styled_final_df,
        use_container_width=True,
        height=550,
        hide_index=True,
        column_config=link_config,
        selection_mode="row"
    )