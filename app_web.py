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

# 사이드바 초기 상태를 세션에 저장 (기본값: 닫힘)
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "collapsed"

# 시장 교체 시 캐시 데이터를 자동 로드하여 사용자 편의성 제공
def handle_market_change():
    market = st.session_state.selected_market
    market_text = "코스피" if market in ["한국(코스피)", "한국"] else "코스닥" if market == "한국(코스닥)" else "미국"
    cache_file = analyzer.find_latest_valid_cache(market_text)
    
    if cache_file and os.path.exists(cache_file):
        try:
            df_cached = pd.read_csv(cache_file)
            if len(df_cached) >= st.session_state.top_n:
                df_cached = df_cached.head(st.session_state.top_n)
                st.session_state.data = df_cached.to_dict(orient='records')
                st.session_state.sidebar_state = "collapsed"
            else:
                # 캐시된 종목 수가 원하는 개수보다 적으면 데이터 분석을 직접 실행하도록 비움
                st.session_state.data = []
        except:
            st.session_state.data = []
    else:
        st.session_state.data = []

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
    st.info("💡 모든 시장 분석 및 데이터 갱신 기능은 메인 화면 상단의 컨트롤 패널을 이용해 주세요. 사이드바는 더 넓은 화면을 위해 자동으로 닫힙니다.")

# ==========================================
# 5. 메인 대시보드 화면 및 컨트롤 패널
# ==========================================
st.header(f"🎯 {st.session_state.selected_market} 핵심 종목 분석 결과")

# 메인 화면 상단에 3개 컬럼으로 구성된 컨트롤 패널 배치 (사이드바가 닫혀있어도 항상 검색 가능)
col1, col2, col3 = st.columns([3, 3, 2], vertical_alignment="bottom")

with col1:
    st.selectbox(
        "🌍 시장 선택", 
        ["한국(코스피)", "한국(코스닥)", "미국"],
        key="selected_market",
        on_change=handle_market_change
    )

with col2:
    st.slider(
        "🔍 탐색 종목 수", 
        10, 100, 50, step=10,
        key="top_n",
        on_change=handle_market_change
    )

with col3:
    market_text = "코스피" if st.session_state.selected_market in ["한국(코스피)", "한국"] else "코스닥" if st.session_state.selected_market == "한국(코스닥)" else "미국"
    cache_file = analyzer.find_latest_valid_cache(market_text)
    
    button_label = "🚀 종목 분석 시작"
    if cache_file and os.path.exists(cache_file):
        button_label = "🔄 데이터 강제 갱신"
        
    if st.button(button_label, use_container_width=True, type="primary"):
        progress_bar = st.progress(0, text="엔진 예열 중...")
        st_queue = StreamlitQueue(progress_bar)
        
        try:
            # 안전제일 수집 엔진 기동 (force_scrape=True로 강제 분석 실행)
            analyzer.screening_worker(
                market=st.session_state.selected_market,
                top_n=st.session_state.top_n,
                app_queue=st_queue,
                stop_requested_func=lambda: False,
                opt_fundamental=True,
                opt_peak=True,
                us_market_cap_data=analyzer.load_us_market_cap_cache(),
                force_scrape=True
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

st.divider()

if st.session_state.data:
    df = pd.DataFrame(st.session_state.data)
    
    # config.py의 TABLE_COLUMNS 기반 한글 컬럼명 매핑
    col_map = {col["id"]: col["text"] for col in TABLE_COLUMNS}
    df_renamed = df.rename(columns=col_map)
    
    display_cols = [col["text"] for col in TABLE_COLUMNS if col["text"] in df_renamed.columns]
    df_display = df_renamed[display_cols]
    
    # 수치형 컬럼 변환 (sorting 및 format 적용을 위해)
    numeric_ids = ["rank", "score", "eps_growth", "hist_per_avg", "us_10y_bond", "foreign_supply", 
                   "market_cap", "price", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "cagr"]
    numeric_cols = [col_map[idx] for idx in numeric_ids if idx in col_map]
    
    for col in numeric_cols:
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
            v = float(val)
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

    # --- [Streamlit Native Column Config] ---
    # 문자/숫자에 따라 컬럼 정렬(오른쪽/왼쪽) 및 포맷 단위(원, $, %, 억 등)를
    # 데이터 타입을 보존하면서 브라우저가 자동 너비 조절하도록 설정
    is_kr = st.session_state.selected_market.startswith("한국")
    col_config = {}
    
    for col in TABLE_COLUMNS:
        col_id = col["id"]
        col_text = col["text"]
        
        if col_text not in df_display.columns:
            continue
            
        if col_id in ["price", "peak", "ma200"]:
            fmt = "%d원" if is_kr else "$%,.2f"
            col_config[col_text] = st.column_config.NumberColumn(col_text, format=fmt)
        elif col_id == "market_cap":
            fmt = "%,d억" if is_kr else "$%,d억"
            col_config[col_text] = st.column_config.NumberColumn(col_text, format=fmt)
        elif col_id in ["eps_growth", "roe", "peak_diff", "diff", "cagr", "foreign_supply", "us_10y_bond"]:
            col_config[col_text] = st.column_config.NumberColumn(col_text, format="%.2f%%")
        elif col_id in ["hist_per_avg", "per", "pbr", "peg", "rsi"]:
            col_config[col_text] = st.column_config.NumberColumn(col_text, format="%.2f")
        elif col_id in ["rank", "score"]:
            col_config[col_text] = st.column_config.NumberColumn(col_text, format="%d")
        else:
            col_config[col_text] = st.column_config.TextColumn(col_text)

    # --- [최종 화면 렌더링] ---
    # use_container_width=True: 브라우저 크기에 맞추되 column_config로 각 데이터에 맞게 최적 너비 설정
    st.dataframe(styled_df, use_container_width=True, hide_index=True, column_config=col_config)

else:
    st.info("💡 위 컨트롤 패널에서 시장 및 분석 개수를 선택하고 [🚀 종목 분석 시작] 버튼을 눌러주세요.")