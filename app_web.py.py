import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE, CACHE_DIR, COL_INFOS  # [수정] 너비 설정을 읽어오기 위해 COL_INFOS 추가

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
# [개선] 시장 선택지를 한국(코스피)과 한국(코스닥)으로 분리하여 총 3개의 세부 선택지로 확장
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
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
# 데이터 포맷팅 및 스타일러 정의 (숫자 원본 정렬 시스템 반영)
# ==============================================================================
def style_screener_dataframe(df, market_type):
    formatted_df = df.copy()
    is_us = (market_type == "미국")
    
    # 티커와 종목명 모두 클릭 시 네이버 실제 확인 주소로 완벽 매핑 및 텍스트 유지 자동화
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
        "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)
    
    styler = formatted_df.style
    
    # 정렬 작동을 위해 형변환을 가하지 않고 .style.format() 분기를 이용해 렌더링을 처리합니다.
    format_dict = {}
    if "시가총액(억)" in formatted_df.columns:
        format_dict["시가총액(억)"] = lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "N/A"
    if "현재가" in formatted_df.columns:
        format_dict["현재가"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "200일선" in formatted_df.columns:
        format_dict["200일선"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점" in formatted_df.columns:
        format_dict["최고점"] = lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
    if "최고점대비" in formatted_df.columns:
        format_dict["최고점대비"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%"
    if "200일괴리율(%)" in formatted_df.columns:
        format_dict["200일괴리율(%)"] = lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%"
    if "RSI(14)" in formatted_df.columns:
        def format_rsi_web(v):
            if pd.isna(v): return "-"
            v = float(v)
            if v >= 70: return f"{v:.1f} (과열)"
            elif v <= 30: return f"{v:.1f} (과매도)"
            elif v >= 50: return f"{v:.1f} (보통)"
            else: return f"{v:.1f} (침체)"
        format_dict["RSI(14)"] = format_rsi_web
    if "PER 등급" in formatted_df.columns:
        format_dict["PER 등급"] = lambda x: analyzer.get_per_grade(x)
    if "PBR 등급" in formatted_df.columns:
        format_dict["PBR 등급"] = lambda x: analyzer.get_pbr_grade(x)
        
    styler = styler.format(format_dict)
    
    styler = styler.set_properties(**{
        'text-align': 'center',
        'white-space': 'nowrap'
    })
    
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
        
    target_cols = [c for c in ["최고점대비", "200일괴리율(%)"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
        
    return styler

# ==============================================================================
# [수정] config.py의 COL_INFOS 설정을 완벽하게 빌드하여 정밀한 픽셀 너비를 전달하는 링커 맵 생성
# ==============================================================================
id_to_web_name = {
    "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
    "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
    "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
    "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
}

link_config = {}
for col in COL_INFOS:
    col_id = col["id"]
    web_name = id_to_web_name.get(col_id, col_id)
    width = col.get("width", 100)
    
    if col_id == "symbol":
        link_config[web_name] = st.column_config.LinkColumn(web_name, display_text=r"ticker=([^&]*)", width=width)
    elif col_id == "name":
        link_config[web_name] = st.column_config.LinkColumn(web_name, display_text=r"name=([^&]*)", width=width)
    else:
        link_config[web_name] = st.column_config.Column(web_name, width=width)

# 검색 버튼 트래킹 및 메인 코어 루프 엔진 실행
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
        args=(
            market, 
            top_n, 
            app_queue, 
            lambda: current_stop_event.is_set(), 
            opt_fundamental, 
            opt_peak, 
            us_market_cap_data
        ),
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
                column_order = [
                    "rank", "symbol", "name", "data_date", "market_cap", "price", 
                    "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr"
                ]
                available_cols = [c for c in column_order if c in df.columns]
                df = df[available_cols]
                
                styled_live_df = style_screener_dataframe(df, market)
                
                # 실시간 테이블 표 행 클릭 하이라이트 및 더블 링크 모드 주입
                # [수정] 무분별하게 늘어나는 stretch 대신 정밀 너비 제어가 먹히도록 'content'로 전환
                table_placeholder.dataframe(
                    styled_live_df, 
                    width='content', 
                    hide_index=True,
                    column_config=link_config,
                    selection_mode="row"
                )
                
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
    
    # 행의 빈 영역 클릭 시 가로 전체 블록 하이라이트 고정 적용 완료
    # [수정] 무분별하게 늘어나는 stretch 대신 정밀 너비 제어가 먹히도록 'content'로 전환
    st.dataframe(
        styled_final_df,
        width='content',
        height=650,
        hide_index=True,
        column_config=link_config,
        selection_mode="row"
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