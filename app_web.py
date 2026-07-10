import os
import html
import glob
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

MOBILE_LENS_META = {
    "🎯 종합평가": {
        "short": "종합평가",
        "score_label": "종합평가",
        "title": "종합평가 후보",
        "description": "좋은 회사와 좋은 가격을 함께 고려해 장기 투자 후보를 우선 표시합니다.",
        "criteria": [
            ("품질", "ROE와 이익 성장으로 좋은 회사인지 봅니다."),
            ("가격", "PER/PBR과 고점 대비 위치를 함께 봅니다."),
            ("성장", "매출, 영업이익, EPS가 같이 늘고 있는지 봅니다."),
            ("리스크", "부채, 현금흐름, 과열 여부를 함께 봅니다."),
        ],
    },
    "🏢 좋은 회사": {
        "short": "좋은회사",
        "score_label": "품질점수",
        "title": "좋은 회사",
        "description": "돈을 꾸준히 잘 버는 회사를 우선 표시합니다.",
        "criteria": [
            ("ROE", "자본을 얼마나 효율적으로 쓰는지 봅니다."),
            ("영업률", "본업에서 이익을 남기는 힘을 봅니다."),
            ("성장", "매출과 영업이익이 함께 늘고 있는지 봅니다."),
            ("재무체력", "부채와 현금흐름이 품질을 받치는지 봅니다."),
        ],
    },
    "💰 저평가": {
        "short": "저평가",
        "score_label": "저평가점수",
        "title": "저평가 후보",
        "description": "기업 가치 대비 가격이 싼 회사를 우선 표시합니다.",
        "criteria": [
            ("PER", "이익 대비 주가가 낮은지 봅니다."),
            ("PBR", "자산 대비 주가가 낮은지 봅니다."),
            ("업종괴리", "같은 업종 평균보다 싼지 봅니다."),
            ("가격위치", "고점 대비 얼마나 내려왔는지 봅니다."),
        ],
    },
    "📈 성장": {
        "short": "성장",
        "score_label": "성장점수",
        "title": "성장 후보",
        "description": "실적이 빠르게 증가하는 회사를 우선 표시합니다.",
        "criteria": [
            ("매출성장률", "외형이 커지고 있는지 봅니다."),
            ("영업익성장", "성장이 이익으로 이어지는지 봅니다."),
            ("EPS성장", "주당 이익이 늘고 있는지 봅니다."),
            ("지속성", "CAGR과 수익성으로 성장의 질을 봅니다."),
        ],
    },
    "💸 현금창출": {
        "short": "현금창출",
        "score_label": "현금창출점수",
        "title": "현금창출 후보",
        "description": "FCF와 영업현금흐름 등 실제 현금을 만들어내는 회사를 우선 표시합니다.",
        "criteria": [
            ("영업현금흐름", "본업에서 현금이 들어오는지 봅니다."),
            ("FCF", "투자 후 남는 현금이 있는지 봅니다."),
            ("현금여력", "순현금과 현금 보유가 충분한지 봅니다."),
            ("부채부담", "현금창출을 빚이 갉아먹는지 봅니다."),
        ],
    },
    "🏦 배당": {
        "short": "배당",
        "score_label": "배당점수",
        "title": "배당 후보",
        "description": "배당수익률과 배당 지속 가능성을 함께 봅니다.",
        "criteria": [
            ("연배당률", "현재 가격 대비 배당 매력이 있는지 봅니다."),
            ("배당성향", "이익 대비 배당이 무리하지 않은지 봅니다."),
            ("지속성", "연속 배당과 삭감 여부를 봅니다."),
            ("배당여력", "FCF와 영업현금흐름이 배당을 받치는지 봅니다."),
        ],
    },
    "🔥 모멘텀": {
        "short": "모멘텀",
        "score_label": "모멘텀점수",
        "title": "모멘텀 후보",
        "description": "최근 시장의 선택을 받는 회사를 우선 표시합니다.",
        "criteria": [
            ("200일선", "장기 추세 위에 있는지 봅니다."),
            ("가격위치", "고점권 또는 회복 흐름인지 봅니다."),
            ("RSI", "단기 수급 온기와 과열을 함께 봅니다."),
            ("주도테마", "시장 관심 업종에 속하는지 봅니다."),
        ],
    },
    "🛡 안정성": {
        "short": "안정성",
        "score_label": "안정성점수",
        "title": "안정성 후보",
        "description": "위기에도 버틸 가능성이 높은 회사를 우선 표시합니다.",
        "criteria": [
            ("부채비율", "무리한 빚이 있는지 봅니다."),
            ("순현금", "현금에서 총부채를 뺀 여력을 봅니다."),
            ("영업현금흐름", "본업 현금 창출이 안정적인지 봅니다."),
            ("이익변동", "ROE와 이익 성장의 안정성을 함께 봅니다."),
        ],
    },
}

MOBILE_LENS_OPTIONS = list(MOBILE_LENS_META.keys())

MOBILE_SECONDARY_LENS_META = {
    "오늘 새로 뜬 종목": {
        "short": "오늘 새로 뜬 종목",
        "description": "점수와 순위가 최근 빠르게 좋아진 종목",
    },
    "아직 덜 오른 종목": {
        "short": "아직 덜 오른 종목",
        "description": "기업 평가는 좋지만 주가 반영은 낮은 종목",
    },
    "왜 안 오르지": {
        "short": "왜 안 오르지",
        "description": "좋은 조건에도 주가가 부진한 이유를 분석",
    },
}

MOBILE_SECONDARY_LENS_OPTIONS = list(MOBILE_SECONDARY_LENS_META.keys())

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

if "mobile_selected_symbol" not in st.session_state:
    st.session_state.mobile_selected_symbol = None

if "mobile_evidence_symbol" not in st.session_state:
    st.session_state.mobile_evidence_symbol = None

if "mobile_detail_tab" not in st.session_state:
    st.session_state.mobile_detail_tab = "요약"

if "mobile_investment_lens" not in st.session_state:
    st.session_state.mobile_investment_lens = "🎯 종합평가"
elif st.session_state.mobile_investment_lens not in MOBILE_LENS_OPTIONS:
    st.session_state.mobile_investment_lens = "🎯 종합평가"

if "mobile_secondary_lens" not in st.session_state:
    st.session_state.mobile_secondary_lens = None
elif st.session_state.mobile_secondary_lens not in MOBILE_SECONDARY_LENS_OPTIONS:
    st.session_state.mobile_secondary_lens = None

if "last_mobile_investment_lens" not in st.session_state:
    st.session_state.last_mobile_investment_lens = st.session_state.mobile_investment_lens
    
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
                df_cached = analyzer.normalize_dividend_yield_metrics(df_cached)
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


def row_is_kr(row):
    symbol = str(row.get("symbol", ""))
    yf_symbol = str(row.get("yf_symbol", ""))
    return symbol.isdigit() or yf_symbol.endswith((".KS", ".KQ"))


def format_cashflow_amount(value, row):
    number = clean_number(value)
    if number is None:
        return "N/A"
    if row_is_kr(row):
        if abs(number) >= 10000:
            return f"{number / 10000:,.1f}조"
        return f"{number:,.0f}억"
    if abs(number) >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:,.2f}T"
    if abs(number) >= 1_000_000_000:
        return f"${number / 1_000_000_000:,.1f}B"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:,.0f}M"
    return f"${number:,.0f}"


def escape_html(value):
    return html.escape(str(value if value is not None else ""))


def mobile_grade_label(row):
    risk_profile = mobile_structural_risk(row)
    if risk_profile["level"] == "hard":
        return "🔵 정책·구조 리스크 상한 후보"
    if risk_profile["level"] == "medium":
        return "🟠 규제·외부변수 확인 후보"
    cheapness = mobile_cheapness_score(row)
    quality = mobile_quality_score(row)
    momentum = mobile_momentum_score(row)
    risk = mobile_risk_penalty(row)
    if momentum >= 24 and risk <= 14:
        return "🔥 주도업종 모멘텀 후보"
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


def sort_mobile_candidates(df, lens="🎯 종합평가"):
    if df is None or df.empty:
        return df
    out = df.copy()
    out["_mobile_score_sort"] = out.apply(lambda row: mobile_lens_score(row.to_dict(), lens), axis=1)
    out["_rank_sort"] = pd.to_numeric(out.get("rank"), errors="coerce").fillna(999999)
    out = out.sort_values(
        by=["_mobile_score_sort", "_rank_sort"],
        ascending=[False, True],
    )
    return out.drop(columns=["_mobile_score_sort", "_rank_sort"]).reset_index(drop=True)


def mobile_cache_files_for_market(market_text):
    cache_dir = "cache"
    prefix = f"snapshot_{market_text}_"
    if not os.path.isdir(cache_dir):
        return []
    files = []
    for path in glob.glob(os.path.join(cache_dir, f"{prefix}*.csv")):
        name = os.path.basename(path)
        date_part = name[-12:-4]
        if len(date_part) == 8 and date_part.isdigit():
            files.append((date_part, path))
    return [path for _, path in sorted(files)]


def mobile_price_return(current_price, past_price):
    current_price = clean_number(current_price)
    past_price = clean_number(past_price)
    if current_price is None or past_price is None or past_price <= 0:
        return None
    return (current_price - past_price) / past_price * 100


@st.cache_data(ttl=1800)
def load_mobile_history_context(market_text):
    files = mobile_cache_files_for_market(market_text)
    current_file = analyzer.find_latest_valid_cache(market_text)
    if not files:
        return {"previous": {}, "price_20": {}, "price_60": {}, "current_file": current_file}

    normalized_files = [os.path.normpath(path) for path in files]
    current_file = os.path.normpath(current_file) if current_file else normalized_files[-1]
    if current_file not in normalized_files:
        current_file = normalized_files[-1]
    current_index = normalized_files.index(current_file)
    previous_file = normalized_files[current_index - 1] if current_index > 0 else None

    def read_snapshot_map(path, columns):
        if not path:
            return {}
        try:
            snapshot = pd.read_csv(path, usecols=lambda col: col in columns)
        except Exception:
            return {}
        if "symbol" not in snapshot.columns:
            return {}
        snapshot["symbol"] = snapshot["symbol"].astype(str)
        return snapshot.set_index("symbol").to_dict(orient="index")

    def file_on_or_before(days_back):
        try:
            current_date = pd.to_datetime(os.path.basename(current_file).split("_")[-1].replace(".csv", ""))
        except Exception:
            return None
        target_date = current_date - pd.Timedelta(days=days_back)
        candidate = None
        for path in normalized_files[:current_index]:
            try:
                path_date = pd.to_datetime(os.path.basename(path).split("_")[-1].replace(".csv", ""))
            except Exception:
                continue
            if path_date <= target_date:
                candidate = path
            else:
                break
        return candidate or previous_file

    previous = read_snapshot_map(previous_file, ["symbol", "score", "rank", "rsi", "score_rsi", "price"])
    price_20 = read_snapshot_map(file_on_or_before(20), ["symbol", "price"])
    price_60 = read_snapshot_map(file_on_or_before(60), ["symbol", "price"])
    return {
        "previous": previous,
        "price_20": price_20,
        "price_60": price_60,
        "current_file": current_file,
    }


def mobile_history_metrics(row, history_context, total_count):
    symbol = str(row.get("symbol", ""))
    previous = history_context.get("previous", {}).get(symbol, {})
    price_20 = history_context.get("price_20", {}).get(symbol, {})
    price_60 = history_context.get("price_60", {}).get(symbol, {})

    score = clean_number(row.get("score"))
    prev_score = clean_number(previous.get("score"))
    rank = clean_number(row.get("rank"))
    prev_rank = clean_number(previous.get("rank"))
    rsi = clean_number(row.get("rsi"))
    prev_rsi = clean_number(previous.get("rsi"))
    score_rsi = clean_number(row.get("score_rsi"))
    prev_score_rsi = clean_number(previous.get("score_rsi"))
    top_cutoff = max(1, int(total_count * 0.2)) if total_count else 0

    new_top20 = False
    if rank is not None and top_cutoff and rank <= top_cutoff:
        new_top20 = prev_rank is None or prev_rank > top_cutoff

    return {
        "score_delta": score - prev_score if score is not None and prev_score is not None else None,
        "rank_delta": prev_rank - rank if rank is not None and prev_rank is not None else None,
        "rsi_delta": rsi - prev_rsi if rsi is not None and prev_rsi is not None else None,
        "tech_delta": score_rsi - prev_score_rsi if score_rsi is not None and prev_score_rsi is not None else None,
        "new_top20": new_top20,
        "return_20": mobile_price_return(row.get("price"), price_20.get("price")),
        "return_60": mobile_price_return(row.get("price"), price_60.get("price")),
    }


def secondary_chip(label, value):
    return f"{label} {value}"


def mobile_secondary_analysis(row, secondary_lens, history_context, total_count):
    if not secondary_lens:
        return {"selected": True, "score": 0, "chips": [], "sentence": "", "details": []}

    metrics = mobile_history_metrics(row, history_context, total_count)
    score = clean_number(row.get("score"))
    quality_score = mobile_lens_score(row, "🏢 좋은 회사")
    composite_score = mobile_lens_score(row, "🎯 종합평가")
    growth_score = mobile_growth_score(row)
    value_score = mobile_lens_score(row, "💰 저평가")
    stability_score = mobile_stability_score(row)
    debt = clean_number(row.get("debt_ratio"))
    per = clean_number(row.get("per"))
    pbr = clean_number(row.get("pbr"))
    rsi = clean_number(row.get("rsi"))
    diff = clean_number(row.get("diff"))
    peak_diff = clean_number(row.get("peak_diff"))
    revenue_growth = clean_number(row.get("revenue_growth"))
    operating_growth = clean_number(row.get("operating_growth"))
    operating_income = clean_number(row.get("operating_income"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    free_cashflow = clean_number(row.get("free_cashflow"))

    if secondary_lens == "오늘 새로 뜬 종목":
        checks = []
        chips = []
        core_improved = False
        if metrics["score_delta"] is not None and metrics["score_delta"] >= 3:
            checks.append(18 + min(metrics["score_delta"], 12))
            chips.append(secondary_chip("점수", f"+{metrics['score_delta']:.0f}"))
            core_improved = True
        if metrics["rank_delta"] is not None and metrics["rank_delta"] >= 10:
            checks.append(18 + min(metrics["rank_delta"] / 2, 20))
            chips.append(secondary_chip("순위", f"+{metrics['rank_delta']:.0f}"))
            core_improved = True
        if metrics["new_top20"]:
            checks.append(20)
            chips.append("상위 20% 신규")
            core_improved = True
        if metrics["tech_delta"] is not None and metrics["tech_delta"] >= 5:
            checks.append(10)
            chips.append(secondary_chip("기술", f"+{metrics['tech_delta']:.0f}"))
        if metrics["rsi_delta"] is not None and metrics["rsi_delta"] >= 5:
            checks.append(8)
            chips.append(secondary_chip("RSI", f"+{metrics['rsi_delta']:.0f}"))
        selected = core_improved and len(checks) >= 2
        return {
            "selected": selected,
            "score": sum(checks),
            "chips": chips[:4],
            "sentence": "점수와 순위가 함께 빠르게 개선되고 있습니다." if selected else "최근 개선 근거가 아직 충분하지 않습니다.",
            "details": chips,
        }

    if secondary_lens == "아직 덜 오른 종목":
        profit_ok = (operating_income is not None and operating_income > 0) or (operating_growth is not None and operating_growth >= 0)
        debt_ok = debt is None or debt <= 200
        eligible = quality_score >= 70 and composite_score >= 65 and profit_ok and debt_ok
        checks = []
        chips = [
            secondary_chip("좋은회사", f"{quality_score:.0f}점"),
            secondary_chip("종합", f"{composite_score:.0f}점"),
        ]
        if metrics["return_20"] is not None and metrics["return_20"] <= 5:
            checks.append(12)
            chips.append(secondary_chip("20일", f"{metrics['return_20']:+.1f}%"))
        if metrics["return_60"] is not None and metrics["return_60"] <= 10:
            checks.append(14)
            chips.append(secondary_chip("60일", f"{metrics['return_60']:+.1f}%"))
        if peak_diff is not None and peak_diff <= -15:
            checks.append(13)
            chips.append(secondary_chip("고점대비", f"{peak_diff:.0f}%"))
        if rsi is not None and 35 <= rsi <= 55:
            checks.append(10)
            chips.append(secondary_chip("RSI", f"{rsi:.0f}"))
        if per is not None and per <= 25:
            checks.append(8)
            chips.append(secondary_chip("PER", f"{per:.1f}"))
        if pbr is not None and pbr <= 3:
            checks.append(8)
            chips.append(secondary_chip("PBR", f"{pbr:.1f}"))
        selected = eligible and len(checks) >= 2
        return {
            "selected": selected,
            "score": quality_score * 0.4 + composite_score * 0.35 + sum(checks),
            "chips": chips[:4],
            "sentence": "기업 평가는 높지만 최근 주가 상승은 제한적입니다." if selected else "기업 평가와 가격 미반영 조건이 동시에 충분하지 않습니다.",
            "details": chips,
        }

    if secondary_lens == "왜 안 오르지":
        weak_price = (
            (metrics["return_20"] is not None and metrics["return_20"] <= 0)
            or (metrics["return_60"] is not None and metrics["return_60"] <= 5)
            or (peak_diff is not None and peak_diff <= -20)
        )
        eligible = quality_score >= 70 and composite_score >= 65 and weak_price
        reasons = []
        chips = [
            secondary_chip("좋은회사", f"{quality_score:.0f}점"),
        ]
        if metrics["return_60"] is not None:
            chips.append(secondary_chip("60일", f"{metrics['return_60']:+.1f}%"))
        elif metrics["return_20"] is not None:
            chips.append(secondary_chip("20일", f"{metrics['return_20']:+.1f}%"))

        if (per is not None and per >= 30) or (pbr is not None and pbr >= 4) or value_score < 45:
            reason_value = f"PER {per:.1f}" if per is not None and per >= 30 else f"PBR {pbr:.1f}" if pbr is not None and pbr >= 4 else "가치점수 낮음"
            reasons.append(("가격 부담", reason_value, 18))
        if (revenue_growth is not None and revenue_growth <= 0) or (operating_growth is not None and operating_growth <= 0) or growth_score < 45:
            reason_value = f"영업익 {operating_growth:.1f}%" if operating_growth is not None else "성장점수 낮음"
            reasons.append(("실적 둔화", reason_value, 15))
        weak_tech = 0
        if rsi is not None and rsi <= 40:
            weak_tech += 1
        if diff is not None and diff < 0:
            weak_tech += 1
        if peak_diff is not None and peak_diff <= -20:
            weak_tech += 1
        if metrics["return_20"] is not None and metrics["return_20"] < 0:
            weak_tech += 1
        if weak_tech >= 2:
            reason_value = f"RSI {rsi:.0f}" if rsi is not None else f"고점대비 {peak_diff:.0f}%"
            reasons.append(("기술 약세", reason_value, 16))
        if (debt is not None and debt >= 200) or (operating_cashflow is not None and operating_cashflow < 0) or (free_cashflow is not None and free_cashflow < 0) or stability_score < 45:
            reason_value = f"부채 {debt:.0f}%" if debt is not None and debt >= 200 else "현금흐름 약함"
            reasons.append(("재무 부담", reason_value, 12))

        reasons = sorted(reasons, key=lambda item: item[2], reverse=True)[:3]
        reason_chips = [label for label, _, _ in reasons]
        selected = eligible and bool(reasons)
        return {
            "selected": selected,
            "score": quality_score + composite_score * 0.5 + sum(item[2] for item in reasons),
            "chips": (chips + reason_chips)[:4],
            "sentence": f"{' · '.join(reason_chips)}이 주가를 누르는 요인으로 보입니다." if selected else "좋은 종목이지만 부진 원인을 특정할 근거가 아직 약합니다.",
            "details": [f"{label}: {value}" for label, value, _ in reasons],
        }

    return {"selected": True, "score": 0, "chips": [], "sentence": "", "details": []}


def apply_mobile_secondary_lens(df, secondary_lens, market_text):
    if df is None or df.empty or not secondary_lens:
        return df, {}
    history_context = load_mobile_history_context(market_text)
    total_count = len(df)
    rows = []
    analyses = {}
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        analysis = mobile_secondary_analysis(row_dict, secondary_lens, history_context, total_count)
        symbol = str(row_dict.get("symbol", ""))
        analyses[symbol] = analysis
        if analysis["selected"]:
            enriched = row.copy()
            enriched["_secondary_score"] = analysis["score"]
            rows.append(enriched)
    if not rows:
        return df.head(0).copy(), analyses
    out = pd.DataFrame(rows)
    out = out.sort_values("_secondary_score", ascending=False).drop(columns=["_secondary_score"]).reset_index(drop=True)
    return out, analyses


def filter_mobile_candidates(df):
    if df is None or df.empty:
        return df
    out = df.copy()
    labels = out.apply(lambda row: mobile_grade_label(row.to_dict()), axis=1)
    return out[labels != "⚪ 좋은 회사지만 아직 비쌈"].reset_index(drop=True)


def filter_mobile_candidates_for_lens(df, lens):
    if lens == "🎯 종합평가":
        return filter_mobile_candidates(df)
    if df is None or df.empty:
        return df
    return df.reset_index(drop=True)


def bounded(value, low=0, high=100):
    return max(low, min(high, value))


def mobile_theme_tags(row):
    text = " ".join([
        str(row.get("name", "")),
        str(row.get("symbol", "")),
        str(row.get("sector", "")),
        str(row.get("industry", "")),
    ]).lower()
    if mobile_structural_risk(row)["level"] == "hard":
        return []
    theme_keywords = {
        "반도체": ["반도체", "semiconductor", "semi", "하이닉스", "sk하이닉스", "삼성전자", "db하이텍", "한미반도체", "리노공업", "테스", "원익", "솔브레인"],
        "AI": ["ai", "인공지능", "엔비디아", "nvidia", "nvda", "amd", "브로드컴", "avgo"],
        "전력기기": ["변압기", "전선", "hd현대일렉트릭", "효성중공업", "ls electric", "ls일렉트릭", "일진전기", "대한전선"],
        "조선": ["조선", "선박", "해양", "hd한국조선해양", "한화오션", "삼성중공업"],
        "방산": ["방산", "항공우주", "한화에어로", "lig넥스원", "현대로템"],
    }
    tags = []
    for theme, keywords in theme_keywords.items():
        if any(keyword.lower() in text for keyword in keywords):
            tags.append(theme)
    return tags


def mobile_structural_risk(row):
    text = " ".join([
        str(row.get("name", "")),
        str(row.get("symbol", "")),
        str(row.get("sector", "")),
        str(row.get("industry", "")),
    ]).lower()
    hard_rules = [
        (
            ["한국전력", "kepco", "015760", "한국가스공사", "036460", "지역난방공사", "071320"],
            60,
            "정부 요금·공공정책 영향",
            "전기·가스요금과 정부정책 영향으로 저평가가 오래 지속될 수 있습니다.",
        ),
        (
            ["관리종목", "상장폐지", "감사의견", "거래정지"],
            60,
            "상장·회계 리스크",
            "상장 유지나 회계 신뢰도 문제가 있으면 수치가 좋아도 후보 상단에 두기 어렵습니다.",
        ),
    ]
    medium_rules = [
        (
            ["은행", "금융지주", "보험", "증권", "kb금융", "신한지주", "하나금융", "우리금융", "기업은행"],
            70,
            "금융 규제산업",
            "배당·자본규제·정책 압박으로 밸류에이션 상단이 제한될 수 있습니다.",
        ),
        (
            ["통신", "kt", "skt", "sk텔레콤", "lg유플러스"],
            70,
            "통신 규제산업",
            "요금 규제와 정치적 압박으로 싸 보이는 상태가 길어질 수 있습니다.",
        ),
        (
            ["카지노", "면세", "화장품", "중국", "호텔신라", "아모레", "lg생활건강"],
            70,
            "중국·지정학 민감",
            "외교·중국 소비·관광 정책 변화가 숫자보다 크게 작용할 수 있습니다.",
        ),
        (
            ["항공", "해운", "정유", "철강", "화학", "대한항공", "hmm", "팬오션", "s-oil", "posco", "포스코"],
            70,
            "원자재·환율 민감",
            "유가, 운임, 환율, 스프레드에 따라 이익이 빠르게 바뀔 수 있습니다.",
        ),
    ]
    cycle_keywords = ["조선", "해운", "철강", "화학", "메모리", "반도체", "정유"]

    for keywords, cap, label, warning in hard_rules:
        if any(keyword.lower() in text for keyword in keywords):
            return {"level": "hard", "cap": cap, "label": label, "warning": warning}
    for keywords, cap, label, warning in medium_rules:
        if any(keyword.lower() in text for keyword in keywords):
            return {"level": "medium", "cap": cap, "label": label, "warning": warning}
    if any(keyword.lower() in text for keyword in cycle_keywords):
        return {
            "level": "cycle",
            "cap": None,
            "label": "사이클 확인 필요",
            "warning": "사이클 업종은 실적 고점과 업황 방향을 함께 확인해야 합니다.",
        }
    return {"level": "none", "cap": None, "label": "", "warning": ""}


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
    if diff is not None:
        if -25 <= diff <= -5:
            score += 5
        elif diff < -35:
            score -= 4
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


def mobile_momentum_score(row):
    score = 0
    tags = mobile_theme_tags(row)
    peak_diff = clean_number(row.get("peak_diff"))
    diff = clean_number(row.get("diff"))
    rsi = clean_number(row.get("rsi"))
    eps_growth = clean_number(row.get("eps_growth"))
    revenue = clean_number(row.get("revenue_growth"))
    operating = clean_number(row.get("operating_growth"))
    foreign_supply = clean_number(row.get("foreign_supply"))

    if tags:
        score += 12
    if peak_diff is not None:
        if peak_diff > -10:
            score += 7
        elif peak_diff > -20:
            score += 4
    if diff is not None:
        if diff >= 0:
            score += 7
        elif diff >= -5:
            score += 3
    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 5
        elif rsi > 78:
            score -= 4
    if eps_growth is not None and eps_growth >= 15:
        score += 4
    if revenue is not None and revenue >= 10:
        score += 3
    if operating is not None and operating >= 15:
        score += 4
    if foreign_supply is not None and foreign_supply >= 15:
        score += 3
    return bounded(score, 0, 35)


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
        available_count = int(completeness.get("available_count", 0))
        total_count = int(completeness.get("total_count", 0))
    except Exception:
        score = 0
        missing = "확인 필요"
        available_count = 0
        total_count = 0
    if score >= 80:
        label = "근거 충분"
    elif score >= 60:
        label = "일부 확인 필요"
    elif score >= 40:
        label = "참고만"
    else:
        label = "신뢰 낮음"
    return score, label, missing, available_count, total_count


def mobile_candidate_score(row):
    confidence, _, _, _, _ = mobile_confidence(row)
    data_penalty = 10 if confidence < 40 else 5 if confidence < 60 else 0
    raw_score = bounded(
        mobile_cheapness_score(row)
        + mobile_quality_score(row)
        + mobile_timing_score(row)
        + mobile_momentum_score(row)
        - mobile_risk_penalty(row)
        - data_penalty,
        0,
        100,
    )
    risk_profile = mobile_structural_risk(row)
    if risk_profile["cap"] is not None:
        return min(raw_score, risk_profile["cap"])
    return raw_score


def mobile_score_breakdown(row):
    confidence, _, _, _, _ = mobile_confidence(row)
    data_penalty = 10 if confidence < 40 else 5 if confidence < 60 else 0
    risk_profile = mobile_structural_risk(row)
    cheapness = mobile_cheapness_score(row)
    quality = mobile_quality_score(row)
    timing = mobile_timing_score(row)
    momentum = mobile_momentum_score(row)
    risk = mobile_risk_penalty(row)
    raw = bounded(cheapness + quality + timing + momentum - risk - data_penalty, 0, 100)
    final = min(raw, risk_profile["cap"]) if risk_profile["cap"] is not None else raw
    rows = [
        ("저렴함", f"+{cheapness:.0f}", "PER, PBR, 과거 평균 대비 할인, 고점 대비 조정"),
        ("기업 품질", f"+{quality:.0f}", "ROE, 매출 성장, 영업이익 성장, 부채 부담"),
        ("시장/타이밍", f"+{timing:.0f}", "RSI, EPS 성장, CAGR, 외인/기관 관심"),
        ("주도 모멘텀", f"+{momentum:.0f}", "주도 테마, 200일선, 고점권, 수급 온기"),
        ("위험 감점", f"-{risk:.0f}", "부채, 수익성, 역성장, 과열"),
        ("데이터 부족", f"-{data_penalty:.0f}", "분석 신뢰도 부족 감점"),
    ]
    if risk_profile["cap"] is not None:
        rows.append(("구조 상한", f"≤{risk_profile['cap']}", risk_profile["warning"]))
    rows.append(("최종", f"{final:.0f}", "후보 목록 정렬에 쓰는 점수"))
    return rows


def mobile_growth_score(row):
    score = 0
    revenue = clean_number(row.get("revenue_growth"))
    operating = clean_number(row.get("operating_growth"))
    eps_growth = clean_number(row.get("eps_growth"))
    cagr = clean_number(row.get("cagr"))
    roe = clean_number(row.get("roe"))

    for value, strong, good, weak in [
        (revenue, 20, 12, 0),
        (operating, 25, 12, 0),
        (eps_growth, 20, 10, 0),
        (cagr, 15, 8, 0),
    ]:
        if value is None:
            continue
        if value >= strong:
            score += 18
        elif value >= good:
            score += 12
        elif value > weak:
            score += 7
        else:
            score -= 8
    if roe is not None:
        if roe >= 15:
            score += 12
        elif roe >= 8:
            score += 6
        elif roe < 5:
            score -= 6
    return bounded(score, 0, 100)


def mobile_cash_generation_score(row):
    score = 0
    fcf = clean_number(row.get("free_cashflow"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    net_cash = clean_number(row.get("net_cash"))
    cash = clean_number(row.get("cash"))
    operating_margin = clean_number(row.get("operating_margin"))
    debt = clean_number(row.get("debt_ratio"))

    if fcf is not None:
        score += 24 if fcf > 0 else -12
    if operating_cashflow is not None:
        score += 24 if operating_cashflow > 0 else -12
    if net_cash is not None:
        score += 20 if net_cash > 0 else -6
    if cash is not None and cash > 0:
        score += 10
    if operating_margin is not None:
        if operating_margin >= 15:
            score += 14
        elif operating_margin >= 8:
            score += 8
        elif operating_margin < 0:
            score -= 8
    if debt is not None:
        if debt <= 80:
            score += 8
        elif debt >= 200:
            score -= 12
    return bounded(score, 0, 100)


def mobile_dividend_score(row):
    score = 0
    dividend_yield = clean_number(row.get("dividend_yield"))
    payout_ratio = clean_number(row.get("payout_ratio"))
    dividend_per_share = clean_number(row.get("dividend_per_share"))
    dividend_growth = clean_number(row.get("dividend_growth_3y"))
    consecutive_years = clean_number(row.get("dividend_consecutive_years"))
    dividend_cut = row.get("dividend_cut_flag")
    fcf = clean_number(row.get("free_cashflow"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    net_cash = clean_number(row.get("net_cash"))
    debt = clean_number(row.get("debt_ratio"))

    yield_cap = 100
    if dividend_yield is not None:
        if 2.5 <= dividend_yield <= 7:
            score += 45
        elif 2 <= dividend_yield < 2.5:
            score += 36
        elif 1.5 <= dividend_yield < 2:
            score += 28
            yield_cap = 75
        elif 1 <= dividend_yield < 1.5:
            score += 20
            yield_cap = 65
        elif 0 < dividend_yield < 1:
            score += 10
            yield_cap = 55
        elif dividend_yield > 7:
            score += 30
        elif dividend_yield <= 0:
            yield_cap = 40
    else:
        yield_cap = 40

    if payout_ratio is not None:
        if 20 <= payout_ratio <= 70:
            score += 20
        elif 0 < payout_ratio < 20 or 70 < payout_ratio <= 100:
            score += 10
        elif payout_ratio > 100:
            score -= 12

    if dividend_per_share is not None:
        score += 4 if dividend_per_share > 0 else -4
    if dividend_growth is not None:
        score += 8 if dividend_growth > 0 else -6
    if consecutive_years is not None:
        if consecutive_years >= 5:
            score += 8
        elif consecutive_years >= 2:
            score += 4
    if str(dividend_cut).strip().lower() in {"true", "1", "yes"}:
        score -= 14

    if fcf is not None:
        score += 5 if fcf > 0 else -8
    if operating_cashflow is not None:
        score += 5 if operating_cashflow > 0 else -6
    if net_cash is not None:
        score += 3 if net_cash > 0 else -2
    if debt is not None and debt >= 200:
        score -= 5
    elif debt is not None and debt <= 80:
        score += 2

    return bounded(score, 0, yield_cap)


def mobile_stability_score(row):
    confidence, _, _, _, _ = mobile_confidence(row)
    debt = clean_number(row.get("debt_ratio"))
    roe = clean_number(row.get("roe"))
    operating = clean_number(row.get("operating_growth"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    fcf = clean_number(row.get("free_cashflow"))
    net_cash = clean_number(row.get("net_cash"))
    score = 55

    score -= mobile_risk_penalty(row) * 2
    if debt is not None:
        if debt <= 80:
            score += 16
        elif debt <= 150:
            score += 8
        elif debt >= 200:
            score -= 16
    if roe is not None:
        if roe >= 10:
            score += 10
        elif roe < 5:
            score -= 10
    if operating is not None:
        score += 8 if operating >= 0 else -8
    if operating_cashflow is not None:
        score += 8 if operating_cashflow > 0 else -8
    if fcf is not None:
        score += 8 if fcf > 0 else -8
    if net_cash is not None:
        score += 10 if net_cash > 0 else -6
    if confidence < 60:
        score -= 8
    return bounded(score, 0, 100)


def mobile_lens_score(row, lens):
    risk_profile = mobile_structural_risk(row)
    if lens == "🎯 종합평가":
        score = mobile_candidate_score(row)
    elif lens == "🏢 좋은 회사":
        score = bounded((mobile_quality_score(row) / 35) * 70 + mobile_cash_generation_score(row) * 0.2 + mobile_stability_score(row) * 0.1)
    elif lens == "💰 저평가":
        score = bounded((mobile_cheapness_score(row) / 45) * 82 + mobile_quality_score(row) * 0.35)
    elif lens == "📈 성장":
        score = mobile_growth_score(row)
    elif lens == "💸 현금창출":
        score = bounded(mobile_cash_generation_score(row) * 0.7 + mobile_stability_score(row) * 0.3)
    elif lens == "🏦 배당":
        score = mobile_dividend_score(row)
    elif lens == "🔥 모멘텀":
        score = bounded((mobile_momentum_score(row) / 35) * 85 + mobile_timing_score(row) * 0.75)
    elif lens == "🛡 안정성":
        score = mobile_stability_score(row)
    else:
        score = mobile_candidate_score(row)
    if risk_profile["level"] == "hard":
        score = min(score, 35)
    return bounded(score, 0, 100)


def mobile_growth_reasons(row):
    reasons = []
    revenue = clean_number(row.get("revenue_growth"))
    operating = clean_number(row.get("operating_growth"))
    eps_growth = clean_number(row.get("eps_growth"))
    cagr = clean_number(row.get("cagr"))
    if revenue is not None and revenue >= 10:
        reasons.append("매출 성장 강함")
    if operating is not None and operating >= 15:
        reasons.append("영업이익 성장")
    if eps_growth is not None and eps_growth >= 15:
        reasons.append("EPS 성장")
    if cagr is not None and cagr >= 10:
        reasons.append("CAGR 양호")
    return reasons


def mobile_cash_reasons(row):
    reasons = []
    fcf = clean_number(row.get("free_cashflow"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    net_cash = clean_number(row.get("net_cash"))
    operating_margin = clean_number(row.get("operating_margin"))
    if fcf is not None and fcf > 0:
        reasons.append("FCF 플러스")
    if operating_cashflow is not None and operating_cashflow > 0:
        reasons.append("영업현금흐름 플러스")
    if net_cash is not None and net_cash > 0:
        reasons.append("순현금")
    if operating_margin is not None and operating_margin >= 10:
        reasons.append("영업이익률 양호")
    return reasons


def mobile_stability_reasons(row):
    reasons = []
    debt = clean_number(row.get("debt_ratio"))
    net_cash = clean_number(row.get("net_cash"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    fcf = clean_number(row.get("free_cashflow"))
    if debt is not None and debt <= 80:
        reasons.append("부채 부담 낮음")
    if net_cash is not None and net_cash > 0:
        reasons.append("순현금")
    if operating_cashflow is not None and operating_cashflow > 0:
        reasons.append("본업 현금 유입")
    if fcf is not None and fcf > 0:
        reasons.append("FCF 플러스")
    return reasons


def mobile_dividend_reasons(row):
    reasons = []
    dividend_yield = clean_number(row.get("dividend_yield"))
    payout_ratio = clean_number(row.get("payout_ratio"))
    dividend_growth = clean_number(row.get("dividend_growth_3y"))
    consecutive_years = clean_number(row.get("dividend_consecutive_years"))
    fcf = clean_number(row.get("free_cashflow"))
    net_cash = clean_number(row.get("net_cash"))

    if dividend_yield is not None and dividend_yield >= 2.5:
        reasons.append("배당수익률 매력")
    if payout_ratio is not None and 20 <= payout_ratio <= 70:
        reasons.append("배당성향 적정")
    if dividend_growth is not None and dividend_growth > 0:
        reasons.append("배당 성장")
    if consecutive_years is not None and consecutive_years >= 3:
        reasons.append("연속 배당")
    if fcf is not None and fcf > 0:
        reasons.append("FCF로 배당 여력")
    if net_cash is not None and net_cash > 0:
        reasons.append("순현금 여력")
    return reasons


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


def mobile_momentum_reasons(row):
    reasons = []
    tags = mobile_theme_tags(row)
    peak_diff = clean_number(row.get("peak_diff"))
    diff = clean_number(row.get("diff"))
    rsi = clean_number(row.get("rsi"))
    if tags:
        reasons.append("주도테마 " + "/".join(tags[:2]))
    if peak_diff is not None and peak_diff > -10:
        reasons.append("고점권 모멘텀")
    if diff is not None and diff >= 0:
        reasons.append("200일선 위")
    if rsi is not None and 50 <= rsi <= 70:
        reasons.append("수급 온기")
    return reasons


def mobile_reason_facts(row, reason_type):
    facts = []
    if reason_type == "cheap":
        per = clean_number(row.get("per"))
        hist_per = clean_number(row.get("hist_per_avg"))
        pbr = clean_number(row.get("pbr"))
        peak_diff = clean_number(row.get("peak_diff"))
        if per is not None and hist_per is not None:
            facts.append(f"PER: 현재 {per:.2f} / 과거 평균 PER {hist_per:.2f}")
        elif per is not None:
            facts.append(f"PER: 현재 {per:.2f}")
        if pbr is not None:
            facts.append(f"PBR: 현재 {pbr:.2f}")
        if peak_diff is not None:
            facts.append(f"최고점 대비: {peak_diff:.2f}%")
    elif reason_type == "good":
        roe = clean_number(row.get("roe"))
        revenue = clean_number(row.get("revenue_growth"))
        operating = clean_number(row.get("operating_growth"))
        debt = clean_number(row.get("debt_ratio"))
        if roe is not None:
            facts.append(f"ROE: 현재 {roe:.2f}%")
        if revenue is not None:
            facts.append(f"매출성장률: {revenue:.2f}%")
        if operating is not None:
            facts.append(f"영업이익성장률: {operating:.2f}%")
        if debt is not None:
            facts.append(f"부채비율: {debt:.2f}%")
    elif reason_type == "momentum":
        tags = mobile_theme_tags(row)
        diff = clean_number(row.get("diff"))
        peak_diff = clean_number(row.get("peak_diff"))
        rsi = clean_number(row.get("rsi"))
        foreign_supply = clean_number(row.get("foreign_supply"))
        if tags:
            facts.append(f"테마: {'/'.join(tags[:2])}")
        if diff is not None:
            facts.append(f"200일선 대비: {diff:.2f}%")
        if peak_diff is not None:
            facts.append(f"최고점 대비: {peak_diff:.2f}%")
        if rsi is not None:
            facts.append(f"RSI: {rsi:.2f}")
        if foreign_supply is not None:
            facts.append(f"외인/기관지분: {foreign_supply:.2f}%")
    return " · ".join(facts[:3]) if facts else "수치 근거 확인 필요"


def mobile_lens_reasons(row, lens):
    if lens == "🏢 좋은 회사":
        reasons = mobile_good_reasons(row) + mobile_cash_reasons(row)
    elif lens == "💰 저평가":
        reasons = mobile_cheap_reasons(row)
    elif lens == "📈 성장":
        reasons = mobile_growth_reasons(row)
    elif lens == "💸 현금창출":
        reasons = mobile_cash_reasons(row) or ["현금흐름 데이터 보강 필요"]
    elif lens == "🏦 배당":
        reasons = mobile_dividend_reasons(row) or ["배당 데이터 보강 필요"]
    elif lens == "🔥 모멘텀":
        reasons = mobile_momentum_reasons(row)
    elif lens == "🛡 안정성":
        reasons = mobile_stability_reasons(row)
    else:
        reasons = mobile_good_reasons(row) + mobile_cheap_reasons(row) + mobile_momentum_reasons(row)
    return reasons[:3] or ["근거 확인 필요"]


def mobile_warning_reasons(row):
    warnings = []
    risk_profile = mobile_structural_risk(row)
    debt = clean_number(row.get("debt_ratio"))
    roe = clean_number(row.get("roe"))
    eps_growth = clean_number(row.get("eps_growth"))
    operating = clean_number(row.get("operating_growth"))
    rsi = clean_number(row.get("rsi"))
    confidence, _, missing, _, _ = mobile_confidence(row)
    if risk_profile["warning"]:
        warnings.append(risk_profile["label"])
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


def mobile_watch_reasons(row):
    reasons = []
    per = clean_number(row.get("per"))
    pbr = clean_number(row.get("pbr"))
    rsi = clean_number(row.get("rsi"))
    peak_diff = clean_number(row.get("peak_diff"))
    cheapness = mobile_cheapness_score(row)
    if cheapness < 18:
        reasons.append("저렴함 점수 낮음")
    if per is not None and per >= 20:
        reasons.append(f"PER {per:.1f}")
    if pbr is not None and pbr >= 3:
        reasons.append(f"PBR {pbr:.1f}")
    if rsi is not None and rsi >= 70:
        reasons.append(f"RSI {rsi:.0f} 과열")
    if peak_diff is not None and peak_diff > -10:
        reasons.append(f"고점대비 {peak_diff:.1f}%")
    if not reasons:
        reasons.append("가격 부담 또는 타이밍 확인")
    return reasons[:3]


def metric_fact(row, key, label, suffix="", decimals=2):
    value = clean_number(row.get(key))
    if value is None:
        return f"{label} N/A"
    if decimals == 0:
        return f"{label} {value:,.0f}{suffix}"
    return f"{label} {value:,.{decimals}f}{suffix}"


def cashflow_fact(row, key, label):
    value = clean_number(row.get(key))
    if value is None:
        return f"{label} 확인 필요"
    return f"{label} {format_cashflow_amount(value, row)}"


def join_facts(*facts):
    clean = [fact for fact in facts if fact and "N/A" not in fact]
    return " · ".join(clean[:2]) if clean else "수치 근거 확인 필요"


def signal_fact_lines(summary):
    parts = [part.strip() for part in str(summary or "").split(" · ") if part and part.strip()]
    if not parts:
        parts = ["수치 근거 확인 필요"]
    while len(parts) < 2:
        parts.append("보조 지표 미확인")
    return parts[:2]


def signal_item(title, value, tone, summary, details):
    return {
        "title": title,
        "value": value,
        "tone": tone,
        "summary": summary,
        "details": details[:4],
    }


def mobile_signal_cards(row, lens="🎯 종합평가"):
    quality = mobile_quality_score(row)
    cheapness = mobile_cheapness_score(row)
    growth = mobile_growth_score(row)
    cash_generation = mobile_cash_generation_score(row)
    dividend = mobile_dividend_score(row)
    momentum = mobile_momentum_score(row)
    stability = mobile_stability_score(row)
    risk = mobile_risk_penalty(row)
    warnings = mobile_warning_reasons(row)
    debt = clean_number(row.get("debt_ratio"))
    fcf = clean_number(row.get("free_cashflow"))
    operating_cashflow = clean_number(row.get("operating_cashflow"))
    dividend_yield = clean_number(row.get("dividend_yield"))
    payout_ratio = clean_number(row.get("payout_ratio"))
    rsi = clean_number(row.get("rsi"))

    if quality >= 26:
        quality_text, quality_tone = "좋음", "good"
    elif quality >= 14:
        quality_text, quality_tone = "보통", "watch"
    else:
        quality_text, quality_tone = "확인 필요", "risk"

    if cheapness >= 28:
        price_text, price_tone = "저렴함", "good"
    elif cheapness >= 18:
        price_text, price_tone = "중립", "watch"
    else:
        price_text, price_tone = "아직 비쌈", "risk"

    if risk <= 8 and not warnings:
        caution_text, caution_tone = "특이사항 적음", "good"
    elif risk <= 18:
        caution_text, caution_tone = "사이클 확인 필요", "watch"
    else:
        caution_text, caution_tone = "주의 필요", "risk"

    quality_item = signal_item(
        "좋은 회사인가",
        quality_text,
        quality_tone,
        join_facts(metric_fact(row, "roe", "ROE", "%"), metric_fact(row, "operating_growth", "영업익", "%")),
        [
            f"ROE: {format_metric(row.get('roe'), '%')} - 자본 효율 기준입니다.",
            f"매출성장률: {format_metric(row.get('revenue_growth'), '%')} - 외형 성장 여부입니다.",
            f"영업이익성장률: {format_metric(row.get('operating_growth'), '%')} - 이익 개선 여부입니다.",
            f"부채비율: {format_metric(row.get('debt_ratio'), '%')} - 재무 부담 확인입니다.",
        ],
    )
    cheap_item = signal_item(
        "지금 저렴한가",
        price_text,
        price_tone,
        join_facts(metric_fact(row, "per", "PER"), metric_fact(row, "peak_diff", "고점대비", "%")),
        [
            f"PER: {format_metric(row.get('per'))} - 이익 대비 가격입니다.",
            f"PBR: {format_metric(row.get('pbr'))} - 자산 대비 가격입니다.",
            f"최고점대비: {format_metric(row.get('peak_diff'), '%')} - 가격 위치입니다.",
            f"업종PER괴리: {format_metric(row.get('peer_per_gap'), '%')} - 업종 대비 가격입니다.",
        ],
    )
    caution_item = signal_item(
        "주의할 점",
        caution_text,
        caution_tone,
        " · ".join(warnings[:2]) if warnings else join_facts(metric_fact(row, "debt_ratio", "부채", "%"), metric_fact(row, "rsi", "RSI")),
        [
            f"부채비율: {format_metric(row.get('debt_ratio'), '%')} - 높으면 재무 부담입니다.",
            f"RSI: {format_metric(row.get('rsi'))} - 단기 과열 여부입니다.",
            f"FCF: {format_metric(row.get('free_cashflow'), '억')} - 마이너스면 현금 유출 부담입니다.",
            f"확인사항: {' · '.join(warnings[:3]) if warnings else '강한 경고는 적습니다.'}",
        ],
    )

    if lens == "🏢 좋은 회사":
        return [
            signal_item("이익을 잘 내나", quality_text, quality_tone, join_facts(metric_fact(row, "roe", "ROE", "%"), metric_fact(row, "operating_margin", "영업률", "%")), quality_item["details"]),
            signal_item("성장도 있나", "좋음" if growth >= 65 else "보통" if growth >= 40 else "확인 필요", "good" if growth >= 65 else "watch" if growth >= 40 else "risk", join_facts(metric_fact(row, "revenue_growth", "매출", "%"), metric_fact(row, "operating_growth", "영업익", "%")), [
                f"매출성장률: {format_metric(row.get('revenue_growth'), '%')}",
                f"영업이익성장률: {format_metric(row.get('operating_growth'), '%')}",
                f"EPS성장률: {format_metric(row.get('eps_growth'), '%')}",
            ]),
            signal_item("재무가 버티나", "튼튼" if stability >= 70 else "보통" if stability >= 45 else "주의", "good" if stability >= 70 else "watch" if stability >= 45 else "risk", join_facts(metric_fact(row, "debt_ratio", "부채", "%"), metric_fact(row, "net_cash", "순현금", "억")), caution_item["details"]),
        ]
    if lens == "💰 저평가":
        return [
            signal_item("가격이 싼가", price_text, price_tone, cheap_item["summary"], cheap_item["details"]),
            signal_item("업종보다 싼가", "저렴" if clean_number(row.get("peer_per_gap")) is not None and clean_number(row.get("peer_per_gap")) <= -15 else "중립", "good" if clean_number(row.get("peer_per_gap")) is not None and clean_number(row.get("peer_per_gap")) <= -15 else "watch", join_facts(metric_fact(row, "peer_per_gap", "PER괴리", "%"), metric_fact(row, "peer_pbr_gap", "PBR괴리", "%")), [
                f"업종 평균 PER: {format_metric(row.get('peer_per_avg'))}",
                f"업종 평균 PBR: {format_metric(row.get('peer_pbr_avg'))}",
                f"업종 내 표본수: {format_metric(row.get('peer_group_count'), decimals=0)}",
            ]),
            signal_item("싸 보이는 이유는", caution_text, caution_tone, " · ".join(warnings[:2]) if warnings else "특이 리스크 적음", caution_item["details"]),
        ]
    if lens == "📈 성장":
        return [
            signal_item("매출이 크나", "성장" if clean_number(row.get("revenue_growth")) is not None and clean_number(row.get("revenue_growth")) > 0 else "확인 필요", "good" if clean_number(row.get("revenue_growth")) is not None and clean_number(row.get("revenue_growth")) >= 10 else "watch", metric_fact(row, "revenue_growth", "매출성장", "%"), [f"매출성장률: {format_metric(row.get('revenue_growth'), '%')}"]),
            signal_item("이익도 따라오나", "성장" if clean_number(row.get("operating_growth")) is not None and clean_number(row.get("operating_growth")) > 0 else "확인 필요", "good" if clean_number(row.get("operating_growth")) is not None and clean_number(row.get("operating_growth")) >= 15 else "watch", metric_fact(row, "operating_growth", "영업익", "%"), [f"영업이익성장률: {format_metric(row.get('operating_growth'), '%')}", f"EPS성장률: {format_metric(row.get('eps_growth'), '%')}"]),
            signal_item("지속성이 있나", "양호" if growth >= 65 else "확인", "good" if growth >= 65 else "watch", join_facts(metric_fact(row, "cagr", "CAGR", "%"), metric_fact(row, "roe", "ROE", "%")), [f"CAGR: {format_metric(row.get('cagr'), '%')}", f"ROE: {format_metric(row.get('roe'), '%')}"]),
        ]
    if lens == "💸 현금창출":
        return [
            signal_item("영업현금은", "플러스" if operating_cashflow is not None and operating_cashflow > 0 else "확인 필요", "good" if operating_cashflow is not None and operating_cashflow > 0 else "risk", cashflow_fact(row, "operating_cashflow", "영업현금"), [
                f"영업현금흐름: {format_cashflow_amount(row.get('operating_cashflow'), row)}",
                "본업에서 실제 현금이 들어오는지 보는 핵심 지표입니다.",
            ]),
            signal_item("FCF는", "남음" if fcf is not None and fcf > 0 else "부족", "good" if fcf is not None and fcf > 0 else "risk", cashflow_fact(row, "free_cashflow", "FCF"), [
                f"FCF: {format_cashflow_amount(row.get('free_cashflow'), row)}",
                "투자 후에도 남는 현금입니다.",
            ]),
            signal_item("현금여력은", "충분" if clean_number(row.get("net_cash")) is not None and clean_number(row.get("net_cash")) > 0 else "확인", "good" if clean_number(row.get("net_cash")) is not None and clean_number(row.get("net_cash")) > 0 else "watch", join_facts(cashflow_fact(row, "net_cash", "순현금"), metric_fact(row, "debt_ratio", "부채", "%")), [
                f"순현금: {format_cashflow_amount(row.get('net_cash'), row)}",
                f"부채비율: {format_metric(row.get('debt_ratio'), '%')}",
                "현금창출을 부채 부담이 갉아먹는지 확인합니다.",
            ]),
        ]
    if lens == "🏦 배당":
        return [
            signal_item("배당 매력은", "높음" if dividend_yield is not None and dividend_yield >= 2.5 else "보통" if dividend_yield is not None and dividend_yield > 0 else "확인 필요", "good" if dividend_yield is not None and dividend_yield >= 2.5 else "watch" if dividend_yield is not None and dividend_yield > 0 else "risk", join_facts(metric_fact(row, "dividend_yield", "연배당률", "%"), metric_fact(row, "dividend_growth_3y", "성장률", "%")), [
                f"연배당률: {format_metric(row.get('dividend_yield'), '%')}",
                f"배당성장률: {format_metric(row.get('dividend_growth_3y'), '%')}",
                f"데이터출처: {row.get('dividend_source') or row.get('dividend_history_source') or 'N/A'}",
            ]),
            signal_item("지속성은", "양호" if dividend >= 70 else "보통" if dividend >= 45 else "확인", "good" if dividend >= 70 else "watch" if dividend >= 45 else "risk", join_facts(metric_fact(row, "dividend_consecutive_years", "연속", "년"), metric_fact(row, "payout_ratio", "성향", "%")), [
                f"연속배당연수: {format_metric(row.get('dividend_consecutive_years'), '년', decimals=0)}",
                f"배당성향: {format_metric(row.get('payout_ratio'), '%')}",
                f"배당삭감여부: {'있음' if str(row.get('dividend_cut_flag')).strip().lower() in {'true', '1', 'yes'} else '확인 안 됨/없음'}",
            ]),
            signal_item("배당 여력은", "양호" if fcf is not None and fcf > 0 else "확인", "good" if fcf is not None and fcf > 0 else "watch", join_facts(cashflow_fact(row, "free_cashflow", "FCF"), cashflow_fact(row, "operating_cashflow", "영업현금")), [
                f"FCF: {format_cashflow_amount(row.get('free_cashflow'), row)}",
                f"영업현금흐름: {format_cashflow_amount(row.get('operating_cashflow'), row)}",
                f"순현금: {format_cashflow_amount(row.get('net_cash'), row)}",
            ]),
        ]
    if lens == "🔥 모멘텀":
        return [
            signal_item("추세가 살아있나", "강함" if momentum >= 24 else "보통", "good" if momentum >= 24 else "watch", join_facts(metric_fact(row, "diff", "200일", "%"), metric_fact(row, "peak_diff", "고점대비", "%")), [f"200일괴리율: {format_metric(row.get('diff'), '%')}", f"최고점대비: {format_metric(row.get('peak_diff'), '%')}"]),
            signal_item("과열은 아닌가", "과열" if rsi is not None and rsi >= 70 else "중립", "risk" if rsi is not None and rsi >= 70 else "good", metric_fact(row, "rsi", "RSI"), [f"RSI: {format_metric(row.get('rsi'))}", "70 이상이면 단기 과열로 봅니다."]),
            signal_item("주도 테마인가", "확인" if not mobile_theme_tags(row) else "테마 있음", "watch" if not mobile_theme_tags(row) else "good", " · ".join(mobile_theme_tags(row)[:2]) if mobile_theme_tags(row) else "테마 확인 필요", [f"테마: {'/'.join(mobile_theme_tags(row)[:3]) if mobile_theme_tags(row) else '확인 필요'}"]),
        ]
    if lens == "🛡 안정성":
        return [
            signal_item("빚 부담은 낮나", "낮음" if debt is not None and debt <= 80 else "확인" if debt is not None and debt < 200 else "높음", "good" if debt is not None and debt <= 80 else "watch" if debt is not None and debt < 200 else "risk", metric_fact(row, "debt_ratio", "부채", "%"), [f"부채비율: {format_metric(row.get('debt_ratio'), '%')}"]),
            signal_item("현금 여력은", "양호" if clean_number(row.get("net_cash")) is not None and clean_number(row.get("net_cash")) > 0 else "확인", "good" if clean_number(row.get("net_cash")) is not None and clean_number(row.get("net_cash")) > 0 else "watch", join_facts(metric_fact(row, "cash", "현금", "억"), metric_fact(row, "net_cash", "순현금", "억")), [f"현금: {format_metric(row.get('cash'), '억')}", f"순현금: {format_metric(row.get('net_cash'), '억')}"]),
            signal_item("이익 변동은", "안정" if risk <= 8 else "확인", "good" if risk <= 8 else "watch", join_facts(metric_fact(row, "roe", "ROE", "%"), metric_fact(row, "operating_growth", "영업익", "%")), quality_item["details"]),
        ]
    return [quality_item, cheap_item, caution_item]


def mobile_change_text(row):
    after_change = clean_number(row.get("after_market_change_pct"))
    peak_diff = clean_number(row.get("peak_diff"))
    if after_change is not None:
        return f"{after_change:+.2f}%"
    if peak_diff is not None:
        return f"최고점 대비 {peak_diff:.1f}%"
    return "등락 N/A"


def split_market_summary(summary):
    summary = str(summary or "")
    headline = summary
    positive = ""
    negative = ""
    if "우호 요인:" in summary:
        headline, positive_part = summary.split("우호 요인:", 1)
        if "부담 요인:" in positive_part:
            positive, negative = positive_part.split("부담 요인:", 1)
        else:
            positive = positive_part
    elif "부담 요인:" in summary:
        headline, negative = summary.split("부담 요인:", 1)
    return headline.strip(" ."), positive.strip(" ."), negative.strip(" .")


def render_mobile_market_notes(market_data):
    score = clean_number(market_data.get("market_score"))
    state = market_data.get("score_state") or market_data.get("market_state") or "확인 중"
    summary = market_data.get("summary", "시장환경 요약을 확인 중입니다.")
    score_text = f"{score:.1f}점" if score is not None else "N/A"
    st.markdown(
        f"""
        <div class="mobile-market-card">
            <div class="mobile-market-top">
                <b>시장환경 한눈에 보기</b>
                <span>자세히 보기 ›</span>
            </div>
            <div class="mobile-market-state">상태: <b>{escape_html(state)}</b></div>
            <div class="mobile-market-score">위험선호도 <b>{score_text}</b></div>
            <div class="mobile-market-summary">{escape_html(summary)}</div>
            <div class="mobile-market-tags">
                <span>정량 확인</span><span>정성 변수 별도</span><span>캐시 기준</span><span>뉴스 별도 확인</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
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


def render_mobile_candidate_card(row, list_index, is_kr, lens="🎯 종합평가", secondary_analysis=None):
    name = escape_html(row.get("name", row.get("symbol", "이름 없음")))
    symbol = escape_html(row.get("symbol", ""))
    sector = escape_html(row.get("sector") or row.get("industry") or "업종 확인")
    price = escape_html(format_price(row.get("price"), is_kr))
    change_text = escape_html(mobile_change_text(row))
    grade = escape_html(mobile_grade_label(row))
    lens_meta = MOBILE_LENS_META.get(lens, MOBILE_LENS_META["🎯 종합평가"])
    candidate_score = mobile_lens_score(row, lens)
    confidence_score, confidence_label, _, _, _ = mobile_confidence(row)
    reason_chips = mobile_lens_reasons(row, lens)
    chip_html = "".join([f"<span>{escape_html(chip)}</span>" for chip in reason_chips])
    secondary_html = ""
    if secondary_analysis and secondary_analysis.get("chips"):
        secondary_chips = "".join([f"<span>{escape_html(chip)}</span>" for chip in secondary_analysis.get("chips", [])])
        secondary_html = (
            f"<div class='mobile-secondary-row'>{secondary_chips}</div>"
            f"<div class='mobile-secondary-sentence'>{escape_html(secondary_analysis.get('sentence', ''))}</div>"
        )
    signal_html = ""
    for signal in mobile_signal_cards(row, lens):
        fact_lines = signal_fact_lines(signal["summary"])
        signal_html += (
            f"<div class='mobile-signal-card {escape_html(signal['tone'])}'>"
            f"<small>{escape_html(signal['title'])}</small>"
            f"<b>{escape_html(signal['value'])}</b>"
            f"<em>{escape_html(fact_lines[0])}</em>"
            f"<em>{escape_html(fact_lines[1])}</em>"
            f"</div>"
        )
    rank_tone = "hot" if list_index <= 3 else "base"

    st.markdown(
        f"""
        <div class="mobile-candidate-card">
            <div class="mobile-candidate-head">
                <div class="mobile-candidate-name">
                    <span class="mobile-rank-badge {rank_tone}">{list_index}</span>
                    <div><b>{name}</b><small>{symbol} · {sector}</small></div>
                </div>
                <span class="mobile-grade-pill">{grade}</span>
            </div>
            <div class="mobile-price-row">
                <b>{price}</b><span>{change_text}</span>
            </div>
            <div class="mobile-signal-grid">{signal_html}</div>
            <div class="mobile-score-row">
                <span>{escape_html(lens_meta["score_label"])} {candidate_score:.0f}%</span>
                <span>근거 신뢰도 <b>{escape_html(confidence_label)}</b> · {confidence_score}%</span>
            </div>
            {secondary_html}
            <div class="mobile-chip-row">{chip_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mobile_metric(label, value_text, explanation):
    st.markdown(
        f"""
        <div class="mobile-metric-row">
            <div class="mobile-metric-head"><b>{label}</b><span>{value_text}</span></div>
            <div class="mobile-metric-explain">{explanation}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mobile_evidence_panel(row, lens="🎯 종합평가"):
    signals = mobile_signal_cards(row, lens)
    panel_html = ""
    for signal in signals:
        details = "".join([f"<li>{escape_html(detail)}</li>" for detail in signal["details"]])
        panel_html += (
            f"<div class='mobile-signal-evidence-card {escape_html(signal['tone'])}'>"
            f"<div class='mobile-signal-evidence-head'>"
            f"<span>{escape_html(signal['title'])}</span>"
            f"<b>{escape_html(signal['value'])}</b>"
            f"</div>"
            f"<p>{escape_html(signal['summary'])}</p>"
            f"<ul>{details}</ul>"
            f"</div>"
        )
    st.markdown(
        f"""
        <div class="mobile-signal-evidence-panel">
            {panel_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def mobile_detail_section_tone(title):
    if title.startswith("1."):
        return "judgment"
    if title.startswith("2."):
        return "positive"
    if title.startswith("3."):
        return "caution"
    if title in ["기업 품질", "성장성"]:
        return "positive"
    if title in ["가격", "차트 대신 보는 핵심 위치"]:
        return "judgment"
    if title in ["재무", "수급"]:
        return "stability"
    if title == "리스크":
        return "caution"
    if title == "기업 정보":
        return "info"
    return "neutral"


def render_mobile_section(title, metrics):
    section_tone = mobile_detail_section_tone(title)
    if not metrics:
        rows_html = "<div class='mobile-detail-section-empty'>확인 가능한 데이터가 아직 부족합니다.</div>"
    else:
        rows_html = ""
        for label, value_text, explanation in metrics:
            rows_html += (
                "<div class='mobile-detail-section-row'>"
                f"<div class='mobile-detail-section-head'><b>{escape_html(label)}</b><span>{escape_html(value_text)}</span></div>"
                f"<div class='mobile-detail-section-body'>{escape_html(explanation)}</div>"
                "</div>"
            )
    st.markdown(
        f"""
        <div class="mobile-detail-section-card {section_tone}">
            <div class="mobile-detail-section-title">{escape_html(title)}</div>
            {rows_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_mobile_lens_panel(lens):
    lens_meta = MOBILE_LENS_META.get(lens, MOBILE_LENS_META["🎯 종합평가"])
    st.markdown(
        f"""
        <div class="mobile-lens-card">
            <div class="mobile-lens-title">🎯 투자 렌즈</div>
            <div class="mobile-lens-current">{escape_html(lens)}</div>
            <div class="mobile-lens-description">{escape_html(lens_meta["description"])}</div>
            <div class="mobile-lens-note">같은 회사도 어떤 관점으로 보느냐에 따라 순위가 달라집니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("주요 기준 보기", expanded=False):
        for label, explanation in lens_meta["criteria"]:
            st.markdown(f"**{label}** - {explanation}")


def render_mobile_stock_card(row, is_kr, show_header=True, lens="🎯 종합평가"):
    rank = row.get("rank", "")
    name = row.get("name", row.get("symbol", "이름 없음"))
    symbol = row.get("symbol", "")
    score = format_metric(row.get("score"), decimals=0)
    grade = row.get("grade", "N/A")
    price = format_price(row.get("price"), is_kr)
    cap = format_cap(row.get("market_cap"), is_kr)
    lens_meta = MOBILE_LENS_META.get(lens, MOBILE_LENS_META["🎯 종합평가"])
    candidate_score = mobile_lens_score(row, lens)
    confidence_score, confidence_label, confidence_missing, available_count, total_count = mobile_confidence(row)
    risk_profile = mobile_structural_risk(row)
    cheap_reasons = mobile_cheap_reasons(row) or ["저렴함 근거 확인 필요"]
    good_reasons = mobile_good_reasons(row) or ["품질 근거 확인 필요"]
    momentum_reasons = mobile_momentum_reasons(row)
    cheap_facts = mobile_reason_facts(row, "cheap")
    good_facts = mobile_reason_facts(row, "good")
    momentum_facts = mobile_reason_facts(row, "momentum")
    warning_reasons = mobile_warning_reasons(row) or ["정치·규제·뉴스 변수 별도 확인"]
    signal_cards = mobile_signal_cards(row, lens)
    signal_labels = {signal["title"]: signal["value"] for signal in signal_cards}
    signal_html = ""
    for signal in signal_cards:
        fact_lines = signal_fact_lines(signal["summary"])
        signal_html += (
            f"<div class='mobile-detail-signal {escape_html(signal['tone'])}'>"
            f"<small>{escape_html(signal['title'])}</small>"
            f"<b>{escape_html(signal['value'])}</b>"
            f"<em>{escape_html(fact_lines[0])}</em>"
            f"<em>{escape_html(fact_lines[1])}</em>"
            f"</div>"
        )

    if show_header:
        st.markdown(
            f"""
            <div id="mobile-detail-top"></div>
            <div class="mobile-detail-hero">
                <div class="mobile-detail-top">
                    <div>
                        <div class="mobile-stock-title">{escape_html(name)}</div>
                        <div class="mobile-stock-rank">시장순위 #{escape_html(rank)} · {escape_html(symbol)} · {escape_html(row.get("sector") or row.get("industry") or "업종 확인")}</div>
                    </div>
                    <span class="mobile-grade-pill">{escape_html(mobile_grade_label(row))}</span>
                </div>
                <div class="mobile-detail-price"><b>{escape_html(price)}</b><span>{escape_html(mobile_change_text(row))}</span></div>
                <div class="mobile-detail-signals">{signal_html}</div>
                <div class="mobile-detail-score">
                    <span>{escape_html(lens_meta["score_label"])} {candidate_score:.0f}%</span>
                    <span>근거 신뢰도 <b>{escape_html(confidence_label)}</b> · {confidence_score}%</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="mobile-inline-detail-anchor"></div>', unsafe_allow_html=True)

    detail_tab_options = ["요약", "상세 수치", "차트", "기업 정보"]
    if st.session_state.mobile_detail_tab not in detail_tab_options:
        st.session_state.mobile_detail_tab = "요약"
    selected_detail_tab = st.session_state.mobile_detail_tab

    if selected_detail_tab == "요약":
        render_mobile_section("1. 후보 판단", [
            (signal["title"], signal_labels.get(signal["title"], "확인 필요"), signal["summary"])
            for signal in signal_cards
        ])
        render_mobile_section("2. 핵심 근거", [
            ("좋은 이유", " · ".join(good_reasons[:3]) if good_reasons else "추가 확인", "성장성, 수익성, 재무 안정성 중 확인된 강점입니다."),
            ("싼 이유", " · ".join(cheap_reasons[:3]) if cheap_reasons else "추가 확인", "가격 매력은 수치 탭에서 구체적으로 확인할 수 있습니다."),
            ("시장환경", " · ".join(momentum_reasons[:3]) if momentum_reasons else "추가 확인", "시장 방향과 업종 흐름을 함께 반영한 판단입니다."),
        ])
        render_mobile_section("3. 확인 필요", [
            ("후보 판단", "확인 필요", "FCF와 영업현금흐름은 데이터가 있으면 PC의 부족 데이터 탭에서 수치와 해석까지 확인할 수 있습니다."),
            ("주의", " · ".join(warning_reasons[:3]), "정치·규제·뉴스 변수는 별도 확인이 필요합니다."),
            ("분석 신뢰도", f"{confidence_score}% · {available_count}/{total_count}개 확인", f"부족한 부분: {confidence_missing}"),
        ])
    elif selected_detail_tab == "상세 수치":
        st.dataframe(
            pd.DataFrame([
                {"항목": label, "점수": points, "기준": reason}
                for label, points, reason in mobile_score_breakdown(row)
            ]),
            width="stretch",
            hide_index=True,
        )
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
        render_mobile_section("리스크", [
            ("데이터기준일", str(row.get("data_date", "N/A")), metric_explanation("데이터기준일", row, row.get("data_date", "N/A"))),
            ("가격기준", str(row.get("price_basis", "N/A")), metric_explanation("가격기준", row, row.get("price_basis", "N/A"))),
            ("구조 리스크", risk_profile["label"] or "특이사항 없음", risk_profile["warning"] or "현재 규칙상 강한 구조 리스크로 분류되지는 않았습니다."),
        ])
    elif selected_detail_tab == "차트":
        render_mobile_section("차트 대신 보는 핵심 위치", [
            ("현재 가격", price, "모바일에서는 차트보다 위치 판단을 먼저 보여줍니다."),
            ("200일괴리율", format_metric(row.get("diff"), "%"), metric_explanation("200일괴리율", row, row.get("diff"))),
            ("최고점대비", format_metric(row.get("peak_diff"), "%"), metric_explanation("최고점대비", row, row.get("peak_diff"))),
            ("RSI", format_metric(row.get("rsi")), metric_explanation("RSI", row, row.get("rsi"))),
        ])
    else:
        render_mobile_section("기업 정보", [
            ("종목코드", str(symbol), "선택한 종목의 코드입니다."),
            ("시장순위", f"#{rank}", "시가총액 기준 후보군 내 위치입니다."),
            ("시가총액", cap, "기업 규모를 보는 기준입니다."),
            ("등급", str(grade), "기존 스크리너의 종합 등급입니다."),
            ("종합점수", f"{score}점", "기존 PC 표와 같은 종합점수입니다."),
        ])


def handle_market_change():
    load_cached_market_data()


def handle_market_choice_change():
    st.session_state.selected_market = MARKET_LABEL_TO_VALUE[st.session_state.market_choice]
    st.session_state.show_large_table = False
    load_cached_market_data()


def select_market_choice(label):
    if label == st.session_state.market_choice:
        return
    st.session_state.market_choice = label
    handle_market_choice_change()
    st.session_state.mobile_visible_count = 5
    st.session_state.mobile_selected_symbol = None
    st.session_state.mobile_evidence_symbol = None
    st.rerun()


def select_table_view_mode(label):
    if label == st.session_state.table_view_mode:
        return
    st.session_state.table_view_mode = label
    st.session_state.show_large_table = False
    st.rerun()


def select_mobile_lens(lens):
    if lens == st.session_state.mobile_investment_lens:
        return
    st.session_state.mobile_investment_lens = lens
    st.session_state.last_mobile_investment_lens = lens
    st.session_state.mobile_visible_count = 5
    st.session_state.mobile_selected_symbol = None
    st.session_state.mobile_evidence_symbol = None
    st.rerun()


def select_mobile_secondary_lens(lens):
    st.session_state.mobile_secondary_lens = None if lens == st.session_state.mobile_secondary_lens else lens
    st.session_state.mobile_visible_count = 5
    st.session_state.mobile_selected_symbol = None
    st.session_state.mobile_evidence_symbol = None
    st.rerun()


def render_choice_buttons(options, current_value, key_prefix, columns, on_select, label_fn=lambda value: value):
    with st.container(key=f"{key_prefix}_wrap"):
        cols = st.columns(columns, gap="small")
        for idx, option in enumerate(options):
            is_active = option == current_value
            button_key = f"{key_prefix}_{'active_' if is_active else ''}{idx}"
            with cols[idx % columns]:
                if st.button(label_fn(option), key=button_key, width="stretch"):
                    on_select(option)


def render_top_choice_panel():
    with st.container(key="top_choice_panel"):
        st.markdown('<div class="top-choice-eyebrow">분석 조건 선택</div>', unsafe_allow_html=True)
        st.markdown('<div class="top-choice-label">시장</div>', unsafe_allow_html=True)
        render_choice_buttons(
            list(MARKET_LABEL_TO_VALUE.keys()),
            st.session_state.market_choice,
            "top_market_choice",
            3,
            select_market_choice,
        )

        st.markdown('<div class="top-choice-label">보기 방식</div>', unsafe_allow_html=True)
        render_choice_buttons(
            ["모바일 보기", "PC 보기"],
            st.session_state.table_view_mode,
            "top_view_choice",
            2,
            select_table_view_mode,
        )

        st.markdown('<div class="top-choice-label">투자 렌즈</div>', unsafe_allow_html=True)
        render_choice_buttons(
            MOBILE_LENS_OPTIONS,
            st.session_state.mobile_investment_lens,
            "top_lens_choice",
            len(MOBILE_LENS_OPTIONS),
            select_mobile_lens,
            label_fn=lambda lens: MOBILE_LENS_META.get(lens, {}).get("short", lens),
        )

        st.markdown('<div class="top-choice-label">투자 렌즈 Ⅱ</div>', unsafe_allow_html=True)
        render_choice_buttons(
            MOBILE_SECONDARY_LENS_OPTIONS,
            st.session_state.mobile_secondary_lens,
            "top_second_lens_choice",
            len(MOBILE_SECONDARY_LENS_OPTIONS),
            select_mobile_secondary_lens,
            label_fn=lambda lens: MOBILE_SECONDARY_LENS_META.get(lens, {}).get("short", lens),
        )
        secondary_lens = st.session_state.mobile_secondary_lens
        if secondary_lens:
            secondary_description = MOBILE_SECONDARY_LENS_META.get(secondary_lens, {}).get("description", "")
            st.markdown(
                f'<div class="top-choice-help"><b>{escape_html(secondary_lens)}</b> · {escape_html(secondary_description)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="top-choice-help">선택하지 않으면 투자 렌즈 Ⅰ 기준으로 그대로 봅니다.</div>',
                unsafe_allow_html=True,
            )


def render_market_environment_panel():
    st.subheader("2단계: 시장환경 점검")
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
            headline, positive_summary, negative_summary = split_market_summary(market_data.get("summary", ""))
            summary_lines = [f"**상태:** {state_color}"]
            if headline:
                summary_lines.append(f"**요약:** {headline}")
            if positive_summary:
                summary_lines.append(f"**우호 요인:** {positive_summary}")
            if negative_summary:
                summary_lines.append(f"**부담 요인:** {negative_summary}")
            summary_lines.append(f"**시장환경 수집시각:** `{source_text}`")
            st.info(
                "  \n".join(summary_lines)
            )
            st.markdown(
                """
                <div class="market-score-guide">
                    <span>80+ 매우우호</span><span>65+ 우호</span><b>50 평균</b><span>35- 부담</span><span>20- 매우부담</span>
                </div>
                """,
                unsafe_allow_html=True,
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
            influence = 0
            if total_weight:
                influence = round(float(weight) / float(total_weight) * 100)
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
                "영향도": f"{influence:.0f}%",
                "의미": row.get("meaning") or market_meaning(label, score),
            }

        evidence_rows = market_data.get("evidence_rows") or market_data.get("rows") or []
        if evidence_rows:
            evidence_df = pd.DataFrame([evidence_display_row(row) for row in evidence_rows])
            driver_df = evidence_df.copy()
            driver_df["_abs_impact"] = driver_df["점수영향"].astype(str).str.replace("+", "", regex=False).str.replace("점", "", regex=False)
            driver_df["_abs_impact"] = pd.to_numeric(driver_df["_abs_impact"], errors="coerce").abs().fillna(0)
            top_drivers = driver_df.sort_values("_abs_impact", ascending=False).head(4)
            driver_html = "".join(
                [
                    f"<span><b>{escape_html(item['항목'])}</b> {escape_html(item['점수영향'])}점 · 영향도 {escape_html(item['영향도'])}</span>"
                    for _, item in top_drivers.iterrows()
                ]
            )
            st.markdown(
                f"""
                <div class="market-driver-strip">
                    <strong>점수 영향 상위</strong>
                    {driver_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

            def color_market_evidence(val):
                text = str(val)
                if text in ["우호", "매우 우호"] or text.startswith("+"):
                    return "color: #FF4B4B; font-weight: bold;"
                if text in ["부담", "매우 부담", "비우호"] or text.startswith("-"):
                    return "color: #2563EB; font-weight: bold;"
                return "color: #64748B;"

            st.caption("시장환경 근거표")
            if st.session_state.table_view_mode == "모바일 보기":
                evidence_cards_html = ""
                for _, item in evidence_df.iterrows():
                    impact_text = str(item.get("점수영향", "-"))
                    impact_class = "positive" if impact_text.startswith("+") else "negative" if impact_text.startswith("-") else "neutral"
                    evidence_cards_html += f"""
                    <div class="mobile-evidence-card">
                        <div class="mobile-evidence-line mobile-evidence-line-main">
                            <b>{escape_html(item.get("항목", "시장환경"))}</b>
                            <span>{escape_html(item.get("의미", ""))}</span>
                        </div>
                        <div class="mobile-evidence-line mobile-evidence-line-data">
                            <strong>{escape_html(item.get("평가", "-"))} <span class="{impact_class}">{escape_html(impact_text)}점</span></strong>
                            <em>영향도 {escape_html(item.get("영향도", "-"))}</em>
                            <em>현재 {escape_html(item.get("현재값", "-"))}</em>
                            <em>20일 {escape_html(item.get("20일", "-"))}</em>
                            <em>60일 {escape_html(item.get("60일", "-"))}</em>
                        </div>
                    </div>
                    """
                st.markdown(
                    f"""
                    <div class="mobile-market-evidence-box">
                        {evidence_cards_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
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

        cache_status = get_cache_status()
        if cache_status:
            st.markdown(
                f"""
                <div class="cache-status-card">
                    <div><b>최근 데이터 기준일</b> {escape_html(cache_status['data_date'])}</div>
                    <div><b>가격 기준</b> {escape_html(cache_status['price_basis'])}</div>
                    <div><b>수집 시각</b> {escape_html(cache_status['price_time'])}</div>
                    <div><b>캐시 동기화</b> {escape_html(cache_status['file_time'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        return market_data
    except Exception as e:
        st.error(f"시장 분석 패널 로드 오류: {e}")
        return {}


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
        .mobile-market-card {
            border: 1px solid rgba(191, 219, 254, 0.9);
            border-radius: 16px;
            padding: 16px;
            margin: 10px 0 14px 0;
            background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        .mobile-market-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: #1e3a8a;
            font-size: 0.92rem;
            margin-bottom: 10px;
        }
        .mobile-market-top span {
            color: #2563eb;
            font-size: 0.78rem;
        }
        .mobile-market-state {
            color: #0f172a;
            font-size: 1.08rem;
            margin-bottom: 6px;
        }
        .mobile-market-score,
        .mobile-market-summary {
            color: #334155;
            font-size: 0.86rem;
            line-height: 1.45;
            margin-bottom: 8px;
        }
        .mobile-market-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .mobile-lens-card {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 10px;
            padding: 13px 14px;
            margin: 8px 0 12px 0;
            background: #ffffff;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }
        .mobile-lens-title {
            color: #475569;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 5px;
        }
        .mobile-lens-current {
            color: #111827;
            font-size: 1rem;
            font-weight: 900;
            margin-bottom: 5px;
        }
        .mobile-lens-description {
            color: #334155;
            font-size: 0.86rem;
            line-height: 1.45;
            margin-bottom: 6px;
        }
        .mobile-lens-note {
            color: #64748b;
            font-size: 0.78rem;
            line-height: 1.35;
        }
        .mobile-market-tags span,
        .mobile-chip-row span {
            border-radius: 999px;
            padding: 5px 9px;
            background: #f1f5f9;
            color: #334155;
            font-size: 0.78rem;
            font-weight: 650;
        }
        .market-score-guide {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 3px;
            margin: 4px 0 12px 0;
            width: 100%;
            overflow: hidden;
        }
        .market-score-guide span,
        .market-score-guide b {
            border-radius: 999px;
            padding: 5px 2px;
            background: #f1f5f9;
            color: #475569;
            font-size: 0.63rem;
            font-weight: 800;
            line-height: 1;
            text-align: center;
            white-space: nowrap;
            min-width: 0;
            overflow: hidden;
        }
        .market-score-guide b {
            background: #fff7ed;
            color: #ea580c;
            border: 1px solid #fed7aa;
        }
        .mobile-candidate-card {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 14px;
            padding: 13px;
            margin: 12px 0 6px 0;
            background: #ffffff;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
        }
        .mobile-candidate-head,
        .mobile-detail-top,
        .mobile-price-row,
        .mobile-score-row,
        .mobile-detail-score {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
        }
        .mobile-candidate-name {
            display: flex;
            gap: 9px;
            align-items: flex-start;
            color: #111827;
            min-width: 0;
        }
        .mobile-candidate-name b {
            display: block;
            font-size: 0.98rem;
            line-height: 1.2;
        }
        .mobile-candidate-name small,
        .mobile-stock-rank {
            display: block;
            color: #64748b;
            font-size: 0.75rem;
            margin-top: 2px;
        }
        .mobile-rank-badge {
            min-width: 24px;
            height: 24px;
            border-radius: 7px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            font-weight: 800;
            font-size: 0.82rem;
            background: #94a3b8;
        }
        .mobile-rank-badge.hot {
            background: linear-gradient(135deg, #ef4444, #f97316);
        }
        .mobile-grade-pill {
            border: 1px solid #fecaca;
            color: #ef4444;
            background: #fff7f7;
            border-radius: 999px;
            padding: 4px 8px;
            font-size: 0.72rem;
            font-weight: 750;
            white-space: nowrap;
        }
        .mobile-price-row {
            align-items: center;
            margin: 13px 0 10px 0;
        }
        .mobile-price-row b {
            color: #111827;
            font-size: 1.05rem;
        }
        .mobile-price-row span,
        .mobile-detail-price span {
            color: #2563eb;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .mobile-signal-grid,
        .mobile-detail-signals {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 7px;
            margin-bottom: 10px;
        }
        .mobile-signal-card,
        .mobile-detail-signal {
            border-radius: 10px;
            padding: 8px 7px;
            background: #f8fafc;
            min-height: 96px;
            overflow: hidden;
            display: grid;
            grid-template-rows: 16px 18px 18px 18px;
            gap: 3px;
        }
        .mobile-signal-card small,
        .mobile-detail-signal small {
            display: block;
            color: #64748b;
            font-size: 0.69rem;
            line-height: 1.05;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 0;
        }
        .mobile-signal-card b,
        .mobile-detail-signal b {
            display: block;
            color: #0f172a;
            font-size: 0.82rem;
            line-height: 1.05;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .mobile-signal-card em,
        .mobile-detail-signal em {
            display: block;
            color: #64748b;
            font-size: 0.66rem;
            font-style: normal;
            line-height: 1.05;
            margin-top: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .mobile-signal-card.good,
        .mobile-detail-signal.good { background: #f0fdf4; }
        .mobile-signal-card.good b,
        .mobile-detail-signal.good b { color: #16a34a; }
        .mobile-signal-card.watch,
        .mobile-detail-signal.watch { background: #fffbeb; }
        .mobile-signal-card.watch b,
        .mobile-detail-signal.watch b { color: #d97706; }
        .mobile-signal-card.risk,
        .mobile-detail-signal.risk { background: #fef2f2; }
        .mobile-signal-card.risk b,
        .mobile-detail-signal.risk b { color: #ef4444; }
        .mobile-score-row,
        .mobile-detail-score {
            color: #64748b;
            font-size: 0.78rem;
            margin: 8px 0;
        }
        .mobile-score-row b,
        .mobile-detail-score b {
            color: #16a34a;
        }
        .mobile-secondary-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin: 8px 0 5px 0;
        }
        .mobile-secondary-row span {
            border-radius: 999px;
            background: #ecfeff;
            color: #0369a1;
            border: 1px solid #bae6fd;
            padding: 5px 9px;
            font-size: 0.76rem;
            font-weight: 900;
            line-height: 1.15;
        }
        .mobile-secondary-sentence {
            color: #334155;
            font-size: 0.8rem;
            line-height: 1.35;
            margin: 0 0 8px 0;
        }
        .mobile-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
        }
        .mobile-detail-hero {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 18px;
            padding: 16px;
            margin: 12px 0 14px 0;
            background: #ffffff;
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
        }
        .mobile-detail-price {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 16px 0 12px 0;
        }
        .mobile-detail-price b {
            color: #111827;
            font-size: 1.35rem;
            line-height: 1;
        }
        [class*="st-key-mobile_fixed_close_wrap"] {
            position: fixed;
            left: 12px;
            right: 148px;
            bottom: 8px;
            z-index: 9999;
            width: auto;
            max-width: 520px;
            padding: 4px;
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.96);
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.18);
            backdrop-filter: blur(10px);
        }
        [class*="st-key-mobile_fixed_close_wrap"] [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
            gap: 3px !important;
            align-items: center !important;
        }
        [class*="st-key-mobile_fixed_close_wrap"] [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: initial !important;
        }
        [class*="st-key-mobile_fixed_close_wrap"] [data-testid="stVerticalBlock"],
        [class*="st-key-mobile_fixed_close_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-mobile_fixed_close_wrap"] [data-testid="stButton"] {
            width: 100% !important;
            min-width: 0 !important;
        }
        [class*="st-key-mobile_fixed_tab_"] button,
        [class*="st-key-mobile_close_detail_fixed_"] button {
            width: 100% !important;
            min-width: 0 !important;
            min-height: 32px;
            height: 32px;
            border-radius: 7px;
            background: #f8fafc;
            color: #374151;
            border: 1px solid rgba(226, 232, 240, 0.95);
            font-size: 0.66rem;
            font-weight: 800;
            padding: 0 2px;
            white-space: nowrap;
            line-height: 1;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        [class*="st-key-mobile_fixed_tab_"] button p,
        [class*="st-key-mobile_close_detail_fixed_"] button p {
            margin: 0;
            line-height: 1;
            white-space: nowrap;
        }
        [class*="st-key-mobile_fixed_tab_active_"] button {
            background: #111827;
            color: #ffffff;
            border-color: #111827;
        }
        [class*="st-key-mobile_fixed_tab_summary_"] button {
            background: #eff6ff;
            color: #1d4ed8;
            border-color: #bfdbfe;
        }
        [class*="st-key-mobile_fixed_tab_numbers_"] button {
            background: #f0fdf4;
            color: #15803d;
            border-color: #bbf7d0;
        }
        [class*="st-key-mobile_fixed_tab_chart_"] button {
            background: #fff7ed;
            color: #c2410c;
            border-color: #fed7aa;
        }
        [class*="st-key-mobile_fixed_tab_info_"] button {
            background: #f8fafc;
            color: #475569;
            border-color: #cbd5e1;
        }
        [class*="st-key-mobile_fixed_tab_active_summary_"] button {
            background: #1d4ed8 !important;
            color: #ffffff !important;
            border-color: #1d4ed8 !important;
        }
        [class*="st-key-mobile_fixed_tab_active_numbers_"] button {
            background: #15803d !important;
            color: #ffffff !important;
            border-color: #15803d !important;
        }
        [class*="st-key-mobile_fixed_tab_active_chart_"] button {
            background: #c2410c !important;
            color: #ffffff !important;
            border-color: #c2410c !important;
        }
        [class*="st-key-mobile_fixed_tab_active_info_"] button {
            background: #475569 !important;
            color: #ffffff !important;
            border-color: #475569 !important;
        }
        [class*="st-key-mobile_close_detail_fixed_"] button {
            background: #111827;
            color: #ffffff;
            border: 0;
        }
        .mobile-evidence-card {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 10px;
            padding: 9px 10px;
            margin: 7px 0;
            background: #ffffff;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }
        .mobile-market-evidence-box {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 12px;
            padding: 8px 10px;
            margin: 6px 0 12px 0;
            background: #f8fafc;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
        }
        .mobile-market-evidence-box .mobile-evidence-card {
            margin: 7px 0;
        }
        .mobile-market-evidence-box .mobile-evidence-card:first-child {
            margin-top: 0;
        }
        .mobile-market-evidence-box .mobile-evidence-card:last-child {
            margin-bottom: 0;
        }
        .mobile-evidence-line {
            display: grid;
            min-width: 0;
        }
        .mobile-evidence-line-main {
            grid-template-columns: minmax(42px, auto) minmax(0, 1fr);
            gap: 6px;
            align-items: baseline;
            margin-bottom: 6px;
        }
        .mobile-evidence-line-main b {
            color: #111827;
            font-size: 0.82rem;
            font-weight: 900;
            line-height: 1.15;
            white-space: nowrap;
        }
        .mobile-evidence-line-main span {
            color: #475569;
            font-size: 0.76rem;
            line-height: 1.15;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .mobile-evidence-line-data {
            grid-template-columns: minmax(58px, auto) repeat(3, minmax(0, 1fr));
            gap: 5px;
            align-items: center;
            color: #334155;
        }
        .mobile-evidence-line-data strong,
        .mobile-evidence-line-data em {
            display: block;
            min-width: 0;
            border-radius: 8px;
            background: #f8fafc;
            padding: 6px 5px;
            font-size: 0.67rem;
            line-height: 1;
            font-style: normal;
            font-weight: 800;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            text-align: center;
        }
        .mobile-evidence-line-data .positive { color: #ff4b4b; }
        .mobile-evidence-line-data .negative { color: #2563eb; }
        .mobile-evidence-line-data .neutral { color: #64748b; }
        .mobile-evidence-title {
            color: #111827;
            font-size: 0.88rem;
            font-weight: 800;
        }
        .mobile-evidence-verdict {
            display: flex;
            gap: 8px;
            align-items: center;
            justify-content: flex-end;
        }
        .mobile-evidence-verdict span {
            border-radius: 999px;
            background: #f1f5f9;
            color: #334155;
            padding: 4px 8px;
            font-size: 0.78rem;
            font-weight: 750;
        }
        .mobile-evidence-verdict b {
            font-size: 0.86rem;
        }
        .mobile-evidence-verdict b.positive { color: #ff4b4b; }
        .mobile-evidence-verdict b.negative { color: #2563eb; }
        .mobile-evidence-verdict b.neutral { color: #64748b; }
        .mobile-evidence-values {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 6px;
            margin-bottom: 8px;
        }
        .mobile-evidence-values span {
            border-radius: 8px;
            background: #f8fafc;
            color: #334155;
            padding: 7px 6px;
            font-size: 0.76rem;
            line-height: 1.25;
        }
        .mobile-evidence-meaning {
            color: #475569;
            font-size: 0.78rem;
            line-height: 1.4;
            text-align: right;
            min-width: 0;
        }
        .mobile-evidence-topline {
            display: grid;
            grid-template-columns: minmax(64px, auto) minmax(0, 1fr);
            gap: 8px;
            align-items: center;
            margin-bottom: 7px;
        }
        .cache-status-card {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 8px;
            padding: 8px 10px;
            margin: 8px 0;
            background: #f8fafc;
            color: #475569;
            font-size: 0.74rem;
            line-height: 1.45;
        }
        .cache-status-card b {
            color: #111827;
            font-weight: 750;
        }
        .market-driver-strip {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 6px;
            margin: 8px 0 10px 0;
            color: #334155;
            font-size: 0.8rem;
        }
        .market-driver-strip strong {
            color: #111827;
            font-weight: 900;
            margin-right: 2px;
        }
        .market-driver-strip span {
            border: 1px solid rgba(203, 213, 225, 0.95);
            border-radius: 999px;
            background: #f8fafc;
            padding: 5px 9px;
            line-height: 1.2;
            white-space: nowrap;
        }
        .market-driver-strip b {
            color: #0f172a;
        }
        [class*="st-key-top_choice_panel"] {
            border: 1px solid rgba(203, 213, 225, 0.95);
            border-radius: 10px;
            padding: 12px 14px 14px 14px;
            margin: 10px 0 10px 0;
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
        }
        .top-choice-eyebrow {
            color: #111827;
            font-size: 1rem;
            font-weight: 900;
            line-height: 1.2;
            margin-bottom: 2px;
        }
        .top-choice-label {
            color: #334155;
            font-size: 0.86rem;
            font-weight: 900;
            margin: 10px 0 5px 2px;
        }
        [class*="st-key-top_market_choice_wrap"] [data-testid="stHorizontalBlock"],
        [class*="st-key-top_view_choice_wrap"] [data-testid="stHorizontalBlock"],
        [class*="st-key-top_lens_choice_wrap"] [data-testid="stHorizontalBlock"],
        [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stHorizontalBlock"] {
            display: grid !important;
            gap: 6px !important;
            align-items: center !important;
            width: 100% !important;
            flex-wrap: nowrap !important;
            overflow: hidden !important;
        }
        [class*="st-key-top_market_choice_wrap"] [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        }
        [class*="st-key-top_view_choice_wrap"] [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        }
        [class*="st-key-top_lens_choice_wrap"] [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(8, minmax(0, 1fr)) !important;
        }
        [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        }
        [class*="st-key-top_market_choice_wrap"] [data-testid="stColumn"],
        [class*="st-key-top_view_choice_wrap"] [data-testid="stColumn"],
        [class*="st-key-top_lens_choice_wrap"] [data-testid="stColumn"],
        [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: initial !important;
            max-width: none !important;
            padding: 0 !important;
        }
        [class*="st-key-top_market_choice_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-top_view_choice_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-top_lens_choice_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-top_market_choice_wrap"] [data-testid="stButton"],
        [class*="st-key-top_view_choice_wrap"] [data-testid="stButton"],
        [class*="st-key-top_lens_choice_wrap"] [data-testid="stButton"],
        [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stButton"] {
            width: 100% !important;
            min-width: 0 !important;
        }
        [class*="st-key-top_market_choice_"] button,
        [class*="st-key-top_view_choice_"] button,
        [class*="st-key-top_lens_choice_"] button,
        [class*="st-key-top_second_lens_choice_"] button {
            min-height: 40px;
            height: 40px;
            border-radius: 8px;
            border: 1px solid rgba(203, 213, 225, 0.95);
            background: #ffffff;
            color: #0f172a;
            font-size: 0.82rem;
            font-weight: 900;
            padding: 0 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
        }
        [class*="st-key-top_market_choice_active_"] button,
        [class*="st-key-top_view_choice_active_"] button,
        [class*="st-key-top_lens_choice_active_"] button,
        [class*="st-key-top_second_lens_choice_active_"] button {
            background: #111827 !important;
            color: #ffffff !important;
            border-color: #111827 !important;
            box-shadow: 0 8px 18px rgba(17, 24, 39, 0.2);
        }
        .top-choice-help {
            color: #64748b;
            font-size: 0.78rem;
            line-height: 1.35;
            margin: 6px 0 2px 2px;
        }
        .top-choice-help b {
            color: #111827;
            font-weight: 900;
        }
        [class*="st-key-mobile_count_wrap"] [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
            gap: 4px !important;
            align-items: center !important;
            width: 100% !important;
            flex-wrap: nowrap !important;
            overflow: hidden !important;
        }
        [class*="st-key-mobile_card_actions_"] [data-testid="stHorizontalBlock"] {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 6px !important;
            align-items: center !important;
            width: 100% !important;
            flex-wrap: nowrap !important;
            overflow: hidden !important;
        }
        [class*="st-key-mobile_count_wrap"] [data-testid="stColumn"],
        [class*="st-key-mobile_card_actions_"] [data-testid="stColumn"] {
            width: 100% !important;
            min-width: 0 !important;
            flex: initial !important;
            max-width: none !important;
            padding: 0 !important;
        }
        [class*="st-key-mobile_count_wrap"] [data-testid="stElementContainer"],
        [class*="st-key-mobile_card_actions_"] [data-testid="stElementContainer"],
        [class*="st-key-mobile_count_wrap"] [data-testid="stButton"],
        [class*="st-key-mobile_card_actions_"] [data-testid="stButton"] {
            width: 100% !important;
            min-width: 0 !important;
        }
        [class*="st-key-mobile_count_"] button,
        [class*="st-key-mobile_more_5"] button,
        [class*="st-key-mobile_evidence_"] button,
        [class*="st-key-mobile_candidate_"] button,
        [class*="st-key-mobile_close_detail_"] button {
            min-height: 34px;
            height: 34px;
            border-radius: 8px;
            font-size: 0.76rem;
            font-weight: 800;
            padding: 0 4px;
            white-space: nowrap;
            overflow: hidden;
        }
        [class*="st-key-mobile_count_active_"] button {
            background: #111827 !important;
            color: #ffffff !important;
            border-color: #111827 !important;
            box-shadow: 0 7px 16px rgba(17, 24, 39, 0.18);
        }
        .mobile-signal-evidence-panel {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            margin: 8px 0 12px 0;
        }
        .mobile-signal-evidence-card {
            border-radius: 10px;
            padding: 10px;
            border: 1px solid rgba(226, 232, 240, 0.95);
            background: #ffffff;
        }
        .mobile-signal-evidence-card.good { border-color: #bbf7d0; background: #f0fdf4; }
        .mobile-signal-evidence-card.watch { border-color: #fde68a; background: #fffbeb; }
        .mobile-signal-evidence-card.risk { border-color: #fecaca; background: #fef2f2; }
        .mobile-signal-evidence-head {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            align-items: center;
            margin-bottom: 6px;
        }
        .mobile-signal-evidence-head span {
            color: #334155;
            font-size: 0.78rem;
            font-weight: 800;
        }
        .mobile-signal-evidence-head b {
            color: #111827;
            font-size: 0.82rem;
            white-space: nowrap;
        }
        .mobile-signal-evidence-card p {
            margin: 0 0 7px 0;
            color: #0f172a;
            font-size: 0.82rem;
            font-weight: 750;
        }
        .mobile-signal-evidence-card ul {
            margin: 0;
            padding-left: 16px;
            color: #475569;
            font-size: 0.78rem;
            line-height: 1.45;
        }
        .mobile-detail-section-card {
            border: 1px solid rgba(226, 232, 240, 0.95);
            border-radius: 10px;
            padding: 10px;
            margin: 9px 0;
            background: #ffffff;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }
        .mobile-detail-section-card.judgment {
            border-color: #bfdbfe;
            background: #eff6ff;
        }
        .mobile-detail-section-card.positive {
            border-color: #bbf7d0;
            background: #f0fdf4;
        }
        .mobile-detail-section-card.caution {
            border-color: #fde68a;
            background: #fffbeb;
        }
        .mobile-detail-section-card.stability {
            border-color: #c4b5fd;
            background: #f5f3ff;
        }
        .mobile-detail-section-card.info {
            border-color: #cbd5e1;
            background: #f8fafc;
        }
        .mobile-detail-section-card.neutral {
            border-color: #bae6fd;
            background: #f0f9ff;
        }
        .mobile-detail-section-title {
            color: #111827;
            font-size: 0.9rem;
            font-weight: 900;
            margin-bottom: 8px;
        }
        .mobile-detail-section-card.judgment .mobile-detail-section-title { color: #1d4ed8; }
        .mobile-detail-section-card.positive .mobile-detail-section-title { color: #15803d; }
        .mobile-detail-section-card.caution .mobile-detail-section-title { color: #b45309; }
        .mobile-detail-section-card.stability .mobile-detail-section-title { color: #6d28d9; }
        .mobile-detail-section-card.info .mobile-detail-section-title { color: #475569; }
        .mobile-detail-section-card.neutral .mobile-detail-section-title { color: #0369a1; }
        .mobile-detail-section-row {
            border: 1px solid rgba(226, 232, 240, 0.86);
            border-radius: 9px;
            padding: 8px;
            margin-top: 7px;
            background: rgba(255, 255, 255, 0.78);
        }
        .mobile-detail-section-head {
            display: grid;
            grid-template-columns: minmax(82px, auto) minmax(0, 1fr);
            gap: 8px;
            align-items: center;
            margin-bottom: 5px;
        }
        .mobile-detail-section-head b {
            color: #334155;
            font-size: 0.76rem;
            font-weight: 900;
            white-space: nowrap;
        }
        .mobile-detail-section-head span {
            color: #111827;
            font-size: 0.82rem;
            font-weight: 850;
            line-height: 1.2;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .mobile-detail-section-body,
        .mobile-detail-section-empty {
            color: #475569;
            font-size: 0.78rem;
            line-height: 1.35;
        }
        .mobile-stock-card {
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 8px;
            padding: 14px 14px 12px 14px;
            margin: 12px 0 6px 0;
            background: rgba(255, 255, 255, 0.03);
        }
        .mobile-stock-rank {
            color: #475569;
            font-size: 0.82rem;
            margin-bottom: 4px;
        }
        .mobile-stock-title {
            color: #0f172a;
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
            color: #334155;
            font-size: 0.86rem;
            margin-bottom: 6px;
        }
        .mobile-stock-summary {
            color: #334155;
            font-size: 0.9rem;
            line-height: 1.35;
            margin-bottom: 10px;
        }
        .mobile-stock-reason {
            color: #1e293b;
            font-size: 0.86rem;
            line-height: 1.35;
            margin-bottom: 4px;
        }
        .mobile-stock-reason b {
            color: #ff4b4b;
            margin-right: 4px;
        }
        .mobile-stock-facts {
            color: #0f172a;
            font-size: 0.84rem;
            line-height: 1.35;
            margin: -1px 0 7px 0;
            padding-left: 6px;
            border-left: 3px solid rgba(255, 75, 75, 0.45);
        }
        .mobile-stock-facts b {
            color: #475569;
            margin-right: 4px;
        }
        .mobile-stock-warning {
            color: #0369a1;
            font-size: 0.86rem;
            line-height: 1.35;
            margin: 4px 0 10px 0;
        }
        .mobile-stock-warning b {
            color: #0284c7;
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
        .mobile-metric-row {
            border: 1px solid rgba(148, 163, 184, 0.24);
            border-radius: 8px;
            padding: 10px 12px;
            margin: 8px 0;
            background: rgba(248, 250, 252, 0.75);
        }
        .mobile-metric-head {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            color: #0f172a;
            font-size: 0.92rem;
            margin-bottom: 5px;
        }
        .mobile-metric-head span {
            font-weight: 700;
            color: #ff4b4b;
            white-space: nowrap;
        }
        .mobile-metric-explain {
            color: #334155;
            font-size: 0.85rem;
            line-height: 1.4;
        }
        @media (max-width: 720px) {
            .block-container { padding-bottom: 5rem; }
            [class*="st-key-top_lens_choice_wrap"] [data-testid="stHorizontalBlock"] {
                grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            }
            [class*="st-key-top_second_lens_choice_wrap"] [data-testid="stHorizontalBlock"] {
                grid-template-columns: repeat(1, minmax(0, 1fr)) !important;
            }
            [class*="st-key-top_market_choice_"] button,
            [class*="st-key-top_view_choice_"] button,
            [class*="st-key-top_lens_choice_"] button,
            [class*="st-key-top_second_lens_choice_"] button {
                min-height: 38px;
                height: 38px;
                font-size: 0.74rem;
                padding: 0 3px;
            }
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
    st.info("💡 데이터 수집은 GitHub Actions 정기 스케줄에서만 실행됩니다. 앱에서는 저장된 캐시를 읽습니다.")

# ==========================================
# 5. 메인 대시보드 화면 및 컨트롤 패널
# ==========================================
st.header(f"🎯 {get_market_text()} 분석")
st.caption("1단계 좋은 회사 후보 → 2단계 시장환경 점검 → 3단계 좋은 회사인데 왜 안 오르지?")
render_top_choice_panel()

st.divider()
st.subheader("1단계: 좋은 회사 후보 찾기")

if st.session_state.data:
    df = analyzer.normalize_dividend_yield_metrics(pd.DataFrame(st.session_state.data))
    df = analyzer.sort_by_market_cap(df)
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
    if st.session_state.table_view_mode == "PC 보기":
        table_action_col = st.columns([6, 1], vertical_alignment="bottom")[1]
        with table_action_col:
            if st.button("⛶ 표 크게 보기", key="toggle_large_table", width="stretch"):
                st.session_state.show_large_table = not st.session_state.get("show_large_table", False)

    if st.session_state.table_view_mode == "모바일 보기":
        current_lens = st.session_state.mobile_investment_lens
        current_secondary_lens = st.session_state.mobile_secondary_lens
        lens_meta = MOBILE_LENS_META.get(current_lens, MOBILE_LENS_META["🎯 종합평가"])
        render_mobile_lens_panel(current_lens)

        sorted_mobile_df = sort_mobile_candidates(df, current_lens)
        mobile_df = filter_mobile_candidates_for_lens(sorted_mobile_df, current_lens)
        mobile_df, secondary_analyses = apply_mobile_secondary_lens(mobile_df, current_secondary_lens, get_market_text())
        if current_lens == "🎯 종합평가":
            excluded_mobile_df = sorted_mobile_df[
                sorted_mobile_df.apply(lambda row: mobile_grade_label(row.to_dict()), axis=1) == "⚪ 좋은 회사지만 아직 비쌈"
            ].reset_index(drop=True)
        else:
            excluded_mobile_df = pd.DataFrame()
        total_candidates = len(mobile_df)
        visible_count = min(st.session_state.mobile_visible_count, total_candidates)
        if visible_count <= 0:
            visible_count = min(5, total_candidates)
            st.session_state.mobile_visible_count = visible_count

        visible_mobile_df = mobile_df.head(visible_count)
        if st.session_state.mobile_selected_symbol not in set(mobile_df["symbol"].astype(str)):
            st.session_state.mobile_selected_symbol = None

        title_prefix = current_secondary_lens or lens_meta["title"]
        st.subheader(title_prefix)
        if current_secondary_lens:
            st.caption(MOBILE_SECONDARY_LENS_META.get(current_secondary_lens, {}).get("description", ""))

        with st.container(key="mobile_count_wrap"):
            count_cols = st.columns(5, gap="small")
            quick_options = [("5개", 5), ("10개", 10), ("20개", 20), ("전체", total_candidates)]
            for idx, (label, count) in enumerate(quick_options):
                with count_cols[idx]:
                    is_active_count = visible_count >= total_candidates if label == "전체" else visible_count == count
                    if st.button(label, key=f"mobile_count_{'active_' if is_active_count else ''}{idx}", width="stretch"):
                        st.session_state.mobile_visible_count = min(count, total_candidates)
                        st.session_state.mobile_selected_symbol = None
                        st.session_state.mobile_evidence_symbol = None
                        st.rerun()

            with count_cols[4]:
                next_count = min(visible_count + 5, total_candidates)
                if st.button("다음5개", key="mobile_more_5", width="stretch", disabled=visible_count >= total_candidates):
                    st.session_state.mobile_visible_count = next_count
                    st.session_state.mobile_selected_symbol = None
                    st.session_state.mobile_evidence_symbol = None
                    st.rerun()

        st.caption("상세 보기를 누르면 해당 후보 바로 아래에 열립니다. 다시 닫고 다음 후보를 볼 수 있습니다.")
        if visible_mobile_df.empty and current_secondary_lens:
            st.info("현재 기준에 맞는 종목이 없습니다. 투자 렌즈 Ⅱ를 한 번 더 눌러 해제하거나 다른 렌즈를 선택해보세요.")
        for list_index, (_, row) in enumerate(visible_mobile_df.iterrows(), start=1):
            row_dict = row.to_dict()
            symbol = str(row_dict.get("symbol", ""))
            render_mobile_candidate_card(
                row_dict,
                list_index,
                is_kr,
                current_lens,
                secondary_analyses.get(symbol) if current_secondary_lens else None,
            )
            evidence_open = st.session_state.mobile_evidence_symbol == symbol
            evidence_label = "근거 닫기" if evidence_open else "근거 보기"
            with st.container(key=f"mobile_card_actions_{symbol}_{list_index}"):
                action_cols = st.columns(2, gap="small")
                with action_cols[0]:
                    if st.button(evidence_label, key=f"mobile_evidence_{symbol}_{list_index}", width="stretch"):
                        st.session_state.mobile_evidence_symbol = None if evidence_open else symbol
                        st.rerun()
                with action_cols[1]:
                    if st.session_state.mobile_selected_symbol == symbol:
                        if st.button("상세 닫기", key=f"mobile_close_detail_{symbol}_{list_index}", width="stretch"):
                            st.session_state.mobile_selected_symbol = None
                            st.rerun()
                    else:
                        if st.button("상세 보기 ›", key=f"mobile_candidate_{symbol}_{list_index}", width="stretch"):
                            st.session_state.mobile_selected_symbol = symbol
                            st.session_state.mobile_evidence_symbol = None
                            st.session_state.mobile_detail_tab = "요약"
                            st.rerun()
            if evidence_open:
                render_mobile_evidence_panel(row_dict, current_lens)
            if st.session_state.mobile_selected_symbol == symbol:
                render_mobile_stock_card(row_dict, is_kr, show_header=False, lens=current_lens)
                with st.container(key=f"mobile_fixed_close_wrap_{symbol}_{list_index}"):
                    tab_cols = st.columns(5)
                    fixed_tabs = [("요약", "요약", "summary"), ("수치", "상세 수치", "numbers"), ("차트", "차트", "chart"), ("정보", "기업 정보", "info")]
                    for tab_col, (short_label, tab_label, tone_key) in zip(tab_cols[:4], fixed_tabs):
                        active_key_part = "active_" if st.session_state.mobile_detail_tab == tab_label else ""
                        with tab_col:
                            if st.button(
                                short_label,
                                key=f"mobile_fixed_tab_{active_key_part}{tone_key}_{symbol}_{list_index}",
                                width="stretch",
                            ):
                                st.session_state.mobile_detail_tab = tab_label
                                st.rerun()
                    with tab_cols[4]:
                        if st.button("닫기", key=f"mobile_close_detail_fixed_{symbol}_{list_index}", width="stretch"):
                            st.session_state.mobile_selected_symbol = None
                            st.rerun()

        if not excluded_mobile_df.empty:
            with st.expander(f"관찰 후보 보기: 좋은 회사지만 아직 비쌈 {len(excluded_mobile_df)}개", expanded=False):
                rows = []
                for idx, (_, row) in enumerate(excluded_mobile_df.head(20).iterrows(), start=1):
                    row_dict = row.to_dict()
                    watch_reasons = mobile_watch_reasons(row_dict)
                    rows.append({
                        "순서": idx,
                        "종목": row_dict.get("name", row_dict.get("symbol")),
                        "후보적합도": f"{mobile_candidate_score(row_dict):.0f}",
                        "관찰이유": " · ".join(watch_reasons),
                        "PER": format_metric(row_dict.get("per")),
                        "RSI": format_metric(row_dict.get("rsi"), decimals=0),
                        "고점대비": format_metric(row_dict.get("peak_diff"), "%"),
                    })
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    else:
        # width="stretch": 브라우저 크기에 맞추되 column_config로 각 데이터에 맞게 최적 너비 설정
        st.dataframe(formatted_styled_df, width="stretch", hide_index=True, column_config=col_config)
        if st.session_state.get("show_large_table", False):
            st.caption("확대 보기")
            st.dataframe(formatted_styled_df, width="stretch", height=820, hide_index=True, column_config=col_config)

    st.divider()
    market_data = render_market_environment_panel()

    if st.session_state.table_view_mode == "PC 보기":
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
        if hasattr(diagnostics, "diagnose_blockers"):
            blocker_diagnosis = diagnostics.diagnose_blockers(selected_row)
        else:
            blocker_diagnosis = {
                "headline": headline,
                "decision": headline,
                "positives": "진단 모듈 업데이트 대기",
                "top_blockers": reason_rows[:3],
                "detail_blockers": reason_rows,
            }
        if hasattr(diagnostics, "data_completeness"):
            completeness = diagnostics.data_completeness(selected_row)
        else:
            completeness = {"score": 0, "available_count": 0, "total_count": 0, "summary": "진단 모듈 업데이트 대기"}
    
        st.info(f"**결론:** {blocker_diagnosis['decision']}")
        st.caption(
            f"데이터 완성도: `{completeness['score']}%` "
            f"({completeness['available_count']}/{completeness['total_count']})"
            f" | 부족: `{completeness['summary']}`"
        )
        st.caption(f"긍정 요인: {blocker_diagnosis['positives']}")
    
        st.markdown("**핵심 원인 TOP 3**")
        st.dataframe(pd.DataFrame(blocker_diagnosis["top_blockers"]), width="stretch", hide_index=True)
    
        tab_review, tab_reasons, tab_missing, tab_market = st.tabs(["전체 수치 검토", "상세 원인·수치", "부족한 데이터", "시장환경 연결"])
        with tab_review:
            st.dataframe(pd.DataFrame(diagnostics.build_metric_review(selected_row)), width="stretch", hide_index=True)
        with tab_reasons:
            st.dataframe(pd.DataFrame(blocker_diagnosis["detail_blockers"]), width="stretch", hide_index=True)
        with tab_missing:
            st.dataframe(pd.DataFrame(diagnostics.missing_data_review(selected_row)), width="stretch", hide_index=True)
            supplemental_data.ensure_template()
            st.caption(f"차단 위험 없이 보강하려면 공식/유료 데이터 또는 직접 받은 CSV를 `{supplemental_data.SUPPLEMENTAL_FILE}`에 채우면 다음 수집 때 자동 병합됩니다.")
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
        st.warning("스크리너가 모르는 것: 이 진단은 수치로 확인 가능한 데이터 중심입니다. 아래 변수는 점수와 결론에 충분히 반영되지 않을 수 있습니다.")
        st.markdown(
            "지정학적 리스크 · 정치·규제 변화 · 예기치 못한 대형 사건 · "
            "경영진의 돌발 이슈 · 소송·회계·공시 리스크 · 실적 발표 직전 변동성"
        )

else:
    st.info("💡 저장된 캐시 데이터가 없습니다. GitHub Actions 정기 스케줄이 수집을 완료한 뒤 앱을 다시 열어주세요.")
