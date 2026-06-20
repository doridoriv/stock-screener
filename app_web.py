import os
import pandas as pd
import streamlit as st

import analyzer
from config import APP_TITLE, TABLE_COLUMNS

# ==========================================
# 1. 페이지 및 세션 상태 초기화 (사이드바 자동 제어)
# ==========================================
# 사이드바 초기 상태를 세션에 저장 (기본값: 열림)
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "expanded"

st.set_page_config(
    page_title=APP_TITLE, 
    layout="wide", 
    initial_sidebar_state=st.session_state.sidebar_state
)

if "data" not in st.session_state:
    st.session_state.data = []

# ==========================================
# 2. UI 스타일링 (간격 및 여백 극한 압축)
# ==========================================
st.markdown("""
    <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 100%; }
        /* 데이터프레임 줄 사이 텅 빈 공간 삭제 */
        [data-testid="stDataFrame"] { margin-bottom: 0px; }
        /* 상단 기본 헤더 공간 숨김 */
        header { visibility: hidden; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 브릿지 클래스 (진행률 상태 표시용)
# ==========================================
class StreamlitQueue:
    def __init__(self, progress_bar):
        self.progress_bar = progress_bar
        self.data = []
        
    def put(self, item):
        if item["type"] == "progress":
            val = max(0, min(100, item["value"]))
            self.progress_bar.progress(val, text=item.get("text", "데이터 고속 수집 중..."))
        elif item["type"] == "data":
            self.data.append(item["data"])

# ==========================================
# 4. 좌측 사이드바 컨트롤 패널
# ==========================================
with st.sidebar:
    st.title("📊 장기 투자 스크리너")
    st.caption("2046년 은퇴를 향한 우상향 마라톤")
    
    st.divider()
    
    selected_market = st.selectbox("🌍 시장 선택", ["미국", "한국(코스피)", "한국(코스닥)"])
    top_n = st.slider("🔍 탐색 종목 수", 10, 200, 50, step=10)
    
    st.divider()
    
    if st.button("🚀 종목 분석 시작", use_container_width=True, type="primary"):
        st.session_state.data = []
        
        progress_bar = st.progress(0, text="엔진 예열 중...")
        st_queue = StreamlitQueue(progress_bar)
        
        try:
            # 1단계에서 완성한 초고속 수집 엔진 가동
            analyzer.screening_worker(
                market=selected_market,
                top_n=top_n,
                app_queue=st_queue,
                stop_requested_func=lambda: False,
                opt_fundamental=True,
                opt_peak=True,
                us_market_cap_data=analyzer.load_us_market_cap_cache()
            )
            
            # 수집 완료 후 데이터를 세션에 저장
            st.session_state.data = st_queue.data
            
            # 🔥 핵심: 사이드바 상태를 '접힘'으로 변경하고 페이지 새로고침
            st.session_state.sidebar_state = "collapsed"
            st.rerun()
            
        except Exception as e:
            progress_bar.empty()
            st.error(f"🚨 엔진 오류 발생: {e}")

# ==========================================
# 5. 메인 대시보드 화면 및 컬러 렌더링
# ==========================================
st.header(f"🎯 {selected_market} 핵심 종목 분석 결과")

if st.session_state.data:
    df = pd.DataFrame(st.session_state.data)
    
    # config.py의 TABLE_COLUMNS 기반 한글 컬럼명 매핑
    col_map = {col["id"]: col["text"] for col in TABLE_COLUMNS}
    df_renamed = df.rename(columns=col_map)
    
    display_cols = [col["text"] for col in TABLE_COLUMNS if col["text"] in df_renamed.columns]
    df_display = df_renamed[display_cols]
    
    # --- [데이터 프레임 컬러 & 스타일링 로직] ---
    def highlight_grade(val):
        """등급별 가시성 높은 색상 적용"""
        if val == 'S': return 'color: #D100D1; font-weight: bold;' # 보라 (S급)
        elif val == 'A': return 'color: #00D100; font-weight: bold;' # 초록
        elif val == 'B': return 'color: #E6B800; font-weight: bold;' # 골드
        elif val in ['C', 'D']: return 'color: #FF4B4B;' # 토마토 빨강
        return ''

    def color_kr_style(val):
        """플러스는 빨강, 마이너스는 파랑 (HTS/MTS 표준)"""
        try:
            v = float(str(val).replace(',', '').replace('%', ''))
            if v > 0: return 'color: #FF4B4B; font-weight: bold;'
            elif v < 0: return 'color: #00BFFF; font-weight: bold;'
        except: pass
        return ''
        
    def highlight_score(val):
        """종합점수 80점 이상 하이라이트"""
        try:
            if float(val) >= 80: return 'color: #FFD700; font-weight: bold; background-color: rgba(255, 215, 0, 0.1);'
        except: pass
        return ''

    # Pandas 버전에 따른 map/applymap 호환 처리
    style_method = df_display.style.map if hasattr(df_display.style, "map") else df_display.style.applymap
    styled_df = df_display.style
    
    if "등급" in df_display.columns:
        styled_df = style_method(highlight_grade, subset=["등급"])
        
    if "종합점수" in df_display.columns:
        styled_df = style_method(highlight_score, subset=["종합점수"])
        
    # 색상을 입힐 핵심 지표 컬럼 추려내기
    color_cols = [c for c in ["EPS성장률(%)", "200일선괴리(%)", "최고점대비(%)", "ROE"] if c in df_display.columns]
    if color_cols:
        styled_df = style_method(color_kr_style, subset=color_cols)

    # 숫자가 깔끔하게 떨어지도록 소수점 2자리 포맷팅 적용
    styled_df = styled_df.format(precision=2)

    # --- [최종 화면 렌더링] ---
    # use_container_width=False: 글자 길이에 맞춰 타이트하게 열 너비가 자동 조절됨 (여백 제거)
    # hide_index=True: 왼쪽에 뜨는 쓸데없는 0, 1, 2 인덱스 번호 삭제
    st.dataframe(styled_df, use_container_width=False, hide_index=True)
    
else:
    st.info("👈 왼쪽 사이드바에서 [🚀 종목 분석 시작] 버튼을 눌러주세요.")