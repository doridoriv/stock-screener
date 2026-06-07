import streamlit as st
import pandas as pd
import time
from datetime import datetime
import os
import analyzer
from config import APP_TITLE, CACHE_DIR

# 페이지 설정
st.set_page_config(page_title=APP_TITLE, layout="wide")

# ==============================================================================
# UI 레이아웃 및 헤더 (기준일 이동 반영)
# ==============================================================================
col_title, col_date = st.columns([3, 1])
with col_title:
    st.title(f"🚀 {APP_TITLE}")
with col_date:
    st.markdown("<br>", unsafe_allow_html=True) # 위쪽 여백
    st.markdown(f"**📊 분석 결과** &nbsp;&nbsp; 📅 기준일: {datetime.now().strftime('%Y-%m-%d')}")

st.markdown("웹 브라우저에서 실시간으로 주식 데이터를 분석하고 저평가 종목을 찾습니다.")

# 사이드바 설정
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
top_n = st.sidebar.slider("분석 종목 수 (상위)", 1, 100, 50)

opt_fundamental = True
opt_peak = True

# 세션 상태 초기화
if "data" not in st.session_state:
    st.session_state.data = []
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None

# ==============================================================================
# 스타일링 및 컬럼 설정 (공간 최적화 및 RSI 색상/텍스트 개선)
# ==============================================================================
def apply_rsi_color_rules(val):
    try:
        if pd.isna(val) or str(val) == "-": return "color: #212121;"
        v = float(val)
        if v >= 70: return "color: #D32F2F; font-weight: bold;"    # 과열 (빨강)
        elif v >= 50: return "color: #EF6C00; font-weight: bold;"  # 보통 이상 (주황)
        elif v >= 30: return "color: #1976D2; font-weight: bold;"  # 보통 이하 (파랑)
        else: return "color: #0D47A1; font-weight: bold;"          # 과매도 (진파랑)
    except: return "color: #212121;"

def style_screener_dataframe(df):
    # RSI 숫자만 표시하도록 포맷팅
    format_dict = {}
    if "RSI" in df.columns:
        format_dict["RSI"] = lambda x: f"{float(x):.1f}" if pd.notna(x) else "-"
    
    styler = df.style.format(format_dict)
    
    # RSI 색상 규칙 적용
    if "RSI" in df.columns:
        styler = styler.map(apply_rsi_color_rules, subset=["RSI"])
        
    return styler.set_properties(**{'text-align': 'center'})

# 컬럼 구성 최적화
link_config = {
    "순위": st.column_config.NumberColumn("순위", width="small"),
    "티커": st.column_config.TextColumn("티커", width="small"),
    "종목명": st.column_config.TextColumn("종목명", width="medium"),
    "시가총액": st.column_config.NumberColumn("시가총액", width="medium"),
    "현재가": st.column_config.NumberColumn("현재가", width="medium"),
    "최고점": st.column_config.NumberColumn("최고점", width="medium"),
    "최고점대비": st.column_config.NumberColumn("최고점대비", width="small"),
    "200일선": st.column_config.NumberColumn("200일선", width="medium"),
    "200일괴리율": st.column_config.NumberColumn("200일괴리율", width="small"),
    "RSI": st.column_config.NumberColumn("RSI", width="small"),
    "PER": st.column_config.NumberColumn("PER", width="small"),
    "PBR": st.column_config.NumberColumn("PBR", width="small"),
    "ROE": st.column_config.NumberColumn("ROE", width="small"),
}

# ==============================================================================
# 메인 로직 실행부
# ==============================================================================
if st.button("🚀 분석 시작"):
    with st.spinner("데이터 분석 중..."):
        # 분석 로직 호출 (analyzer 모듈 의존)
        raw_data = analyzer.run_screening(market, top_n)
        if raw_data:
            df = pd.DataFrame(raw_data)
            
            # 컬럼명 변경 (RSI(14) -> RSI)
            df.rename(columns={"rsi": "RSI", "per": "PER", "pbr": "PBR", "roe": "ROE", 
                               "rank": "순위", "symbol": "티커", "name": "종목명", 
                               "market_cap": "시가총액", "price": "현재가", 
                               "peak": "최고점", "peak_diff": "최고점대비",
                               "ma200": "200일선", "diff": "200일괴리율"}, inplace=True)
            
            # 표시할 컬럼 순서 지정
            cols_to_show = ["순위", "티커", "종목명", "시가총액", "현재가", "최고점", "최고점대비", "200일선", "200일괴리율", "RSI", "PER", "PBR", "ROE"]
            final_df = df[[c for c in cols_to_show if c in df.columns]]
            
            styled_df = style_screener_dataframe(final_df)
            
            st.dataframe(
                styled_df,
                use_container_width=True, # 가로 폭 최적화
                height=650,
                hide_index=True,
                column_config=link_config
            )
        else:
            st.error("데이터를 가져오는 데 실패했습니다.")