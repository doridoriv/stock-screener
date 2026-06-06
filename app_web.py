import streamlit as st
import pandas as pd
import time
import queue
import threading
from datetime import datetime
import os

import analyzer
from config import APP_TITLE

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(f"🚀 {APP_TITLE}")
st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

opt_fundamental = st.sidebar.checkbox("기본적 분석 포함 (PER/PBR)", value=True)
opt_peak = st.sidebar.checkbox("고점 대비 하락율 포함", value=True)

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []

# ==============================================================================
# 데이터 포맷팅 및 스타일러 정의 (요청사항 반영)
# ==============================================================================
def style_screener_dataframe(df, market_type):
    formatted_df = df.copy()
    is_us = (market_type == "미국")
    
    # [요청사항 4] 금액 데이터 3자리 콤마 처리 명시
    if "market_cap" in formatted_df.columns:
        formatted_df["market_cap"] = formatted_df["market_cap"].apply(
            lambda x: f"{int(x):,}억" if pd.notna(x) and x > 0 else "N/A"
        )
    if "price" in formatted_df.columns:
        formatted_df["price"] = formatted_df["price"].apply(
            lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
        )
    if "ma200" in formatted_df.columns:
        formatted_df["ma200"] = formatted_df["ma200"].apply(
            lambda x: f"${x:,.2f}" if is_us else f"{int(x):,}원" if pd.notna(x) else "-"
        )
    if "diff" in formatted_df.columns:
        formatted_df["diff"] = formatted_df["diff"].apply(
            lambda x: f"+{x:.2f}%" if pd.notna(x) and x > 0 else f"{x:.2f}%" if pd.notna(x) and x < 0 else "0.00%"
        )
    if "rsi" in formatted_df.columns:
        def format_rsi(v):
            if pd.isna(v): return "-"
            if v >= 70: return f"{v:.1f} (과열)"
            elif v <= 30: return f"{v:.1f} (과매도)"
            elif v >= 50: return f"{v:.1f} (보통)"
            else: return f"{v:.1f} (침체)"
        formatted_df["rsi"] = formatted_df["rsi"].apply(format_rsi)
        
    # 모든 컬럼 안전 문자열 변환
    for col in formatted_df.columns:
        formatted_df[col] = formatted_df[col].astype(str)
        
    # 출력용 한글 헤더 매핑
    rename_dict = {
        "rank": "순위", "symbol": "티커", "name": "종목명", "data_date": "기준일",
        "market_cap": "시가총액(억)", "price": "현재가", "peak": "최고점",
        "peak_diff": "최고점대비", "ma200": "200일선", "diff": "200일괴리율(%)",
        "rsi": "RSI(14)", "per": "PER 등급", "pbr": "PBR 등급"
    }
    formatted_df = formatted_df.rename(columns=rename_dict)
    
    # [요청사항 2, 3] 전체 수치 항목 가운데 정렬 및 줄바꿈(Wrap) 차단 CSS 주입
    styler = formatted_df.style.set_properties(**{
        'text-align': 'center',
        'white-space': 'nowrap'
    })
    
    # [요청사항 5] 최고점대비 / 괴리율 양수·음수 컬러링 규칙
    def apply_strict_color_rules(val):
        if isinstance(val, str):
            if "+" in val or "🔴" in val:
                return "color: #D32F2F; font-weight: bold;"
            if "-" in val or "🔵" in val:
                return "color: #1976D2; font-weight: bold;"
        return "color: #212121;"
        
    target_cols = [c for c in ["최고점대비", "200일괴리율(%)"] if c in formatted_df.columns]
    if target_cols:
        styler = styler.map(apply_strict_color_rules, subset=target_cols)
        
    return styler

# 검색 버튼 트래킹
if st.sidebar.button("🔄 스크리닝 시작"):
    st.session_state.data = []  
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    table_placeholder = st.empty()
    
    app_queue = queue.Queue()
    stop_event = threading.Event()
    
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    worker_thread = threading.Thread(
        target=analyzer.screening_worker,
        args=(
            market, 
            top_n, 
            app_queue, 
            lambda: stop_event.is_set(), 
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
                
                # 실시간 테이블에도 스타일 포맷 적용 및 [로그 경고 해결] width='stretch' 변경
                styled_live_df = style_screener_dataframe(df, market)
                table_placeholder.dataframe(styled_live_df, width='stretch', hide_index=True)
                
            elif m_type == "done":
                progress_bar.progress(1.0)
                status_text.success(msg["text"])
                break
                
            elif m_type == "error":
                st.error(msg["text"])
                break
                
            elif m_type == "stopped":
                st.warning(f"분석 중지: {msg['count']}개 완료")
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
    
    # 최종 결과 스타일 뷰 가공
    styled_final_df = style_screener_dataframe(final_df, market)
    
    # [로그 경고 해결] use_container_width=True 대신 표준 width='stretch' 명시 적용
    # [요청사항 1] hide_index=True 좌측 공백 인덱스 열 제거 완료
    st.dataframe(
        styled_final_df,
        width='stretch',
        height=650,
        hide_index=True
    )
    
    # 다운로드용 데이터프레임 헤더 정리
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
    st.info("사이드바의 [스크리닝 시작] 버튼을 눌러 분석을 시작하세요.")