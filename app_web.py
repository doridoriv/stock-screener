import os
import sys
import time
import queue
import threading
from datetime import datetime
import pandas as pd
import streamlit as st

# 엔진 모듈 로드
from analyzer import load_us_market_cap_cache, screening_worker

# 페이지 초기 레이아웃 및 환경 설정
st.set_page_config(
    page_title="글로벌 주식 퀀트 스크리너 엔진",
    page_icon="📈",
    layout="wide"
)

# -----------------------------------------------------------------------------
# [Pandas Styler 전용 포맷터 함수 정의]
# 텍스트 이모지 등급을 화면에 유지하면서 숫자로 완벽하게 정렬을 지원하기 위함
# -----------------------------------------------------------------------------
def format_per_value(val):
    if pd.isna(val) or val is None:
        return "⚪ 정보없음"
    
    try:
        v = float(val)
        if v < 0.0:
            return f"❌ 적자 ({v:.1f})"
        elif v <= 10.0:
            return f"🔵 초저평가 ({v:.1f})"
        elif v <= 20.0:
            return f"🟢 적정 ({v:.1f})"
        elif v <= 40.0:
            return f"🟡 고평가 ({v:.1f})"
        else:
            return f"🔴 초고평가 ({v:.1f})"
    except:
        return "⚪ 정보없음"

def format_pbr_value(val):
    if pd.isna(val) or val is None:
        if st.session_state.get("market_type") == "한국":
            return "-"
        else:
            return "⚪ 정보없음"
        
    try:
        v = float(val)
        if v < 0.0:
            return f"❌ 자본잠식 ({v:.2f})"
        elif v <= 1.0:
            return f"🔵 절대저평가 ({v:.2f})"
        elif v <= 1.5:
            return f"🟢 적정 ({v:.2f})"
        elif v <= 3.0:
            return f"🟡 고평가 ({v:.2f})"
        else:
            return f"🔴 초고평가 ({v:.2f})"
    except:
        return "⚪ 정보없음"

def format_peak_value(val):
    if pd.isna(val) or val is None:
        return "비활성"
    
    try:
        v = float(val)
        if st.session_state.get("market_type") == "미국":
            return f"${v:.2f}"
        else:
            return f"{int(v):,}원"
    except:
        return "비활성"

def format_peak_diff_value(val):
    if pd.isna(val) or val is None:
        return "비활성"
        
    try:
        v = float(val)
        if v > 0.0:
            return f"🔴 +{v:.2f}%"
        elif v < 0.0:
            return f"🔵 {v:.2f}%"
        else:
            return "⚫ 0.00%"
    except:
        return "비활성"

# -----------------------------------------------------------------------------
# [세션 상태 관리 초기화 부]
# -----------------------------------------------------------------------------
if "data_list" not in st.session_state:
    st.session_state.data_list = []

if "screening_active" not in st.session_state:
    st.session_state.screening_active = False

if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

if "progress_val" not in st.session_state:
    st.session_state.progress_val = 0

if "progress_text" not in st.session_state:
    st.session_state.progress_text = "대기 중"

if "market_type" not in st.session_state:
    st.session_state.market_type = "한국"

if "opt_fundamental" not in st.session_state:
    st.session_state.opt_fundamental = True

if "opt_peak" not in st.session_state:
    st.session_state.opt_peak = True

if "us_cache" not in st.session_state:
    st.session_state.us_cache = load_us_market_cap_cache()

if "app_queue" not in st.session_state:
    st.session_state.app_queue = queue.Queue()

# -----------------------------------------------------------------------------
# [스레드 제어 및 콜백 백엔드 함수 함수]
# -----------------------------------------------------------------------------
def check_stop_status():
    return st.session_state.stop_requested

def execute_start_screening(market, top_n, opt_fundamental, opt_peak):
    st.session_state.data_list = []
    st.session_state.screening_active = True
    st.session_state.stop_requested = False
    st.session_state.progress_val = 0
    st.session_state.progress_text = "스크리닝 작업을 시작합니다..."
    st.session_state.market_type = market
    st.session_state.opt_fundamental = opt_fundamental
    st.session_state.opt_peak = opt_peak
    
    while not st.session_state.app_queue.empty():
        try:
            st.session_state.app_queue.get_nowait()
        except queue.Empty:
            break
            
    worker_thread = threading.Thread(
        target=screening_worker,
        args=(
            market,
            top_n,
            st.session_state.app_queue,
            check_stop_status,
            opt_fundamental,
            opt_peak,
            st.session_state.us_cache
        ),
        daemon=True
    )
    worker_thread.start()

def execute_stop_screening():
    st.session_state.stop_requested = True
    st.session_state.progress_text = "사용자 중지 요청 처리 중..."

# -----------------------------------------------------------------------------
# [사이드바 웹 컨트롤 인터페이스 레이아웃]
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ 스크리닝 컨트롤 타워")
st.sidebar.markdown("---")

selected_market = st.sidebar.selectbox(
    "📍 대상 시장 선택",
    ["한국", "미국"],
    index=0 if st.session_state.market_type == "한국" else 1
)

selected_top_n = st.sidebar.slider(
    "📊 분석 대상 종목 수 (시총 상위 순)",
    min_value=10,
    max_value=500,
    value=50,
    step=10
)

st.sidebar.markdown("🔬 **추가 옵션 데이터 활성화**")
chk_fundamental = st.sidebar.checkbox("밸류에이션 지표 분석 (PER/PBR)", value=st.session_state.opt_fundamental)
chk_peak = st.sidebar.checkbox("최고점 대비 하락률 분석", value=st.session_state.opt_peak)

st.sidebar.markdown("---")

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    btn_start = st.button(
        "🚀 스크리닝 시작",
        use_container_width=True,
        disabled=st.session_state.screening_active
    )
with col_btn2:
    btn_stop = st.button(
        "🛑 작업 중지",
        use_container_width=True,
        disabled=not st.session_state.screening_active
    )

if btn_start:
    execute_start_screening(selected_market, selected_top_n, chk_fundamental, chk_peak)
    st.rerun()

if btn_stop:
    execute_stop_screening()
    st.rerun()

# -----------------------------------------------------------------------------
# [메인 화면 UI 대시보드 구조 레이아웃]
# -----------------------------------------------------------------------------
st.title("📈 대형주 실시간 퀀트 모니터링 시스템")
st.markdown("시가총액 상위 주식의 200일 이동평균선 이격도 및 RSI 상태 분석 대시보드")

# 상단 상태 대시보드 지표 컨테이너
metric_col1, metric_col2, metric_col3 = st.columns(3)
with metric_col1:
    st.metric("선택된 시장", st.session_state.market_type)
with metric_col2:
    st.metric("실시간 수집된 종목 수", f"{len(st.session_state.data_list)}개")
with metric_col3:
    st.metric("엔진 작동 상태", "RUNNING" if st.session_state.screening_active else "IDLE")

# 프로그레스바 지시 영역 컨테이너
progress_bar_placeholder = st.empty()
status_text_placeholder = st.empty()

if st.session_state.screening_active:
    progress_bar_placeholder.progress(st.session_state.progress_val)
    status_text_placeholder.info(f"⏳ {st.session_state.progress_text}")
else:
    if "완료" in st.session_state.progress_text:
        status_text_placeholder.success(f"✅ {st.session_state.progress_text}")
    elif "중지" in st.session_state.progress_text or "중단" in st.session_state.progress_text:
        status_text_placeholder.warning(f"⚠️ {st.session_state.progress_text}")
    else:
        status_text_placeholder.normal(f"💡 {st.session_state.progress_text}")

st.markdown("---")
st.subheader("📊 스크리닝 실시간 종합 분석 테이블 결과")

# -----------------------------------------------------------------------------
# [실시간 백엔드 큐 데이터 폴링 루프 프로세스]
# -----------------------------------------------------------------------------
if st.session_state.screening_active:
    time.sleep(0.1)
    queue_processed = False
    
    while not st.session_state.app_queue.empty():
        try:
            msg = st.session_state.app_queue.get_nowait()
            queue_processed = True
            
            if msg["type"] == "progress":
                st.session_state.progress_val = msg["value"]
                st.session_state.progress_text = msg["text"]
            elif msg["type"] == "data":
                st.session_state.data_list.append(msg["data"])
            elif msg["type"] == "done":
                st.session_state.screening_active = False
                st.session_state.progress_val = 100
                st.session_state.progress_text = msg["text"]
            elif msg["type"] == "stopped":
                st.session_state.screening_active = False
                st.session_state.progress_text = f"사용자 요청으로 스크리닝이 중단되었습니다. (분석 완료: {msg['count']}개)"
            elif msg["type"] == "error":
                st.session_state.screening_active = False
                st.session_state.progress_text = msg["text"]
        except queue.Empty:
            break
            
    if queue_processed:
        st.rerun()

# -----------------------------------------------------------------------------
# [메인 데이터프레임 구조화 및 정렬/하이라이트 처리]
# -----------------------------------------------------------------------------
if len(st.session_state.data_list) > 0:
    df_raw = pd.DataFrame(st.session_state.data_list)
    
    # 순수 숫자 매핑 가상 변환 테이블 구성
    df_renamed = df_raw.rename(
        columns={
            "rank": "순위",
            "symbol": "티커",
            "name": "종목명",
            "data_date": "기준일자",
            "market_cap": "시가총액(억)",
            "price": "현재가",
            "ma200": "200일선",
            "diff": "이격도(%)",
            "rsi": "RSI(14)",
            "per_num": "PER 등급",
            "pbr_num": "PBR 등급",
            "peak_num": "최고점",
            "peak_diff_num": "최고점대비"
        }
    )
    
    # 출력 컬럼 선택 기준 처리
    display_columns = [
        "순위", "티커", "종목명", "기준일자", "시가총액(억)", 
        "현재가", "200일선", "이격도(%)", "RSI(14)"
    ]
    
    if st.session_state.opt_fundamental:
        display_columns.append("PER 등급")
        display_columns.append("PBR 등급")
        
    if st.session_state.opt_peak:
        display_columns.append("최고점")
        display_columns.append("최고점대비")
        
    df_final = df_renamed[display_columns]
    
    # 포맷 지정 딕셔너리 연동 매핑
    styler_format_map = {
        "시가총액(억)": "{:,}",
        "현재가": lambda v: f"${v:.2f}" if st.session_state.market_type == "미국" else f"{int(v):,}원",
        "200일선": lambda v: f"${v:.2f}" if st.session_state.market_type == "미국" else f"{int(v):,}원",
        "이격도(%)": "{:+.2f}%",
        "RSI(14)": "{:.1f}",
        "PER 등급": format_per_value,
        "PBR 등급": format_pbr_value,
        "최고점": format_peak_value,
        "최고점대비": format_peak_diff_value
    }
    
    # -------------------------------------------------------------------------
    # [정렬 완벽 해결 핵심 포인트] Pandas Styler 객체를 전달하면,
    # 웹 화면에는 이모지 텍스트 문자열이 예쁘게 포맷팅되어 나타나지만
    # 사용자가 컬럼 클릭 시 내장 정렬은 "원래의 숫자 데이터 크기 고유 타입"을 기준으로
    # 완벽하게 오름차순/내림차순 정렬이 보장됩니다.
    # -------------------------------------------------------------------------
    styled_df = df_final.style.format(styler_format_map)
    
    # 데이터프레임 컴포넌트 렌더링
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        selection_mode="row"  # 클릭 시 가로 왼쪽 끝부터 오른쪽 끝까지 가로 한 행 전체가 블록 하이라이트 됩니다.
    )
else:
    st.info("스크리닝 시작 버튼을 누르면 실시간으로 데이터가 수집되어 여기에 표시됩니다.")