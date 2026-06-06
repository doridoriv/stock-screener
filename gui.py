import streamlit as st
import pandas as pd
import queue
import threading
import os
import re
import time
from datetime import datetime
import yfinance as yf

from config import APP_TITLE, COL_INFOS, CACHE_DIR
import analyzer

# ==============================================================================
# 1. 세션 상태(Session State) 초기화 (기존 클래스 변수 대체)
# ==============================================================================
if "us_market_cap_data" not in st.session_state:
    st.session_state.us_market_cap_data = analyzer.load_us_market_cap_cache()

if "current_session_data" not in st.session_state:
    st.session_state.current_session_data = []

if "is_running" not in st.session_state:
    st.session_state.is_running = False

if "stop_requested" not in st.session_state:
    st.session_state.stop_requested = False

# ==============================================================================
# 2. 헬퍼 함수 정의 (기존 메소드 구조 유지)
# ==============================================================================
def get_csv_filename(market_val):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if market_val == "미국" else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

# ==============================================================================
# 3. Streamlit 웹 페이지 레이아웃 및 컨트롤러 구성
# ==============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(f"🚀 {APP_TITLE}")

# 상단 설정 바 구성 (기존 frame_top 영역)
col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns([1.5, 2, 1.5, 1.5, 1.5])

with col_m1:
    market_var = st.selectbox("시장 선택", ["미국", "한국"], index=0)

with col_m2:
    top_n_val = st.slider("검색 순위 범위", min_value=1, max_value=100, value=50)

with col_m3:
    btn_run = st.button("🔄 새로 검색", use_container_width=True, type="primary")

with col_m4:
    btn_load = st.button("📂 불러오기", use_container_width=True)

with col_m5:
    btn_stop = st.button("⏹ 중지", use_container_width=True, disabled=not st.session_state.is_running)

# 중지 버튼 클릭 처리
if btn_stop:
    st.session_state.stop_requested = True
    st.warning("사용자가 중지를 요청했습니다. 현재 종목까지만 처리하고 종료합니다...")

# 불러오기 버튼 클릭 처리
if btn_load:
    filename = get_csv_filename(market_var)
    if not os.path.exists(filename):
        st.error("오늘 저장된 스크리닝 결과가 없습니다.\n[새로 검색]을 먼저 진행해 주세요.")
    else:
        try:
            df_loaded = pd.read_csv(filename, encoding='utf-8-sig')
            st.session_state.current_session_data = df_loaded.to_dict('records')
            st.success(f"📂 저장된 결과를 성공적으로 불러왔습니다! ({len(st.session_state.current_session_data)} 종목)")
        except Exception as e:
            st.error(f"파일을 불러오는 중 오류가 발생했습니다:\n{e}")

# ==============================================================================
# 4. 새로 검색(스크리닝) 코어 스레드 로직
# ==============================================================================
if btn_run:
    st.session_state.is_running = True
    st.session_state.stop_requested = False
    st.session_state.current_session_data = []
    
    # 통신용 큐 생성
    q = queue.Queue()
    
    # 백그라운드 스레드 실행
    stop_fn = lambda: st.session_state.stop_requested
    threading.Thread(
        target=analyzer.screening_worker,
        args=(market_var, top_n_val, q, stop_fn, True, True, st.session_state.us_market_cap_data),
        daemon=True
    ).start()
    
    # 화면 표시용 플레이스홀더 생성
    progress_bar = st.progress(0)
    status_label = st.empty()
    
    # 큐 모니터링 루프 (기존 check_queue 루프 기능 구현)
    while True:
        try:
            msg = q.get_nowait()
            m_type = msg.get("type")
            
            if m_type == "progress":
                p_val = msg["value"]
                progress_bar.progress(int(p_val) / 100 if p_val <= 100 else 1.0)
                status_label.text(msg["text"])
                
            elif m_type == "data":
                st.session_state.current_session_data.append(msg["data"])
                
            elif m_type in ["done", "stopped"]:
                if st.session_state.current_session_data and not st.session_state.stop_requested:
                    try:
                        df_backup = pd.DataFrame(st.session_state.current_session_data)
                        df_backup.to_csv(get_csv_filename(market_var), index=False, encoding='utf-8-sig')
                    except:
                        pass
                
                st.session_state.is_running = False
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                if m_type == "stopped":
                    st.warning(f"중지됨: 총 {msg['count']}개 종목까지만 분석되었습니다.")
                else:
                    st.success(f"완료! (기준일: {today_str}) 총 {msg['count']}개 종목 분석 완료 (자동 백업됨)")
                break
                
            elif m_type == "error":
                st.session_state.is_running = False
                st.error(msg["text"])
                break
                
        except queue.Empty:
            time.sleep(0.1)
            
    st.session_state.is_running = False
    st.rerun()

# ==============================================================================
# 5. 데이터프레임 빌드 및 표 스타일링 (요청사항 1, 2, 3, 4, 5 집중 처리 영역)
# ==============================================================================
if st.session_state.current_session_data:
    raw_records = st.session_state.current_session_data
    is_us = (market_var == "미국")
    
    # 표에 바인딩할 정제된 데이터 리스트 생성 (기존 render_row의 포맷팅 로직 이관)
    formatted_rows = []
    
    for data in raw_records:
        # [요청사항 4] 금액 데이터 3자리 콤마 처리 구현
        mcap_str = f"{data['market_cap']:,}억" if data.get('market_cap', 0) > 0 else "N/A"
        
        if is_us:
            price_str = f"${data['price']:,.2f}"
            ma_str = f"${data['ma200']:,.2f}"
        else:
            price_str = f"{int(data['price']):,}원"
            ma_str = f"{int(data['ma200']):,}원"
            
        peak_val = data.get("peak", "비활성")
        if isinstance(peak_val, (int, float)):
            if is_us:
                peak_str = f"${peak_val:,.2f}"
            else:
                peak_str = f"{int(peak_val):,}원"
        else:
            peak_str = str(peak_val)
            
        # 변동률 및 괴리율 수치 문자열 생성
        diff_val = float(data['diff']) if not pd.isna(data['diff']) else 0.0
        if diff_val > 0:
            diff_str = f"+{diff_val:.2f}%"
        elif diff_val < 0:
            diff_str = f"{diff_val:.2f}%"
        else:
            diff_str = "0.00%"
            
        rsi_val = float(data.get("rsi", 50.0))
        if rsi_val >= 70:
            rsi_str = f"{rsi_val:.1f} (과열)"
        elif rsi_val <= 30:
            rsi_str = f"{rsi_val:.1f} (과매도)"
        elif rsi_val >= 50:
            rsi_str = f"{rsi_val:.1f} (보통)"
        else:
            rsi_str = f"{rsi_val:.1f} (침체)"
            
        per_str = str(data.get("per", "비활성"))
        pbr_str = str(data.get("pbr", "비활성"))
        peak_diff_str = str(data.get("peak_diff", "비활성"))
        
        # 13개 항목 매핑 구조 유지
        row_data = [
            str(data.get("rank", "")),
            str(data.get("symbol", "")),
            str(data.get("name", "")),
            str(data.get("data_date", "-")),
            mcap_str,
            price_str,
            peak_str,
            peak_diff_str,
            ma_str,
            diff_str,
            rsi_str,
            per_str,
            pbr_str
        ]
        formatted_rows.append(row_data)
        
    # 데이터프레임 변환 (컬럼 헤더 설정)
    col_headers = [col["text"] for col in COL_INFOS]
    display_df = pd.DataFrame(formatted_rows, columns=col_headers)
    
    # 대상 컬럼 정의 (최고점대비 컬럼명과 200일괴리율 컬럼명 동적 추출)
    peak_diff_col = COL_INFOS[7]["text"]
    diff_col = COL_INFOS[9]["text"]
    
    # Pandas Styler 객체 생성
    styler = display_df.style
    
    # [요청사항 2, 3] 모든 항목 데이터 가운데 정렬 및 자동 줄바꿈(Wrap) 방지 설정
    styler = styler.set_properties(**{
        'text-align': 'center',
        'white-space': 'nowrap'
    })
    
    # [요청사항 5] 최고점대비 및 200일괴리율 수치 컬러링 함수 정의
    def apply_conditional_color(val):
        if isinstance(val, str):
            if "🔴" in val or "+" in val:
                return "color: #D32F2F; font-weight: bold;" # 조건 충족 시 빨간색
            elif "🔵" in val or "-" in val:
                return "color: #1976D2; font-weight: bold;" # 조건 충족 시 파란색
        return "color: #212121;"
        
    # 하위 호환성을 고려한 스타일 맵 바인딩 기법 적용
    if hasattr(styler, 'map'):
        styler = styler.map(apply_conditional_color, subset=[peak_diff_col, diff_col])
    else:
        styler = styler.applymap(apply_conditional_color, subset=[peak_diff_col, diff_col])
        
    # [요청사항 1, 3] 웹 데이터프레임 최종 출력부 기동
    st.dataframe(
        styler,
        hide_index=True,          # [요청사항 1] 좌측의 이름 없는 빈 인덱스 행 강제 완전 삭제
        use_container_width=False, # [요청사항 3] 무조건 가로로 늘어나지 않고 텍스트 폭에 최적화하여 공간 낭비 방지
        height=650
    )