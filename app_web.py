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
    st.session_state.table_view_mode = "모바일 보기"
elif st.session_state.table_view_mode == "핵심만":
    st.session_state.table_view_mode = "모바일 보기"

if "mobile_visible_count" not in st.session_state:
    st.session_state.mobile_visible_count = 5
    
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


def clean_number(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_metric(value, suffix="", decimals=2, na_text="N/A"):
    number = clean_number(value)
    if number is None:
        return na_text
    if decimals == 0:
        return f"{number:,.0f}{suffix}"
    return f"{number:,.{decimals}f}{suffix}"


def format_price(value, is_kr):
    number = clean_number(value)
    if number is None:
        return "N/A"
    if is_kr:
        return f"{number:,.0f}원"
    return f"${number:,.2f}"


def format_cap(value, is_kr):
    number = clean_number(value)
    if number is None:
        return "N/A"
    if is_kr:
        if number >= 10000:
            return f"{number / 10000:.1f}조"
        return f"{number:,.0f}억"
    if number >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:.2f}T"
    if number >= 1_000_000_000:
        return f"${number / 1_000_000_000:.0f}B"
    if number >= 1000:
        return f"${number / 1000:.2f}T"
    if number >= 1:
        return f"${number:.0f}B"
    return f"${number / 1_000_000:.0f}M"


def mobile_grade_label(row):
    cheapness = mobile_cheapness_score(row)
    quality = mobile_quality_score(row)
    risk = mobile_risk_penalty(row)
    if cheapness >= 28 and quality >= 22 and risk <= 10:
        return "🔴 저렴한 우량 후보"
    if cheapness >= 24 and risk <= 18:
        return "🟠 싸지만 확인 필요"
    if quality >= 26 and cheapness < 18:
        return "⚪ 좋은 회사지만 아직 비쌈"
    return "🔵 싼 이유가 위험함"


def mobile_summary(row):
    cheap_reasons = mobile_cheap_reasons(row)
    good_reasons = mobile_good_reasons(row)
    if cheap_reasons and good_reasons:
        return f"싼 이유: {' · '.join(cheap_reasons[:2])} / 좋은 이유: {' · '.join(good_reasons[:2])}"
    if cheap_reasons:
        return f"싼 이유: {' · '.join(cheap_reasons[:3])}"
    if good_reasons:
        return f"좋은 이유: {' · '.join(good_reasons[:3])}"
    return "핵심 지표를 상세보기에서 확인하세요."


def sort_mobile_candidates(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    out["_mobile_score_sort"] = out.apply(lambda row: mobile_candidate_score(row.to_dict()), axis=1)
    out["_rank_sort"] = pd.to_numeric(out.get("rank"), errors="coerce").fillna(999999)
    out = out.sort_values(
        by=["_mobile_score_sort", "_rank_sort"],
        ascending=[False, True],
    )
    return out.drop(columns=["_mobile_score_sort", "_rank_sort"]).reset_index(drop=True)


def bounded(value, low=0, high=100):
    return max(low, min(high, value))


def mobile_cheapness_score(row):
    score = 0
    per = clean_number(row.get("per"))
    hist_per = clean_number(row.get("hist_per_avg"))
    pbr = clean_number(row.get("pbr"))
    peak_diff = clean_number(row.get("peak_diff"))
    diff = clean_number(row.get("diff"))

    if per is not None:
        if per <= 8:
            score += 14
        elif per <= 12:
            score += 11
        elif per <= 18:
            score += 6
        elif per >= 25:
            score -= 4
    if per is not None and hist_per is not None and hist_per > 0:
        discount = (hist_per - per) / hist_per
        if discount >= 0.35:
            score += 14
        elif discount >= 0.2:
            score += 10
        elif discount >= 0.05:
            score += 5
        elif discount <= -0.2:
            score -= 5
    if pbr is not None:
        if pbr <= 0.8:
            score += 10
        elif pbr <= 1.2:
            score += 7
        elif pbr <= 2:
            score += 3
        elif pbr >= 4:
            score -= 4
    if peak_diff is not None:
        if peak_diff <= -35:
            score += 10
        elif peak_diff <= -20:
            score += 7
        elif peak_diff <= -10:
            score += 4
        elif peak_diff > -5:
            score -= 3
    if diff is not None:
        if -25 <= diff <= -5:
            score += 5
        elif diff < -35:
            score -= 4
        elif diff > 20:
            score -= 3
    return bounded(score, 0, 45)


def mobile_quality_score(row):
    score = 0
    roe = clean_number(row.get("roe"))
    revenue = clean_number(row.get("revenue_growth"))
    operating = clean_number(row.get("operating_growth"))
    debt = clean_number(row.get("debt_ratio"))

    if roe is not None:
        if roe >= 20:
            score += 14
        elif roe >= 15:
            score += 11
        elif roe >= 10:
            score += 7
        elif roe < 5:
            score -= 5
    if revenue is not None:
        if revenue >= 15:
            score += 7
        elif revenue > 0:
            score += 4
        else:
            score -= 3
    if operating is not None:
        if operating >= 20:
            score += 8
        elif operating > 0:
            score += 5
        else:
            score -= 4
    if debt is not None:
        if debt <= 80:
            score += 6
        elif debt >= 200:
            score -= 8
    return bounded(score, 0, 35)


def mobile_timing_score(row):
    score = 0
    rsi = clean_number(row.get("rsi"))
    eps_growth = clean_number(row.get("eps_growth"))
    cagr = clean_number(row.get("cagr"))
    foreign_supply = clean_number(row.get("foreign_supply"))

    if rsi is not None:
        if 35 <= rsi <= 60:
            score += 5
        elif rsi >= 70:
            score -= 5
        elif rsi <= 25:
            score -= 2
    if eps_growth is not None:
        if eps_growth >= 15:
            score += 5
        elif eps_growth < 0:
            score -= 5
    if cagr is not None:
        if cagr >= 10:
            score += 4
        elif cagr <= 0:
            score -= 3
    if foreign_supply is not None:
        if foreign_supply >= 15:
            score += 3
        elif foreign_supply < 5:
            score -= 1
    return bounded(score, 0, 20)


def mobile_risk_penalty(row):
    penalty = 0
    debt = clean_number(row.get("debt_ratio"))
    roe = clean_number(row.get("roe"))
    eps_growth = clean_number(row.get("eps_growth"))
    operating = clean_number(row.get("operating_growth"))
    rsi = clean_number(row.get("rsi"))

    if debt is not None and debt >= 200:
        penalty += 10
    if roe is not None and roe < 5:
        penalty += 8
    if eps_growth is not None and eps_growth < 0:
        penalty += 7
    if operating is not None and operating < 0:
        penalty += 6
    if rsi is not None and rsi >= 75:
        penalty += 5
    return bounded(penalty, 0, 25)


def mobile_confidence(row):
    try:
        completeness = diagnostics.data_completeness(row)
        score = int(completeness.get("score", 0))
        missing = completeness.get("summary", "확인 필요")
    except Exception:
        score = 0
        missing = "확인 필요"
    if score >= 80:
        label = "근거 충분"
    elif score >= 60:
        label = "일부 확인 필요"
    elif score >= 40:
        label = "참고만"
    else:
        label = "신뢰 낮음"
    return score, label, missing


def mobile_candidate_score(row):
    confidence, _, _ = mobile_confidence(row)
    data_penalty = 10 if confidence < 40 else 5 if confidence < 60 else 0
    return bounded(
        mobile_cheapness_score(row)
        + mobile_quality_score(row)
        + mobile_timing_score(row)
        - mobile_risk_penalty(row)
        - data_penalty,
        0,
        100,
    )


def mobile_cheap_reasons(row):
    reasons = []
    per = clean_number(row.get("per"))
    hist_per = clean_number(row.get("hist_per_avg"))
    pbr = clean_number(row.get("pbr"))
    peak_diff = clean_number(row.get("peak_diff"))
    diff = clean_number(row.get("diff"))
    if per is not None and per <= 12:
        reasons.append("PER 낮음")
    if per is not None and hist_per is not None and hist_per > 0 and per <= hist_per * 0.8:
        reasons.append("과거 PER 대비 할인")
    if pbr is not None and pbr <= 1.2:
        reasons.append("PBR 낮음")
    if peak_diff is not None and peak_diff <= -20:
        reasons.append("고점 대비 조정")
    if diff is not None and -25 <= diff <= -5:
        reasons.append("장기선 아래 눌림")
    return reasons


def mobile_good_reasons(row):
    reasons = []
    roe = clean_number(row.get("roe"))
    revenue = clean_number(row.get("revenue_growth"))
    operating = clean_number(row.get("operating_growth"))
    debt = clean_number(row.get("debt_ratio"))
    if roe is not None and roe >= 15:
        reasons.append("ROE 우수")
    if revenue is not None and revenue > 0:
        reasons.append("매출 성장")
    if operating is not None and operating > 0:
        reasons.append("영업이익 성장")
    if debt is not None and debt <= 80:
        reasons.append("부채 부담 낮음")
    return reasons


def mobile_warning_reasons(row):
    warnings = []
    debt = clean_number(row.get("debt_ratio"))
    roe = clean_number(row.get("roe"))
    eps_growth = clean_number(row.get("eps_growth"))
    operating = clean_number(row.get("operating_growth"))
    rsi = clean_number(row.get("rsi"))
    confidence, _, missing = mobile_confidence(row)
    if debt is not None and debt >= 200:
        warnings.append("부채비율 높음")
    if roe is not None and roe < 8:
        warnings.append("수익성 약함")
    if eps_growth is not None and eps_growth < 0:
        warnings.append("EPS 역성장")
    if operating is not None and operating < 0:
        warnings.append("영업이익 둔화")
    if rsi is not None and rsi >= 70:
        warnings.append("단기 과열")
    if confidence < 60:
        warnings.append(f"데이터 부족: {missing}")
    return warnings


def render_mobile_market_notes(market_data):
    with st.expander("⚠️ 오늘의 시장 메시지", expanded=False):
        st.write(market_data.get("summary", "시장환경 요약을 확인 중입니다."))
        st.caption(
            "금리, 환율, 업종 강도처럼 숫자로 볼 수 있는 시장 변수는 참고하되, "
            "정책·규제·전쟁 같은 정성 변수는 별도 확인이 필요합니다."
        )
    with st.expander("스크리너가 모르는 것", expanded=False):
        st.caption("숫자로 보이는 저렴함만으로 모든 현실을 설명할 수는 없습니다.")
        st.markdown(
            "- 지정학적 리스크\n"
            "- 정치·규제 변화\n"
            "- 예기치 못한 대형 사건\n"
            "- 경영진의 돌발 이슈\n"
            "- 소송·회계·공시 리스크\n"
            "- 실적 발표 직전 변동성"
        )


def metric_explanation(label, row, value):
    number = clean_number(value)
    if label == "PER":
        hist_per = clean_number(row.get("hist_per_avg"))
        if number is not None and hist_per is not None and hist_per > 0:
            gap = (number / hist_per - 1) * 100
            if gap <= -20:
                return f"현재 PER {number:.2f}는 과거 평균 {hist_per:.2f}보다 {abs(gap):.1f}% 낮습니다. 같은 이익을 내는 회사가 예전보다 싸게 거래되는 상태라 가격 매력이 있습니다."
            if gap >= 20:
                return f"현재 PER {number:.2f}는 과거 평균 {hist_per:.2f}보다 {gap:.1f}% 높습니다. 이미 기대가 많이 반영됐을 수 있어 실적 성장 확인이 필요합니다."
            return f"현재 PER {number:.2f}는 과거 평균 {hist_per:.2f}와 큰 차이가 없습니다. 싸다/비싸다보다 다른 지표와 함께 봐야 합니다."
        if number is not None:
            if number <= 12:
                return f"PER {number:.2f}는 이익 대비 가격 부담이 낮은 편입니다. 다만 실적이 일시적으로 좋아진 착시인지 확인해야 합니다."
            if number >= 25:
                return f"PER {number:.2f}는 이익 대비 비싼 편입니다. 앞으로 이익이 빠르게 늘어야 현재 가격이 정당화됩니다."
            return f"PER {number:.2f}는 중간 구간입니다. 가격 하나만으로 결론내리기보다 ROE와 성장률을 같이 보세요."
        return "PER 데이터가 없습니다. 가격이 싼지 비싼지 판단하려면 최근 이익 데이터 보강이 필요합니다."
    if label == "ROE":
        if number is not None:
            if number >= 15:
                return f"ROE {number:.2f}%는 자기자본으로 돈을 잘 버는 편입니다. 좋은 기업 후보로 볼 수 있지만, 이 수익성이 계속 유지되는지가 중요합니다."
            if number < 8:
                return f"ROE {number:.2f}%는 수익성이 약한 편입니다. 주가가 싸 보여도 기업 품질 때문에 할인받는 것일 수 있습니다."
            return f"ROE {number:.2f}%는 보통 수준입니다. 가격 매력이나 성장성이 같이 좋아야 후보로 보기 쉽습니다."
        return "ROE 데이터가 없습니다. 기업이 자본을 얼마나 효율적으로 쓰는지 판단하려면 이 값이 필요합니다."
    if label == "PBR":
        if number is not None:
            if number <= 1:
                return f"PBR {number:.2f}는 장부가치보다 낮거나 비슷한 가격입니다. 자산 대비 싸 보이지만, 시장이 성장성을 낮게 보는 이유도 확인해야 합니다."
            if number >= 3:
                return f"PBR {number:.2f}는 자산가치 대비 프리미엄이 큽니다. 높은 ROE나 강한 성장성이 뒷받침되어야 부담이 줄어듭니다."
            return f"PBR {number:.2f}는 과도하게 싸거나 비싸다고 단정하기 어려운 구간입니다. ROE와 함께 봐야 합니다."
        return "PBR 데이터가 없습니다. 자산가치 대비 주가 부담을 판단하려면 보강이 필요합니다."
    if label == "PEG":
        if number is not None:
            if 0 < number <= 1:
                return f"PEG {number:.2f}는 성장률을 감안하면 가격 부담이 낮은 편입니다. 성장 전망이 실제로 유지되는지가 핵심입니다."
            if number > 2:
                return f"PEG {number:.2f}는 성장 대비 가격이 비싼 편입니다. 실적 기대가 꺾이면 주가 부담이 커질 수 있습니다."
            return f"PEG {number:.2f}는 중립 구간입니다. PER만 볼 때보다 성장성을 어느 정도 반영한 상태입니다."
        return "PEG 데이터가 없습니다. 성장률을 감안한 가격 매력을 판단하기 어렵습니다."
    if label == "EPS성장률":
        if number is not None:
            if number >= 20:
                return f"EPS성장률 {number:.2f}%는 이익 증가 속도가 빠른 편입니다. 높은 가격도 일부 정당화될 수 있습니다."
            if number < 0:
                return f"EPS성장률 {number:.2f}%는 이익이 줄고 있다는 뜻입니다. 싼 주식처럼 보여도 실적 둔화 리스크가 있습니다."
            return f"EPS성장률 {number:.2f}%는 완만한 성장 구간입니다. 가격이 비싸지 않은지 같이 확인하세요."
        return "EPS성장률 데이터가 없습니다. 이익이 늘고 있는지 줄고 있는지 확인이 필요합니다."
    if label == "CAGR":
        if number is not None:
            if number >= 15:
                return f"CAGR {number:.2f}%는 장기 성장 흐름이 좋은 편입니다. 단기 반짝 성장보다 신뢰도가 높습니다."
            if number <= 0:
                return f"CAGR {number:.2f}%는 장기 성장 흐름이 약합니다. 저평가보다 성장 정체 가능성을 먼저 확인하세요."
            return f"CAGR {number:.2f}%는 완만한 성장입니다. 안정성은 있지만 강한 재평가 동력은 제한적일 수 있습니다."
        return "CAGR 데이터가 없습니다. 장기 성장 흐름을 판단하려면 보강이 필요합니다."
    if label == "매출성장률":
        if number is not None:
            if number > 10:
                return f"매출성장률 {number:.2f}%는 외형이 잘 커지고 있다는 뜻입니다. 이 성장이 이익 증가로 이어지는지 확인하면 좋습니다."
            if number < 0:
                return f"매출성장률 {number:.2f}%는 매출이 줄고 있다는 뜻입니다. 업황 둔화나 경쟁력 약화 가능성을 봐야 합니다."
            return f"매출성장률 {number:.2f}%는 크지 않은 편입니다. 안정적이지만 강한 성장주는 아닐 수 있습니다."
        return "매출성장률 데이터가 없습니다. 회사 규모가 실제로 커지고 있는지 확인하기 어렵습니다."
    if label == "영업이익성장률":
        if number is not None:
            if number > 15:
                return f"영업이익성장률 {number:.2f}%는 본업 이익이 빠르게 늘고 있다는 뜻입니다. 매출보다 이익이 더 잘 늘면 품질이 좋아집니다."
            if number < 0:
                return f"영업이익성장률 {number:.2f}%는 본업 이익이 줄고 있다는 뜻입니다. 비용 증가나 업황 악화를 확인해야 합니다."
            return f"영업이익성장률 {number:.2f}%는 보통 수준입니다. 이익률이 유지되는지 같이 보면 좋습니다."
        return "영업이익성장률 데이터가 없습니다. 본업 수익성이 좋아지는지 판단하기 어렵습니다."
    if label == "부채비율":
        if number is not None:
            if number <= 80:
                return f"부채비율 {number:.2f}%는 재무 부담이 낮은 편입니다. 금리 상승이나 경기 둔화에도 버틸 여지가 비교적 있습니다."
            if number >= 200:
                return f"부채비율 {number:.2f}%는 높은 편입니다. 이자비용과 차환 부담 때문에 업황이 나빠질 때 리스크가 커질 수 있습니다."
            return f"부채비율 {number:.2f}%는 중간 구간입니다. 현금 보유와 영업현금흐름을 함께 확인하세요."
        return "부채비율 데이터가 없습니다. 재무 안전성을 판단하려면 보강이 필요합니다."
    if label == "외인/기관지분":
        if number is not None:
            if number >= 15:
                return f"외인/기관지분 {number:.2f}%는 전문 투자자 관심이 있는 편입니다. 다만 최근에 사고 있는지, 팔고 있는지가 더 중요합니다."
            if number < 5:
                return f"외인/기관지분 {number:.2f}%는 관심이 낮은 편입니다. 주가를 밀어 올릴 수급 동력이 약할 수 있습니다."
            return f"외인/기관지분 {number:.2f}%는 보통 수준입니다. 최근 순매수 방향을 추가로 확인하세요."
        return "수급 데이터가 없습니다. 외국인과 기관의 관심도를 판단하기 어렵습니다."
    if label == "200일괴리율":
        if number is not None:
            if number >= 0:
                return f"200일괴리율 {number:.2f}%는 주가가 장기 평균선 위에 있다는 뜻입니다. 시장이 아직 추세를 인정하고 있습니다."
            if number <= -20:
                return f"200일괴리율 {number:.2f}%는 장기 평균선보다 많이 낮습니다. 싸 보일 수 있지만 추세 회복 확인이 필요합니다."
            return f"200일괴리율 {number:.2f}%는 장기 평균선 아래지만 낙폭은 제한적입니다. 반등 여부를 관찰할 구간입니다."
        return "200일괴리율 데이터가 없습니다. 중장기 추세를 판단하기 어렵습니다."
    if label == "최고점대비":
        if number is not None:
            if number <= -30:
                return f"최고점대비 {number:.2f}%는 고점에서 많이 내려온 상태입니다. 반등 여지는 있지만 하락 이유가 해소됐는지 확인해야 합니다."
            if number > -10:
                return f"최고점대비 {number:.2f}%는 고점과 가깝습니다. 모멘텀은 살아 있지만 추격 매수 부담도 있습니다."
            return f"최고점대비 {number:.2f}%는 적당히 조정받은 상태입니다. 가격 매력과 추세를 함께 볼 구간입니다."
        return "최고점대비 데이터가 없습니다. 현재 가격 위치를 판단하기 어렵습니다."
    if label == "RSI":
        if number is not None:
            if number >= 70:
                return f"RSI {number:.2f}는 단기 과열 구간입니다. 좋은 종목이어도 진입 타이밍은 신중할 필요가 있습니다."
            if number <= 30:
                return f"RSI {number:.2f}는 단기 침체 구간입니다. 반등 후보가 될 수 있지만 하락 원인을 먼저 확인하세요."
            return f"RSI {number:.2f}는 과열도 침체도 아닌 중립 구간입니다. 단기 타이밍보다 기업 지표를 더 봐야 합니다."
        return "RSI 데이터가 없습니다. 단기 과열/침체 판단은 어렵습니다."
    if label == "데이터기준일":
        return f"이 종목 판단에 사용한 데이터 기준일은 {value}입니다. 오래된 데이터라면 최신 실적과 가격으로 다시 확인해야 합니다."
    if label == "가격기준":
        return f"현재 가격 기준은 {value}입니다. 장중, 종가, 애프터 가격 중 무엇을 기준으로 봤는지에 따라 해석이 달라질 수 있습니다."
    return "현재 수치만으로 결론내리기 어렵습니다. 같은 섹션의 다른 지표와 함께 확인하세요."


def render_mobile_metric(label, value_text, explanation):
    st.markdown(f"**{label}**  `{value_text}`")
    with st.expander("설명 보기", expanded=False):
        st.caption(explanation)


def render_mobile_section(title, metrics):
    with st.expander(title, expanded=False):
        if not metrics:
            st.caption("확인 가능한 데이터가 아직 부족합니다.")
        for label, value_text, explanation in metrics:
            render_mobile_metric(label, value_text, explanation)


def render_mobile_stock_card(row, is_kr):
    rank = row.get("rank", "")
    name = row.get("name", row.get("symbol", "이름 없음"))
    symbol = row.get("symbol", "")
    score = format_metric(row.get("score"), decimals=0)
    grade = row.get("grade", "N/A")
    price = format_price(row.get("price"), is_kr)
    cap = format_cap(row.get("market_cap"), is_kr)
    candidate_score = mobile_candidate_score(row)
    confidence_score, confidence_label, confidence_missing = mobile_confidence(row)
    cheap_reasons = mobile_cheap_reasons(row) or ["저렴함 근거 확인 필요"]
    good_reasons = mobile_good_reasons(row) or ["품질 근거 확인 필요"]
    warning_reasons = mobile_warning_reasons(row) or ["정치·규제·뉴스 변수 별도 확인"]

    st.markdown(
        f"""
        <div class="mobile-stock-card">
            <div class="mobile-stock-rank">시장순위 #{rank} · {symbol}</div>
            <div class="mobile-stock-title">{name}</div>
            <div class="mobile-stock-grade">{mobile_grade_label(row)} · 후보적합도 {candidate_score:.0f}점</div>
            <div class="mobile-stock-trust">분석 신뢰도 {confidence_score}% · {confidence_label}</div>
            <div class="mobile-stock-summary">{mobile_summary(row)}</div>
            <div class="mobile-stock-reason"><b>싼 이유</b> {' · '.join(cheap_reasons[:3])}</div>
            <div class="mobile-stock-reason"><b>좋은 이유</b> {' · '.join(good_reasons[:3])}</div>
            <div class="mobile-stock-warning"><b>주의</b> {' · '.join(warning_reasons[:2])}</div>
            <div class="mobile-stock-metrics">
                <span>가격 {price}</span>
                <span>시총 {cap}</span>
                <span>PER {format_metric(row.get("per"))}</span>
                <span>ROE {format_metric(row.get("roe"), "%")}</span>
                <span>등급 {grade}</span>
                <span>종합점수 {score}점</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("상세보기 ▼", expanded=False):
        render_mobile_section("기업 품질", [
            ("ROE", format_metric(row.get("roe"), "%"), metric_explanation("ROE", row, row.get("roe"))),
            ("매출성장률", format_metric(row.get("revenue_growth"), "%"), metric_explanation("매출성장률", row, row.get("revenue_growth"))),
            ("영업이익성장률", format_metric(row.get("operating_growth"), "%"), metric_explanation("영업이익성장률", row, row.get("operating_growth"))),
        ])
        render_mobile_section("가격", [
            ("PER", format_metric(row.get("per")), metric_explanation("PER", row, row.get("per"))),
            ("PBR", format_metric(row.get("pbr")), metric_explanation("PBR", row, row.get("pbr"))),
            ("PEG", format_metric(row.get("peg")), metric_explanation("PEG", row, row.get("peg"))),
        ])
        render_mobile_section("성장성", [
            ("EPS성장률", format_metric(row.get("eps_growth"), "%"), metric_explanation("EPS성장률", row, row.get("eps_growth"))),
            ("CAGR", format_metric(row.get("cagr"), "%"), metric_explanation("CAGR", row, row.get("cagr"))),
        ])
        render_mobile_section("재무", [
            ("부채비율", format_metric(row.get("debt_ratio"), "%"), metric_explanation("부채비율", row, row.get("debt_ratio"))),
            ("시가총액", cap, "기업 규모를 보는 지표입니다. 크다고 항상 좋은 것은 아니지만 안정성 판단에 참고합니다."),
        ])
        render_mobile_section("수급", [
            ("외인/기관지분", format_metric(row.get("foreign_supply"), "%"), metric_explanation("외인/기관지분", row, row.get("foreign_supply"))),
        ])
        render_mobile_section("시장환경", [
            ("200일괴리율", format_metric(row.get("diff"), "%"), metric_explanation("200일괴리율", row, row.get("diff"))),
            ("최고점대비", format_metric(row.get("peak_diff"), "%"), metric_explanation("최고점대비", row, row.get("peak_diff"))),
            ("RSI", format_metric(row.get("rsi")), metric_explanation("RSI", row, row.get("rsi"))),
        ])
        render_mobile_section("리스크", [
            ("데이터기준일", str(row.get("data_date", "N/A")), metric_explanation("데이터기준일", row, row.get("data_date", "N/A"))),
            ("가격기준", str(row.get("price_basis", "N/A")), metric_explanation("가격기준", row, row.get("price_basis", "N/A"))),
            ("분석 신뢰도", f"{confidence_score}% · {confidence_label}", f"이 값은 수익 확률이 아니라 분석에 필요한 데이터가 얼마나 채워졌는지입니다. 부족한 부분: {confidence_missing}"),
            ("스크리너가 모르는 것", "정성·돌발 변수", "지정학, 정치·규제, 대형 사건, 경영진 이슈, 소송·회계 리스크는 점수에 충분히 반영되지 않을 수 있습니다."),
        ])


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
        .mobile-stock-card {
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 8px;
            padding: 14px 14px 12px 14px;
            margin: 12px 0 6px 0;
            background: rgba(255, 255, 255, 0.03);
        }
        .mobile-stock-rank {
            color: #94a3b8;
            font-size: 0.82rem;
            margin-bottom: 4px;
        }
        .mobile-stock-title {
            font-size: 1.1rem;
            font-weight: 700;
            line-height: 1.25;
            margin-bottom: 6px;
        }
        .mobile-stock-grade {
            color: #ff4b4b;
            font-size: 0.92rem;
            font-weight: 650;
            margin-bottom: 6px;
        }
        .mobile-stock-trust {
            color: #e5e7eb;
            font-size: 0.86rem;
            margin-bottom: 6px;
        }
        .mobile-stock-summary {
            color: #cbd5e1;
            font-size: 0.9rem;
            line-height: 1.35;
            margin-bottom: 10px;
        }
        .mobile-stock-reason {
            color: #f8fafc;
            font-size: 0.86rem;
            line-height: 1.35;
            margin-bottom: 4px;
        }
        .mobile-stock-reason b {
            color: #ff4b4b;
            margin-right: 4px;
        }
        .mobile-stock-warning {
            color: #bfdbfe;
            font-size: 0.86rem;
            line-height: 1.35;
            margin: 4px 0 10px 0;
        }
        .mobile-stock-warning b {
            color: #60a5fa;
            margin-right: 4px;
        }
        .mobile-stock-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
            gap: 6px;
            font-size: 0.84rem;
        }
        .mobile-stock-metrics span {
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 6px;
            padding: 6px 8px;
            min-height: 34px;
            display: flex;
            align-items: center;
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

    compact_ids = core_ids if st.session_state.table_view_mode == "모바일 보기" else full_ids
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
            ["모바일 보기", "PC 보기"],
            key="table_view_mode",
            horizontal=True,
        )
        st.caption("모바일은 카드형 후보, PC는 전체표")
    with table_action_col:
        if st.session_state.table_view_mode == "PC 보기" and st.button("⛶ 표 크게 보기", key="toggle_large_table", width="stretch"):
            st.session_state.show_large_table = not st.session_state.get("show_large_table", False)

    if st.session_state.table_view_mode == "모바일 보기":
        mobile_df = sort_mobile_candidates(df)
        total_candidates = len(mobile_df)
        visible_count = min(st.session_state.mobile_visible_count, total_candidates)
        if visible_count <= 0:
            visible_count = min(5, total_candidates)
            st.session_state.mobile_visible_count = visible_count

        title_text = f"전체 저렴 후보 {total_candidates}개" if visible_count >= total_candidates else f"오늘의 저렴 후보 {visible_count}개"
        st.subheader(title_text)
        render_mobile_market_notes(market_data)

        count_cols = st.columns(5)
        quick_options = [("5개", 5), ("10개", 10), ("20개", 20), ("전체", total_candidates)]
        for idx, (label, count) in enumerate(quick_options):
            with count_cols[idx]:
                if st.button(label, key=f"mobile_count_{label}", width="stretch"):
                    st.session_state.mobile_visible_count = min(count, total_candidates)
                    st.rerun()

        with count_cols[4]:
            next_count = min(visible_count + 5, total_candidates)
            if st.button("다음 5개", key="mobile_more_5", width="stretch", disabled=visible_count >= total_candidates):
                st.session_state.mobile_visible_count = next_count
                st.rerun()

        st.caption("정렬 기준: 현재 저렴함을 먼저 보고, 기업 품질·성장·재무·위험 신호로 보정한 후보 적합도순입니다.")
        for _, row in mobile_df.head(visible_count).iterrows():
            render_mobile_stock_card(row.to_dict(), is_kr)
    else:
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
    if hasattr(diagnostics, "data_completeness"):
        completeness = diagnostics.data_completeness(selected_row)
    else:
        completeness = {"score": 0, "available_count": 0, "total_count": 0, "summary": "진단 모듈 업데이트 대기"}
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
        if hasattr(diagnostics, "market_context_review"):
            market_rows = diagnostics.market_context_review(market_data)
        else:
            market_rows = [{
                "구분": "시장환경",
                "항목": market_data.get("score_state", market_data.get("market_state", "미확인")),
                "해석": market_data.get("summary", "진단 모듈 업데이트 대기"),
            }]
        st.dataframe(pd.DataFrame(market_rows), width="stretch", hide_index=True)

else:
    st.info("💡 저장된 캐시 데이터가 없습니다. GitHub Actions의 Run workflow로 수집을 실행한 뒤 [캐시 새로고침]을 눌러주세요.")
