import streamlit as st
import pandas as pd
import queue
import threading
import time
import os
import re
from datetime import datetime
import yfinance as yf

from config import APP_TITLE, COL_INFOS, CACHE_DIR
import analyzer

# ==============================================================================
# 1. 웹페이지 기본 설정 및 스타일 정의
# ==============================================================================
st.set_page_config(page_title=APP_TITLE, layout="wide")

def get_csv_filename(market_var):
    today = datetime.now().strftime('%Y%m%d')
    market = "US" if market_var == "미국" else "KR"
    return os.path.join(CACHE_DIR, f"screener_backup_{market}_{today}.csv")

# ==============================================================================
# 2. 원본의 항목별 세부 글자색상 디테일 구현 (Pandas Styler용)
# ==============================================================================
def style_formatted_dataframe(df):
    # 빈 스타일 데이터프레임 생성 (기본 글자색 #212121 지정 및 텍스트 줄바꿈 방지 적용)
    style_df = pd.DataFrame('color: #212121; white-space: nowrap;', index=df.index, columns=df.columns)
    
    for idx, row in df.iterrows():
        # [요청사항 2] 순위 항목 아래의 숫자들은 가운데 정렬 처리
        if 'rank' in df.columns:
            style_df.at[idx, 'rank'] = 'text-align: center; color: #212121; white-space: nowrap;'
            
        # [디테일 1] 기준일(data_date) 색상 적용 (#2E7D32)
        if 'data_date' in df.columns:
            style_df.at[idx, 'data_date'] = 'color: #2E7D32; white-space: nowrap;'
            
        # [요청사항 5] 괴리율(diff) 값에 따른 색상 분기 (+는 빨강, -는 파랑)
        diff_str = str(row.get('diff', ''))
        if '+' in diff_str:
            style_df.at[idx, 'diff'] = 'color: #D32F2F; font-weight: bold; white-space: nowrap;'  # 빨간색 (양수)
        elif '-' in diff_str:
            style_df.at[idx, 'diff'] = 'color: #1976D2; font-weight: bold; white-space: nowrap;'  # 파란색 (음수)
        else:
            style_df.at[idx, 'diff'] = 'color: #212121; white-space: nowrap;'
            
        # [디테일 3] RSI 과열/공포 조건별 색상 분기
        rsi_str = str(row.get('rsi', ''))
        if "(과열)" in rsi_str:
            style_df.at[idx, 'rsi'] = 'color: #D32F2F; font-weight: bold; white-space: nowrap;'
        elif "(과매도)" in rsi_str:
            style_df.at[idx, 'rsi'] = 'color: #1976D2; font-weight: bold; white-space: nowrap;'
        elif "(보통)" in rsi_str:
            style_df.at[idx, 'rsi'] = 'color: #E65100; font-weight: bold; white-space: nowrap;'
        else:
            style_df.at[idx, 'rsi'] = 'color: #555555; white-space: nowrap;'
            
        # [디테일 4] PER 등급별 5단계 정밀 색상 분기
        per_text = str(row.get('per', ''))
        if "적자" in per_text or "자본잠식" in per_text:
            style_df.at[idx, 'per'] = 'color: #B71C1C; font-weight: bold; white-space: nowrap;'
        elif "초저평가" in per_text or "절대저평가" in per_text:
            style_df.at[idx, 'per'] = 'color: #1976D2; font-weight: bold; white-space: nowrap;'
        elif "적정" in per_text:
            style_df.at[idx, 'per'] = 'color: #388E3C; font-weight: bold; white-space: nowrap;'
        elif "초고평가" in per_text:
            style_df.at[idx, 'per'] = 'color: #D32F2F; font-weight: bold; white-space: nowrap;'
        elif "고평가" in per_text:
            style_df.at[idx, 'per'] = 'color: #F57C00; font-weight: bold; white-space: nowrap;'
        else:
            style_df.at[idx, 'per'] = 'color: #757575; white-space: nowrap;'
            
        # [디테일 5] PBR 등급별 5단계 정밀 색상 분기
        pbr_text = str(row.get('pbr', ''))
        if "적자" in pbr_text or "자본잠식" in pbr_text:
            style_df.at[idx, 'pbr'] = 'color: #B71C1C; font-weight: bold; white-space: nowrap;'
        elif "초저평가" in pbr_text or "절대저평가" in pbr_text:
            style_df.at[idx, 'pbr'] = 'color: #1976D2; font-weight: bold; white-space: nowrap;'
        elif "적정" in pbr_text:
            style_df.at[idx, 'pbr'] = 'color: #388E3C; font-weight: bold; white-space: nowrap;'
        elif "초고평가" in pbr_text:
            style_df.at[idx, 'pbr'] = 'color: #D32F2F; font-weight: bold; white-space: nowrap;'
        elif "고평가" in pbr_text:
            style_df.at[idx, 'pbr'] = 'color: #F57C00; font-weight: bold; white-space: nowrap;'
        else:
            style_df.at[idx, 'pbr'] = 'color: #757575; white-space: nowrap;'
            
        # [요청사항 5] 최고점 대비 하락률(peak_diff) 값에 따른 색상 분기 (+는 빨강, -는 파랑)
        peak_diff_str = str(row.get('peak_diff', ''))
        if "🔴" in peak_diff_str or "+" in peak_diff_str:
            style_df.at[idx, 'peak_diff'] = 'color: #D32F2F; font-weight: bold; white-space: nowrap;'
        elif "🔵" in peak_diff_str or "-" in peak_diff_str:
            style_df.at[idx, 'peak_diff'] = 'color: #1976D2; font-weight: bold; white-space: nowrap;'
        else:
            style_df.at[idx, 'peak_diff'] = 'color: #212121; white-space: nowrap;'
            
    return style_df

# ==============================================================================
# 3. 원본의 데이터 텍스트 포맷팅 규칙 파싱 함수
# ==============================================================================
def format_raw_records(records, market_var):
    formatted_list = []
    is_us = (market_var == "미국")
    
    for data in records:
        mcap_str = f"{data.get('market_cap', 0):,}억" if data.get('market_cap', 0) > 0 else "N/A"
        
        # [요청사항 4] 현재가 수치 포맷팅에 3자리 단위 콤마(,) 추가 반영
        try:
            price_val = float(data.get('price', 0))
            price_str = f"${price_val:,.2f}" if is_us else f"{int(price_val):,}원"
        except:
            price_str = str(data.get('price', ''))
            
        # [요청사항 4] 최고점 수치 포맷팅에 3자리 단위 콤마(,) 추가 반영
        try:
            peak_val = float(data.get('peak', 0))
            peak_str = f"${peak_val:,.2f}" if is_us else f"{int(peak_val):,}원"
        except:
            peak_str = str(data.get('peak', ''))
            
        # [요청사항 4] 200일선 수치 포맷팅에 3자리 단위 콤마(,) 추가 반영
        try:
            ma_val = float(data.get('ma200', 0))
            ma_str = f"${ma_val:,.2f}" if is_us else f"{int(ma_val):,}원"
        except:
            ma_str = str(data.get('ma200', ''))
            
        try:
            diff_val = float(data.get('diff', 0))
            if diff_val > 0:
                diff_str = f"+{diff_val:.2f}%"
            elif diff_val < 0:
                diff_str = f"{diff_val:.2f}%"
            else:
                diff_str = "0.00%"
        except:
            diff_str = str(data.get('diff', ''))
            
        try:
            rsi_val = float(data.get("rsi", 50.0))
            if rsi_val >= 70:
                rsi_str = f"{rsi_val:.1f} (과열)"
            elif rsi_val <= 30:
                rsi_str = f"{rsi_val:.1f} (과매도)"
            elif rsi_val >= 50:
                rsi_str = f"{rsi_val:.1f} (보통)"
            else:
                rsi_str = f"{rsi_val:.1f} (침체)"
        except:
            rsi_str = str(data.get('rsi', ''))
            
        formatted_list.append({
            "rank": data.get("rank", ""),
            "symbol": data.get("symbol", ""),
            "name": data.get("name", ""),
            "data_date": data.get("data_date", "-"),
            "market_cap": mcap_str,
            "price": price_str,
            "peak": peak_str,
            "peak_diff": data.get("peak_diff", "비활성"),
            "ma200": ma_str,
            "diff": diff_str,
            "rsi": rsi_str,
            "per": data.get("per", "비활성"),
            "pbr": data.get("pbr", "비활성")
        })
        
    return formatted_list

# ==============================================================================
# 4. 세션 상태 관리 선언
# ==============================================================================
if "current_session_data" not in st.session_state:
    st.session_state.current_session_data = []
if "status_text" not in st.session_state:
    st.session_state.status_text = "대기 중..."
if "progress_val" not in st.session_state:
    st.session_state.progress_val = 0

# ==============================================================================
# 5. 웹 대시보드 레이아웃 UI 설계
# ==============================================================================
st.title(f"🚀 {APP_TITLE}")
st.markdown("브라우저 웹에서 양방향으로 주식 데이터를 분석하고 저평가를 찾고 있습니다.")

# 사이드바 컨트롤 컴포넌트 구성
st.sidebar.header("🔍 검색 설정")
market = st.sidebar.selectbox("시장 선택", ["한국", "미국"], index=1)
top_n = st.sidebar.slider("분석할 수 있다(상위)", min_value=1, max_value=100, value=50)

opt_fundamental = st.sidebar.checkbox("기본적 분석을 포함한다(PER/PBR)", value=True)
opt_peak = st.sidebar.checkbox("고정 비교율을 포함한다", value=True)

# 레이아웃 정렬용 컬럼 배치
col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    start_button = st.button("⚡ 스크리닝 시작")
with col_btn2:
    load_button = st.button("📂 불러오기")

# ------------------------------------------------------------------------------
# 기능 로직 A: 로컬 CSV 파일 백업 불러오기 (fast_load_from_csv)
# ------------------------------------------------------------------------------
if load_button:
    filename = get_csv_filename(market)
    if not os.path.exists(filename):
        st.sidebar.warning("오늘 저장된 스크리닝 결과가 없습니다.\n[스크리닝 시작]을 먼저 진행해 주세요.")
    else:
        try:
            df_loaded = pd.read_csv(filename, encoding='utf-8-sig')
            st.session_state.current_session_data = df_loaded.to_dict('records')
            st.session_state.status_text = f"✅ 저장된 결과를 1초 만에 불러왔습니다! ({len(df_loaded)} 종목)"
            st.session_state.progress_val = 100
        except Exception as e:
            st.sidebar.error(f"파일을 불러오는 중 오류가 발생했습니다: {e}")

# ------------------------------------------------------------------------------
# 기능 로직 B: 엔진 연동 실시간 스크리닝 시작 (start_screening)
# ------------------------------------------------------------------------------
if start_button:
    st.session_state.current_session_data = []
    st.session_state.progress_val = 0
    st.session_state.status_text = "준비 중..."
    
    q = queue.Queue()
    stop_requested = False
    us_market_cap_data = analyzer.load_us_market_cap_cache()
    
    # analyzer 스크리닝 백엔드 스레드 생성
    t = threading.Thread(
        target=analyzer.screening_worker,
        args=(market, top_n, q, lambda: stop_requested, opt_fundamental, opt_peak, us_market_cap_data),
        daemon=True
    )
    t.start()
    
    # 동적 렌더링을 위한 윈도우 프리셋 컴포넌트 선언
    progress_bar = st.progress(0)
    status_label = st.empty()
    table_placeholder = st.empty()
    
    while t.is_alive() or not q.empty():
        try:
            while True:
                msg = q.get_nowait()
                m_type = msg.get("type")
                
                if m_type == "progress":
                    st.session_state.progress_val = msg["value"]
                    st.session_state.status_text = msg["text"]
                elif m_type == "data":
                    st.session_state.current_session_data.append(msg["data"])
                elif m_type == "done" or m_type == "stopped":
                    st.session_state.status_text = f"완료! 총 {msg.get('count', 0)}개 종목 분석 완료"
                    st.session_state.progress_val = 100
                elif m_type == "error":
                    st.session_state.status_text = f"오류 발생: {msg.get('text')}"
                    st.session_state.progress_val = 100
        except queue.Empty:
            pass
            
        progress_bar.progress(st.session_state.progress_val)
        status_label.info(st.session_state.status_text)
        
        if st.session_state.current_session_data:
            formatted_list = format_raw_records(st.session_state.current_session_data, market)
            df_current = pd.DataFrame(formatted_list)
            
            # config에 정의된 순서대로 정렬 및 출력
            col_ids = [c["id"] for c in COL_INFOS if c["id"] in df_current.columns]
            df_current = df_current[col_ids]
            
            # 실시간 스타일링 테이핑 로드
            styled_df = df_current.style.apply(style_formatted_dataframe, axis=None)
            
            # [요청사항 1, 3] hide_index=True로 좌측 빈 인덱스 열 제거, use_container_width=False로 타이트하게 정렬
            table_placeholder.dataframe(styled_df, use_container_width=False, height=500, hide_index=True)
            
        time.sleep(0.1)
        
    # 완료 시 자동 로컬 CSV 백업 기능 작동
    if st.session_state.current_session_data:
        try:
            df_save = pd.DataFrame(st.session_state.current_session_data)
            df_save.to_csv(get_csv_filename(market), index=False, encoding='utf-8-sig')
        except:
            pass

# ==============================================================================
# 6. 최종 뷰어 화면 렌더링 단락
# ==============================================================================
if st.session_state.current_session_data and not start_button:
    st.info(st.session_state.status_text)
    
    formatted_list = format_raw_records(st.session_state.current_session_data, market)
    df_display = pd.DataFrame(formatted_list)
    
    col_ids = [c["id"] for c in COL_INFOS if c["id"] in df_display.columns]
    df_display = df_display[col_ids]
    
    styled_df = df_display.style.apply(style_formatted_dataframe, axis=None)
    
    st.subheader("📊 분석 결과")
    
    # [요청사항 1, 3] hide_index=True로 좌측 빈 인덱스 열 제거, use_container_width=False로 타이트하게 정렬
    st.dataframe(styled_df, use_container_width=False, height=500, hide_index=True)
    
    # 엑셀 변환 결과 다운로드 (CSV) 기능 구현
    csv_data = df_display.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    st.download_button(
        label="📥 결과 다운로드 (CSV)",
        data=csv_data,
        file_name=f"screener_result_{market}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv"
    )
elif not start_button:
    st.info(st.session_state.status_text)