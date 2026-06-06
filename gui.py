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
# 1. 전역 세션 상태(Session State) 관리부
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
# 2. 기존 코어 비즈니스 메소드 이관 정의
# ==============================================================================
def get_csv_filename(market_val):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if market_val == "미국" else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

# ==============================================================================
# 3. Streamlit 웹 인터페이스 및 컨트롤 레이아웃 구성
# ==============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(f"🚀 {APP_TITLE}")

# 상단 대시보드 컨트롤 패널 구성
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

# 중지 버튼 트리거 프로세스
if btn_stop:
    st.session_state.stop_requested = True
    st.warning("사용자가 중지를 요청했습니다. 현재 종목까지만 처리하고 종료합니다...")

# 불러오기 버튼 백업 복원 프로세스
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
# 4. 실시간 스크리닝 백그라운드 스레드 및 큐 모니터링 엔진
# ==============================================================================
if btn_run:
    st.session_state.is_running = True
    st.session_state.stop_requested = False
    st.session_state.current_session_data = []
    
    q = queue.Queue()
    stop_fn = lambda: st.session_state.stop_requested
    
    threading.Thread(
        target=analyzer.screening_worker,
        args=(market_var, top_n_val, q, stop_fn, True, True, st.session_state.us_market_cap_data),
        daemon=True
    ).start()
    
    progress_bar = st.progress(0)
    status_label = st.empty()
    table_placeholder = st.empty()
    
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
            time.sleep(0.05)
            
    st.session_state.is_running = False
    st.rerun()

# ==============================================================================
# 5. 데이터 가공 및 테이블 인젝션
# ==============================================================================
if st.session_state.current_session_data:
    raw_records = st.session_state.current_session_data
    is_us = (market_var == "미국")
    
    formatted_rows = []
    
    for data in raw_records:
        # 데이터 정렬을 위해 수치형 항목을 파싱하여 순수 float/int 형태로 데이터프레임 내 주입
        rank_val = int(data.get("rank", 0)) if str(data.get("rank", "")).isdigit() else data.get("rank", 0)
        mcap_val = float(data.get('market_cap', 0)) if data.get('market_cap', 0) is not None else 0.0
        price_val = float(data.get('price', 0)) if data.get('price', 0) is not None else 0.0
        ma_val = float(data.get('ma200', 0)) if data.get('ma200', 0) is not None else 0.0
        
        # 최고점 수치 가공
        raw_peak = data.get("peak", 0)
        if isinstance(raw_peak, str):
            cleaned_peak = re.sub(r'[^\d.]', '', raw_peak)
            peak_val = float(cleaned_peak) if cleaned_peak else 0.0
        else:
            peak_val = float(raw_peak) if raw_peak is not None else 0.0
            
        # 200일 괴리율 수치화
        diff_val = float(data.get('diff', 0.0)) if not pd.isna(data.get('diff')) else 0.0
        
        # 최고점대비 수치 가공 (방해되는 동그라미 기호 등 삭제 및 숫자 우선 추출)
        raw_peak_diff = data.get("peak_diff", 0.0)
        if isinstance(raw_peak_diff, str):
            cleaned_peak_diff = re.sub(r'[^\d.-]', '', raw_peak_diff)
            peak_diff_val = float(cleaned_peak_diff) if cleaned_peak_diff else 0.0
        else:
            peak_diff_val = float(raw_peak_diff) if raw_peak_diff is not None else 0.0
            
        # RSI 수치화 및 텍스트 분할 기법 적용
        rsi_val = float(data.get("rsi", 50.0))
        if rsi_val >= 70:
            rsi_str = f"{rsi_val:.1f} (과열)"
        elif rsi_val <= 30:
            rsi_str = f"{rsi_val:.1f} (과매도)"
        elif rsi_val >= 50:
            rsi_str = f"{rsi_val:.1f} (보통)"
        else:
            rsi_str = f"{rsi_val:.1f} (침체)"
            
        # PER / PBR 등급 항목 정렬 방해 요소인 동그라미 기호 제거 및 숫자가 제일 먼저 오도록 재정렬
        raw_per = str(data.get("per", "정보없음"))
        raw_pbr = str(data.get("pbr", "정보없음"))
        
        cleaned_per = re.sub(r'[^\d.-]', '', raw_per)
        cleaned_pbr = re.sub(r'[^\d.-]', '', raw_pbr)
        
        per_num = float(cleaned_per) if cleaned_per else None
        pbr_num = float(cleaned_pbr) if cleaned_pbr else None
        
        # 정렬에 영향이 없도록 문자열의 시작 부분을 숫자로만 구성하여 바인딩
        if per_num is not None:
            if "적자" in raw_per:
                per_str = f"{per_num:.1f} (적자)"
            elif "초저평가" in raw_per:
                per_str = f"{per_num:.1f} (초저평가)"
            elif "적정" in raw_per:
                per_str = f"{per_num:.1f} (적정)"
            elif "고평가" in raw_per:
                per_str = f"{per_num:.1f} (고평가)"
            elif "초고평가" in raw_per:
                per_str = f"{per_num:.1f} (초고평가)"
            else:
                per_str = f"{per_num:.1f}"
        else:
            per_str = "정보없음"
            
        if pbr_num is not None:
            if "적자" in raw_pbr:
                pbr_str = f"{pbr_num:.1f} (적자)"
            elif "저평가" in raw_pbr:
                pbr_str = f"{pbr_num:.1f} (저평가)"
            elif "적정" in raw_pbr:
                pbr_str = f"{pbr_num:.1f} (적정)"
            elif "고평가" in raw_pbr:
                pbr_str = f"{pbr_num:.1f} (고평가)"
            else:
                pbr_str = f"{pbr_num:.1f}"
        else:
            pbr_str = "정보없음"
        
        row_data = [
            rank_val,
            str(data.get("symbol", "")),
            str(data.get("name", "")),
            str(data.get("data_date", "-")),
            mcap_val,
            price_val,
            peak_val,
            peak_diff_val,
            ma_val,
            diff_val,
            rsi_str,
            per_str,
            pbr_str
        ]
        formatted_rows.append(row_data)
        
    # 출력형 데이터프레임 구조 빌드
    col_headers = [col["text"] for col in COL_INFOS]
    display_df = pd.DataFrame(formatted_rows, columns=col_headers)
    
    # 뼈대 텍스트 명칭 동적 지정 추출
    peak_diff_column_name = COL_INFOS[7]["text"]
    diff_column_name = COL_INFOS[9]["text"]
    
    # Pandas 데이터 프레임 고급 스타일러 선언 및 포맷터를 활용한 표기 처리 (정렬 인프라 유지 보장)
    styler = display_df.style
    
    # 포맷 지정 딕셔너리 동적 빌드 (데이터는 숫자 고유의 형태로 유지하고 표기만 3자리 콤마 처리 기법)
    fmt_dict = {}
    if is_us:
        fmt_dict[COL_INFOS[4]["text"]] = "{:,.0f}억"
        fmt_dict[COL_INFOS[5]["text"]] = "${:,.2f}"
        fmt_dict[COL_INFOS[6]["text"]] = "${:,.2f}"
        fmt_dict[COL_INFOS[7]["text"]] = "{:+.2f}%"
        fmt_dict[COL_INFOS[8]["text"]] = "${:,.2f}"
        fmt_dict[COL_INFOS[9]["text"]] = "{:+.2f}%"
    else:
        fmt_dict[COL_INFOS[4]["text"]] = "{:,.0f}억"
        fmt_dict[COL_INFOS[5]["text"]] = "{:,.0f}원"
        fmt_dict[COL_INFOS[6]["text"]] = "{:,.0f}원"
        fmt_dict[COL_INFOS[7]["text"]] = "{:+.2f}%"
        fmt_dict[COL_INFOS[8]["text"]] = "{:,.0f}원"
        fmt_dict[COL_INFOS[9]["text"]] = "{:+.2f}%"
        
    styler = styler.format(fmt_dict, na_rep="N/A")
    
    # 전체 수치 항목의 가운데 정렬 및 개행(Wrap) 자동 금지 제어 설계
    styler = styler.set_properties(**{
        'text-align': 'center',
        'white-space': 'nowrap'
    })
    
    # 최고점대비 / 200일괴리율 조건부 텍스트 컬러 스위칭 정적 함수
    def apply_strict_color_rules(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return "color: #D32F2F; font-weight: bold;"
            if val < 0:
                return "color: #1976D2; font-weight: bold;"
        elif isinstance(val, str):
            if "+" in val:
                return "color: #D32F2F; font-weight: bold;"
            if "-" in val:
                return "color: #1976D2; font-weight: bold;"
        return "color: #212121;"
        
    styler = styler.map(apply_strict_color_rules, subset=[peak_diff_column_name, diff_column_name])
        
    # 콘솔 경고를 완전히 제압하는 최신 Streamlit 프레임 표출 엔진
    st.dataframe(
        styler,
        width='content',
        height=680,
        hide_index=True
    )