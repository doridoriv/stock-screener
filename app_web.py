import os
import pandas as pd
import streamlit as st

import analyzer
from config import APP_TITLE, TABLE_COLUMNS

# ==========================================
# 1. 페이지 및 세션 상태 초기화 (사이드바 자동 제어)
# ==========================================
if "selected_market" not in st.session_state:
    st.session_state.selected_market = "한국(코스피)"
    
if "top_n" not in st.session_state:
    st.session_state.top_n = 50

# 사이드바 초기 상태를 세션에 저장 (기본값: 열림)
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "expanded"

# 시장 교체 시 캐시 데이터를 자동 로드하여 사용자 편의성 제공
def handle_market_change():
    market = st.session_state.selected_market
    market_text = "코스피" if market in ["한국(코스피)", "한국"] else "코스닥" if market == "한국(코스닥)" else "미국"
    latest_date = analyzer.get_latest_market_date(market_text)
    cache_file = os.path.join(analyzer.CACHE_DIR, f"snapshot_{market_text}_{latest_date}.csv")
    
    if os.path.exists(cache_file):
        try:
            df_cached = pd.read_csv(cache_file).head(st.session_state.top_n)
            st.session_state.data = df_cached.to_dict(orient='records')
            st.session_state.sidebar_state = "collapsed"
        except:
            st.session_state.data = []
            st.session_state.sidebar_state = "expanded"
    else:
        st.session_state.data = []
        st.session_state.sidebar_state = "expanded"

# 스타트업 시 기본 캐시 자동 로딩
if "data" not in st.session_state:
    handle_market_change()

st.set_page_config(
    page_title=APP_TITLE, 
    layout="wide", 
    initial_sidebar_state=st.session_state.sidebar_state
)

# ==========================================
# 2. UI 스타일링 (간격 및 여백 극한 압축)
# ==========================================
st.markdown("""
    <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 100%; }
        [data-testid="stDataFrame"] { margin-bottom: 0px; }
        header { visibility: hidden; }
        .sidebar-toggle-hint {
            padding: 10px;
            background-color: rgba(255, 215, 0, 0.05);
            border-left: 5px solid #FFD700;
            margin-bottom: 20px;
            border-radius: 4px;
        }
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
            self.data = item["data"]

# ==========================================
# 4. 좌측 사이드바 컨트롤 패널
# ==========================================
with st.sidebar:
    st.title("📊 장기 투자 스크리너")
    st.caption("2046년 은퇴를 향한 우상향 마라톤")
    
    st.divider()
    
    # selectbox의 key를 세션 상태 변수와 연동하여 자동으로 캐시 룩업 발동
    st.selectbox(
        "🌍 시장 선택", 
        ["한국(코스피)", "한국(코스닥)", "미국"],
        key="selected_market",
        on_change=handle_market_change
    )
    
    st.slider(
        "🔍 탐색 종목 수", 
        10, 100, 50, step=10,
        key="top_n",
        on_change=handle_market_change
    )
    
    st.divider()
    
    # 수동 검색 버튼 (캐시가 이미 있을 때 중복 요청을 유도하지 않기 위해 상태 체크)
    market_text = "코스피" if st.session_state.selected_market in ["한국(코스피)", "한국"] else "코스닥" if st.session_state.selected_market == "한국(코스닥)" else "미국"
    latest_date = analyzer.get_latest_market_date(market_text)
    cache_file = os.path.join(analyzer.CACHE_DIR, f"snapshot_{market_text}_{latest_date}.csv")
    
    button_label = "🚀 종목 분석 시작"
    if os.path.exists(cache_file):
        button_label = "🔄 최신 데이터 강제 갱신"
        st.info("💡 선택하신 시장의 오늘 마감 데이터가 이미 로컬 캐시에 저장되어 있습니다. 최신 수집 데이터가 로딩되었습니다.")
        
    if st.button(button_label, use_container_width=True, type="primary"):
        progress_bar = st.progress(0, text="엔진 예열 중...")
        st_queue = StreamlitQueue(progress_bar)
        
        try:
            # 안전제일 수집 엔진 기동
            analyzer.screening_worker(
                market=st.session_state.selected_market,
                top_n=st.session_state.top_n,
                app_queue=st_queue,
                stop_requested_func=lambda: False,
                opt_fundamental=True,
                opt_peak=True,
                us_market_cap_data=analyzer.load_us_market_cap_cache()
            )
            
            # 수집 완료 후 데이터를 세션에 저장
            if st_queue.data:
                st.session_state.data = st_queue.data
                st.session_state.sidebar_state = "collapsed"
                st.rerun()
            else:
                progress_bar.empty()
                st.warning("⚠️ 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
            
        except Exception as e:
            progress_bar.empty()
            st.error(f"🚨 엔진 오류 발생: {e}")

# ==========================================
# 5. 메인 대시보드 화면 및 컬러 렌더링
# ==========================================
st.header(f"🎯 {st.session_state.selected_market} 핵심 종목 분석 결과")

if st.session_state.data:
    df = pd.DataFrame(st.session_state.data)
    
    # config.py의 TABLE_COLUMNS 기반 한글 컬럼명 매핑
    col_map = {col["id"]: col["text"] for col in TABLE_COLUMNS}
    df_renamed = df.rename(columns=col_map)
    
    display_cols = [col["text"] for col in TABLE_COLUMNS if col["text"] in df_renamed.columns]
    df_display = df_renamed[display_cols]
    
    # 텍스트와 숫자가 섞여 연산 오류를 내는 것을 방지하기 위해 수치형 변환
    float_cols = ["EPS성장률(%)", "과거평균PER", "현재PER", "PBR", "ROE(%)", "PEG", "CAGR(%)", "최고점대비(%)", "200일괴리율(%)", "RSI", "외인/기관지분(%)", "美10년물금리"]
    for col in float_cols:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
            
    # --- [데이터 프레임 컬러 & 스타일링 로직] ---
    def highlight_grade(val):
        """등급별 가시성 높은 색상 적용"""
        if val == 'S': return 'color: #D100D1; font-weight: bold;'
        elif val == 'A': return 'color: #00D100; font-weight: bold;'
        elif val == 'B': return 'color: #E6B800; font-weight: bold;'
        elif val in ['C', 'D']: return 'color: #FF4B4B;'
        return ''

    def color_kr_style(val):
        """플러스는 빨강, 마이너스는 파랑 (HTS/MTS 표준)"""
        try:
            v = float(str(val).replace(',', '').replace('%', '').replace('원', '').replace('$', ''))
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
    styled_df = df_display.style
    style_method = styled_df.map if hasattr(styled_df, "map") else styled_df.applymap
    
    if "등급" in df_display.columns:
        styled_df = style_method(highlight_grade, subset=["등급"])
        
    if "종합점수" in df_display.columns:
        styled_df = style_method(highlight_score, subset=["종합점수"])
        
    # 색상을 입힐 핵심 지표 컬럼
    color_cols = [c for c in ["EPS성장률(%)", "200일괴리율(%)", "최고점대비(%)", "ROE(%)"] if c in df_display.columns]
    if color_cols:
        styled_df = style_method(color_kr_style, subset=color_cols)

    # 포맷 딕셔너리 빌딩 (단위 바인딩 및 빈 칸 처리)
    fmt_dict = {}
    is_kr = st.session_state.selected_market.startswith("한국")
    for col in df_display.columns:
        if col in ["현재가", "최고점", "200일선"]:
            fmt_dict[col] = (lambda x, is_kr=is_kr: f"{int(x):,}원" if pd.notna(x) and is_kr else f"${x:,.2f}" if pd.notna(x) else "-")
        elif col == "시가총액(억)":
            fmt_dict[col] = (lambda x, is_kr=is_kr: f"{int(x):,}억" if pd.notna(x) and is_kr else f"${int(x):,}억" if pd.notna(x) else "-")
        elif col in ["EPS성장률(%)", "ROE(%)", "최고점대비(%)", "200일괴리율(%)", "CAGR(%)", "외인/기관지분(%)", "美10년물금리"]:
            fmt_dict[col] = (lambda x: f"{x:,.2f}%" if pd.notna(x) else "-")
        elif col in ["과거평균PER", "현재PER", "PBR", "PEG", "RSI"]:
            fmt_dict[col] = (lambda x: f"{x:,.2f}" if pd.notna(x) else "-")

    styled_df = styled_df.format(fmt_dict, na_rep="-")

    # 사이드바가 닫혔을 때 다시 켜는 힌트 출력
    if st.session_state.sidebar_state == "collapsed":
        st.markdown(
            '<div class="sidebar-toggle-hint">💡 다른 시장 분석 또는 종목 개수 조정을 원하시면 좌측 상단의 <b>&gt;</b> 화살표를 눌러 사이드바를 펼쳐주세요.</div>', 
            unsafe_allow_html=True
        )

    # --- [최종 화면 렌더링] ---
    # use_container_width=True: 가로 길이에 맞추되 columns가 반응형으로 자동 정렬
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

else:
    st.info("👈 왼쪽 사이드바에서 시장 및 분석 개수를 선택하고 [🚀 종목 분석 시작] 버튼을 눌러주세요.")