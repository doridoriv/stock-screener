import os
import pandas as pd
import streamlit as st

import analyzer
from config import APP_TITLE, TABLE_COLUMNS

# ==========================================
# 1. 페이지 및 세션 상태 초기화
# ==========================================
st.set_page_config(page_title=APP_TITLE, layout="wide")

if "data" not in st.session_state:
    st.session_state.data = []

# ==========================================
# 2. UI 스타일링 (불필요한 빈 공간 및 여백 완벽 제거)
# ==========================================
st.markdown("""
    <style>
        /* 전체 컨테이너 상하 여백 압축 */
        .block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 100%; }
        
        /* 테이블 줄과 줄 사이 빈 공간 삭제 및 타이트한 배치 */
        [data-testid="stDataFrame"] { margin-bottom: 0px; }
        [data-testid="stTable"] { margin-bottom: 0px; }
        .stDataFrame div[data-testid="stVirtualizedTable"] div {
            line-height: 1.2 !important;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 브릿지 클래스 (analyzer.py의 진행 상태를 Streamlit UI로 연결)
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
    
    # 스레딩 없이 초고속 동기식 실행
    if st.button("🚀 종목 분석 시작", use_container_width=True, type="primary"):
        st.session_state.data = [] # 이전 데이터 초기화
        
        progress_bar = st.progress(0, text="엔진 예열 중...")
        st_queue = StreamlitQueue(progress_bar)
        
        try:
            # analyzer의 고속 수집기 직접 호출 (수 초 내 완료)
            analyzer.screening_worker(
                market=selected_market,
                top_n=top_n,
                app_queue=st_queue,
                stop_requested_func=lambda: False,
                opt_fundamental=True,
                opt_peak=True,
                us_market_cap_data=analyzer.load_us_market_cap_cache()
            )
            
            st.session_state.data = st_queue.data
            progress_bar.empty()
            st.success("✅ 스크리닝 완료!")
            
        except Exception as e:
            progress_bar.empty()
            st.error(f"🚨 엔진 오류 발생: {e}")

# ==========================================
# 5. 메인 대시보드 화면
# ==========================================
st.header(f"🎯 {selected_market} 핵심 종목 분석 결과")

if st.session_state.data:
    df = pd.DataFrame(st.session_state.data)
    
    # config.py의 TABLE_COLUMNS를 기반으로 한글 컬럼명 매핑 및 필터링
    col_map = {col["id"]: col["text"] for col in TABLE_COLUMNS}
    df_renamed = df.rename(columns=col_map)
    
    display_cols = [col["text"] for col in TABLE_COLUMNS if col["text"] in df_renamed.columns]
    df_display = df_renamed[display_cols]
    
    # hide_index=True 옵션으로 좌측의 불필요한 인덱스 번호 공간 삭제
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    
else:
    st.info("👈 왼쪽 사이드바에서 [🚀 종목 분석 시작] 버튼을 눌러주세요. VOO, QQQM, TSLA 등 핵심 우량주 데이터를 고속으로 스캔합니다.")