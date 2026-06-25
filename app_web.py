import os
from datetime import datetime
import pandas as pd
import streamlit as st

import analyzer
import diagnostics
import market_analyzer
import supplemental_data
from config import APP_TITLE, FIXED_TOP_N, TABLE_COLUMNS

MARKET_PANEL_CACHE_VERSION = 2
MARKET_LABEL_TO_VALUE = {
    "코스피": "한국(코스피)",
    "코스닥": "한국(코스닥)",
    "미국": "미국",
}
MARKET_VALUE_TO_LABEL = {value: label for label, value in MARKET_LABEL_TO_VALUE.items()}

@st.cache_data(ttl=1800) # 캐시 유지 시간 30분
def get_cached_market_panel(cache_version=MARKET_PANEL_CACHE_VERSION):
    cached_panel = market_analyzer.load_market_panel_cache()
    if cached_panel:
        return cached_panel
    return market_analyzer.build_market_panel()

# ==========================================
# 1. 페이지 및 세션 상태 초기화 (사이드바 자동 제어)
# ==========================================
if "selected_market" not in st.session_state:
    st.session_state.selected_market = "한국(코스피)"

if "market_choice" not in st.session_state:
    st.session_state.market_choice = MARKET_VALUE_TO_LABEL.get(st.session_state.selected_market, "코스피")

if "table_view_mode" not in st.session_state:
    st.session_state.table_view_mode = "핵심만"
    
if "top_n" not in st.session_state:
    st.session_state.top_n = FIXED_TOP_N
else:
    st.session_state.top_n = FIXED_TOP_N

# 사이드바 초기 상태를 세션에 저장 (기본값: 닫힘)
if "sidebar_state" not in st.session_state:
    st.session_state.sidebar_state = "collapsed"

# 시장 교체 시 캐시 데이터를 자동 로드하여 사용자 편의성 제공
def get_market_text(market=None):
    market = market or st.session_state.selected_market
    market_text = "코스피" if market in ["한국(코스피)", "한국"] else "코스닥" if market == "한국(코스닥)" else "미국"
    return market_text


def load_cached_market_data():
    market_text = get_market_text()
    cache_file = analyzer.find_latest_valid_cache(market_text)

    if cache_file and os.path.exists(cache_file):
        try:
            df_cached = pd.read_csv(cache_file)
            if not df_cached.empty:
                df_cached = analyzer.sort_by_market_cap(df_cached).head(FIXED_TOP_N)
                st.session_state.data = df_cached.to_dict(orient='records')
                st.session_state.sidebar_state = "collapsed"
            else:
                st.session_state.data = []
        except:
            st.session_state.data = []
    else:
        st.session_state.data = []


def get_cache_status():
    market_text = get_market_text()
    cache_file = analyzer.find_latest_valid_cache(market_text)
    if not cache_file or not os.path.exists(cache_file):
        return None
    try:
        df = pd.read_csv(cache_file)
    except Exception:
        return None
    if df.empty:
        return None

    data_date = df["data_date"].dropna().iloc[0] if "data_date" in df.columns and df["data_date"].notna().any() else "미지정"
    price_basis = "미지정"
    if "price_basis" in df.columns:
        counts = df["price_basis"].dropna().astype(str).value_counts()
        if not counts.empty:
            price_basis = " / ".join([f"{idx} {val}" for idx, val in counts.items()])
    price_time = df["price_time"].dropna().iloc[0] if "price_time" in df.columns and df["price_time"].notna().any() else "미지정"
    file_time = datetime.fromtimestamp(os.path.getmtime(cache_file)).strftime("%Y-%m-%d %H:%M")
    return {
        "data_date": data_date,
        "price_basis": price_basis,
        "price_time": price_time,
        "file_time": file_time,
        "cache_file": cache_file,
    }


def handle_market_change():
    load_cached_market_data()


def handle_market_choice_change():
    st.session_state.selected_market = MARKET_LABEL_TO_VALUE[st.session_state.market_choice]
    st.session_state.show_large_table = False
    load_cached_market_data()


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
# 4. 좌측 사이드바 컨트롤 패널
# ==========================================
with st.sidebar:
    st.title("📊 장기 투자 스크리너")
    st.caption("2046년 은퇴를 향한 우상향 마라톤")
    st.divider()
    st.info("💡 데이터 수집은 GitHub Actions 스케줄 또는 Run workflow에서만 실행됩니다. 앱에서는 저장된 캐시를 읽고 새로고침합니다.")

# ==========================================
# 5. 메인 대시보드 화면 및 컨트롤 패널
# ==========================================
st.header(f"🎯 {get_market_text()} 시장 분석 대시보드")
st.caption("1단계 시장환경 → 2단계 좋은 회사 후보 → 3단계 안 오르는 이유 진단")

st.subheader("분석 기준")
criteria_col1, criteria_col2, criteria_col3 = st.columns([4, 2, 2], vertical_alignment="bottom")
with criteria_col1:
    st.radio(
        "시장",
        list(MARKET_LABEL_TO_VALUE.keys()),
        key="market_choice",
        horizontal=True,
        on_change=handle_market_choice_change,
    )
with criteria_col2:
    st.metric("탐색 종목 수", f"{FIXED_TOP_N}개 고정")
with criteria_col3:
    if st.button("🔄 캐시 새로고침", width="stretch", type="secondary"):
        get_cached_market_panel.clear()
        load_cached_market_data()
        st.rerun()

# 메인 화면 상단에 시장 분위기 (Market Sentiment) 패널 표시 (요구사항 #4번 구현)
st.subheader("1단계: 시장환경")
try:
    market_data = get_cached_market_panel()
    
    state_color = "🔴 위험회피 (Risk-Off)"
    if market_data["market_state"] == "위험선호":
        state_color = "🟢 위험선호 (Risk-On)"
    elif market_data["market_state"] == "중립":
        state_color = "🟡 중립 (Neutral)"
         
    col_m1, col_m2 = st.columns([1, 4])
    with col_m1:
        st.metric(
            label="시장환경 점수",
            value=f"{market_data['market_score']}점",
            delta=market_data.get("score_state", market_data["market_state"])
        )
    with col_m2:
        source_text = market_data.get("collected_at", "미지정")
        st.info(
            f"**상태:** {state_color}  |  **요약:** {market_data['summary']}  \n"
            "**기준:** 80↑ 매우 우호 | 65↑ 우호 | 50=평균 | 35↓ 부담 | 20↓ 매우 부담  \n"
            f"**시장환경 수집시각:** `{source_text}`"
        )

    def format_market_value(label, value):
        if value is None or pd.isna(value):
            return "-"
        if label == "미국10년물":
            return f"{float(value):.2f}%"
        if label == "달러인덱스":
            return f"{float(value):.1f}"
        if float(value) >= 100:
            return f"{float(value):,.1f}"
        return f"{float(value):.2f}"

    def format_market_pct(value):
        if value is None or pd.isna(value):
            return "-"
        return f"{float(value):+.2f}%"

    def market_meaning(label, score):
        if score is None or pd.isna(score):
            return "판단 보류"
        favorable = float(score) >= 65
        neutral = 50 <= float(score) < 65
        if label == "나스닥":
            return "성장주 위험선호 양호" if favorable else "성장주 방향성 제한" if neutral else "성장주 투자심리 부담"
        if label == "반도체":
            return "반도체 종목에 우호적" if favorable else "반도체 모멘텀 중립" if neutral else "반도체 종목에 부담"
        if label == "S&P500":
            return "미국 대형주 흐름 양호" if favorable else "대형주 흐름 중립" if neutral else "대형주 시장 체력 약함"
        if label == "금융":
            return "금융주 수급 우호" if favorable else "금융주 방향성 중립" if neutral else "금융주 수급 부담"
        if label == "장기채":
            return "금리 부담 완화 신호" if favorable else "금리 부담 중립" if neutral else "금리 상승 부담"
        if label == "달러인덱스":
            return "달러 약세로 수급 부담 완화" if favorable else "달러 영향 중립" if neutral else "달러 강세로 외국인 수급 부담"
        if label == "미국10년물":
            return "고PER 할인 부담 완화" if favorable else "밸류에이션 부담 중립" if neutral else "고PER 종목 할인 요인"
        return "시장환경 참고 지표"

    def evidence_display_row(row):
        label = row.get("label")
        score = row.get("risk_score")
        weight = row.get("weight") or 0
        total_weight = market_data.get("total_weight") or 100
        score_impact = row.get("score_impact")
        if score_impact is None and score is not None:
            score_impact = round((float(score) - 50) * float(weight) / float(total_weight), 1)
        return {
            "항목": label,
            "현재값": row.get("latest_text") or format_market_value(label, row.get("latest")),
            "20일": row.get("ret20_text") or format_market_pct(row.get("ret20")),
            "60일": row.get("ret60_text") or format_market_pct(row.get("ret60")),
            "평가": row.get("effect") or "-",
            "점수영향": f"{score_impact:+.1f}" if score_impact is not None else "-",
            "의미": row.get("meaning") or market_meaning(label, score),
        }

    evidence_rows = market_data.get("evidence_rows") or market_data.get("rows") or []
    if evidence_rows:
        evidence_df = pd.DataFrame([evidence_display_row(row) for row in evidence_rows])
        def color_market_evidence(val):
            text = str(val)
            if text in ["우호", "매우 우호"] or text.startswith("+"):
                return "color: #FF4B4B; font-weight: bold;"
            if text in ["부담", "매우 부담", "비우호"] or text.startswith("-"):
                return "color: #00BFFF; font-weight: bold;"
            return ""

        st.caption("시장환경 근거표")
        evidence_style = evidence_df.style
        evidence_style_method = evidence_style.map if hasattr(evidence_style, "map") else evidence_style.applymap
        evidence_style = evidence_style_method(color_market_evidence, subset=["평가", "점수영향"])
        st.dataframe(
            evidence_style,
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("시장환경 근거표: 표시할 지표 데이터가 아직 없습니다.")
         
    # 데이터 신선도 및 가격 기준 표시
    cache_status = get_cache_status()
    if cache_status:
        st.caption(
            f"ℹ️ **최근 데이터 기준일**: `{cache_status['data_date']}` | "
            f"**가격 기준**: `{cache_status['price_basis']}` | "
            f"**수집 시각**: `{cache_status['price_time']}` | "
            f"**캐시 동기화**: `{cache_status['file_time']}`"
        )
except Exception as e:
    st.error(f"시장 분석 패널 로드 오류: {e}")

st.divider()
st.subheader("2단계: 좋은 회사 후보 찾기")

if st.session_state.data:
    df = analyzer.sort_by_market_cap(pd.DataFrame(st.session_state.data))
    st.session_state.data = df.to_dict(orient="records")
    if "selected_symbol" not in st.session_state and not df.empty:
        st.session_state.selected_symbol = df.iloc[0]["symbol"]
    is_kr = st.session_state.selected_market.startswith("한국")
    
    # config.py의 TABLE_COLUMNS 기반 한글 컬럼명 매핑
    col_map = {col["id"]: col["text"] for col in TABLE_COLUMNS}
    df_renamed = df.rename(columns=col_map)
     
    full_ids = [
        "name", "market_cap", "price",
        "per", "pbr", "roe", "eps_growth", "cagr", "peg", "diff", "peak_diff",
        "data_date", "price_basis", "price_time", "grade", "rank", "symbol"
    ]
    if not is_kr:
        full_ids[3:3] = ["after_market_price", "after_market_change_pct"]

    core_ids = ["name", "market_cap", "price", "per", "roe", "peak_diff", "score", "grade", "rank", "symbol"]
    if not is_kr:
        core_ids.insert(3, "after_market_change_pct")

    compact_ids = core_ids if st.session_state.table_view_mode == "핵심만" else full_ids
    display_cols = [col_map[col_id] for col_id in compact_ids if col_id in col_map and col_map[col_id] in df_renamed.columns]
    df_display = df_renamed[display_cols]
    
    # 수치형 컬럼 변환 (sorting 및 format 적용을 위해)
    numeric_ids = ["rank", "score", "eps_growth", "hist_per_avg", "us_10y_bond", "foreign_supply", 
                   "market_cap", "price", "after_market_price", "after_market_change_pct", "peak", "peak_diff", "ma200", "diff", "rsi", "per", "pbr", "roe", "peg", "cagr",
                   "revenue_growth", "operating_growth", "debt_ratio"]
    numeric_cols = [col_map[idx] for idx in numeric_ids if idx in col_map]
    
    # None 문자열이나 실제 None 객체를 numpy NaN으로 통일하여 결측치 처리기(na_rep)가 작동하게 함
    import numpy as np
    df_display = df_display.replace(["None", "none", "-", ""], np.nan)
    
    for col in numeric_cols:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(df_display[col], errors='coerce')
            
    # CAGR 결측값을 적절히 채우고 수치 타입 명확화
    cagr_col = col_map.get("cagr")
    if cagr_col and cagr_col in df_display.columns:
        df_display[cagr_col] = pd.to_numeric(df_display[cagr_col], errors='coerce')
    market_cap_col = col_map.get("market_cap")
    
    def format_market_cap(value):
        if pd.isna(value):
            return np.nan
        try:
            cap = float(value)
        except (TypeError, ValueError):
            return value
        if is_kr:
            if cap >= 10000:
                return f"{cap / 10000:.1f}조"
            return f"{cap:,.0f}억"
        if cap >= 1_000_000_000_000:
            return f"${cap / 1_000_000_000_000:.2f}T"
        if cap >= 1_000_000_000:
            return f"${cap / 1_000_000_000:.0f}B"
        # Current US cache stores market cap in billions of dollars.
        if cap >= 1000:
            return f"${cap / 1000:.2f}T"
        if cap >= 1:
            return f"${cap:.0f}B"
        return f"${cap / 1_000_000:.0f}M"

    if market_cap_col and market_cap_col in df_display.columns:
        df_display[market_cap_col] = df_display[market_cap_col].apply(format_market_cap)

    for center_col in ["순위", "종합점수", "등급"]:
        if center_col in df_display.columns:
            df_display[center_col] = df_display[center_col].apply(
                lambda v: "" if pd.isna(v) else f"{int(v)}" if isinstance(v, (int, float)) and float(v).is_integer() else str(v)
            )
            
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
    color_cols = [c for c in ["EPS성장률(%)", "200일괴리율(%)", "최고점대비(%)", "ROE(%)", "매출성장률(%)", "영업이익성장률(%)", "애프터등락률(%)"] if c in df_display.columns]
    if color_cols:
        styled_df = style_method(color_kr_style, subset=color_cols)

    center_cols = [c for c in ["종합점수", "등급", "순위", "티커"] if c in df_display.columns]
    if center_cols:
        styled_df = styled_df.set_properties(subset=center_cols, **{"text-align": "center"})

    header_center_cols = ["기준가격", "현재PER", "ROE(%)", "최고점대비(%)"]
    header_styles = [
        {
            "selector": f"th.col_heading.level0.col{idx}",
            "props": [("text-align", "center")],
        }
        for idx, col_name in enumerate(df_display.columns)
        if col_name in header_center_cols
    ]
    if header_styles:
        styled_df = styled_df.set_table_styles(header_styles, overwrite=False)

    # --- [Streamlit Native Column Config] ---
    # 문자/숫자에 따라 컬럼 정렬(오른쪽/왼쪽) 및 포맷 단위(원, $, %, 억 등)를
    # 데이터 타입을 보존하면서 브라우저가 자동 너비 조절하도록 설정
    col_config = {}
    
    for col in TABLE_COLUMNS:
        col_id = col["id"]
        col_text = col["text"]
        
        actual_col_text = col_text
        if actual_col_text not in df_display.columns:
            continue
            
        if col_id in ["price", "peak", "ma200", "after_market_price"]:
            if is_kr:
                col_config[actual_col_text] = st.column_config.NumberColumn(actual_col_text, format="%,d원")
            else:
                col_config[actual_col_text] = st.column_config.NumberColumn(actual_col_text, format="$%,.2f")
        elif col_id == "market_cap":
            col_config[actual_col_text] = st.column_config.TextColumn(actual_col_text)
        elif col_id in ["eps_growth", "roe", "peak_diff", "diff", "cagr", "foreign_supply", "us_10y_bond", "revenue_growth", "operating_growth", "debt_ratio", "after_market_change_pct"]:
            col_config[actual_col_text] = st.column_config.NumberColumn(actual_col_text, format="%.2f%%")
        elif col_id in ["hist_per_avg", "per", "pbr", "peg", "rsi"]:
            col_config[actual_col_text] = st.column_config.NumberColumn(actual_col_text, format="%.2f")
        elif col_id in ["rank", "score"]:
            col_config[actual_col_text] = st.column_config.TextColumn(actual_col_text, alignment="center")
        elif col_id in ["grade", "symbol"]:
            col_config[actual_col_text] = st.column_config.TextColumn(actual_col_text, alignment="center")
        else:
            col_config[actual_col_text] = st.column_config.TextColumn(actual_col_text)

    # --- [최종 화면 렌더링] ---
    # NaN/None 값을 "N/A" 혹은 "-"로 정렬 및 보기 편하도록 포맷팅 지정
    formatted_styled_df = styled_df.format(na_rep="N/A", precision=2)
    view_col, table_action_col = st.columns([6, 1], vertical_alignment="bottom")
    with view_col:
        st.radio(
            "보기 방식",
            ["핵심만", "전체표"],
            key="table_view_mode",
            horizontal=True,
        )
        st.caption("종목 스크리닝 결과표")
    with table_action_col:
        if st.button("⛶ 표 크게 보기", key="toggle_large_table", width="stretch"):
            st.session_state.show_large_table = not st.session_state.get("show_large_table", False)
    # width="stretch": 브라우저 크기에 맞추되 column_config로 각 데이터에 맞게 최적 너비 설정
    st.dataframe(formatted_styled_df, width="stretch", hide_index=True, column_config=col_config)
    if st.session_state.get("show_large_table", False):
        st.caption("확대 보기")
        st.dataframe(formatted_styled_df, width="stretch", height=820, hide_index=True, column_config=col_config)

    st.divider()
    st.subheader("3단계: 좋은 회사인데 왜 안 오르지?")

    symbol_options = {
        f"{row.get('rank', '')}. {row.get('name', row.get('symbol'))} ({row.get('symbol')})": row.get("symbol")
        for _, row in df.iterrows()
    }
    option_values = list(symbol_options.values())
    selected_index = option_values.index(st.session_state.selected_symbol) if st.session_state.selected_symbol in option_values else 0
    selected_label = st.selectbox("상세 진단 종목", list(symbol_options.keys()), index=selected_index)
    st.session_state.selected_symbol = symbol_options[selected_label]
    selected_row = df[df["symbol"] == st.session_state.selected_symbol].iloc[0].to_dict()

    headline, reason_rows = diagnostics.diagnose_why_not_rising(selected_row)
    completeness = diagnostics.data_completeness(selected_row)
    st.info(f"**진단 요약:** {headline}")
    st.caption(
        f"데이터 완성도: `{completeness['score']}%` "
        f"({completeness['available_count']}/{completeness['total_count']})"
        f" | 부족: `{completeness['summary']}`"
    )

    tab_review, tab_missing, tab_reasons, tab_market = st.tabs(["확인한 항목", "부족한 데이터", "안 오르는 이유", "시장환경 연결"])
    with tab_review:
        st.dataframe(pd.DataFrame(diagnostics.build_metric_review(selected_row)), width="stretch", hide_index=True)
    with tab_missing:
        st.dataframe(pd.DataFrame(diagnostics.missing_data_review(selected_row)), width="stretch", hide_index=True)
        supplemental_data.ensure_template()
        st.caption(f"차단 위험 없이 보강하려면 공식/유료 데이터 또는 직접 받은 CSV를 `{supplemental_data.SUPPLEMENTAL_FILE}`에 채우면 다음 수집 때 자동 병합됩니다.")
    with tab_reasons:
        st.dataframe(pd.DataFrame(reason_rows), width="stretch", hide_index=True)
    with tab_market:
        st.dataframe(pd.DataFrame(diagnostics.market_context_review(market_data)), width="stretch", hide_index=True)

else:
    st.info("💡 저장된 캐시 데이터가 없습니다. GitHub Actions의 Run workflow로 수집을 실행한 뒤 [캐시 새로고침]을 눌러주세요.")
