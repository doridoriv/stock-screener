import math
from typing import Dict, List, Tuple

import pandas as pd


def _num(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        value = float(value)
    except Exception:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _txt(value, suffix=""):
    value = _num(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}{suffix}"


def _has_value(row: Dict[str, object], key: str) -> bool:
    value = row.get(key)
    if _num(value) is not None:
        return True
    return isinstance(value, str) and value.strip() not in ["", "-", "N/A", "None", "nan", "NaN"]


def _grade_metric(value, good=None, bad=None, lower_is_better=False):
    value = _num(value)
    if value is None:
        return "확인 필요"
    if lower_is_better:
        if good is not None and value <= good:
            return "긍정적"
        if bad is not None and value >= bad:
            return "부담"
    else:
        if good is not None and value >= good:
            return "긍정적"
        if bad is not None and value <= bad:
            return "부담"
    return "중립"


def _signed_txt(value, suffix=""):
    value = _num(value)
    if value is None:
        return "N/A"
    return f"{value:+,.2f}{suffix}"


def _compact_amount(value):
    value = _num(value)
    if value is None:
        return "N/A"
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"{sign}{abs_value / 1_000_000_000_000:.2f}T"
    if abs_value >= 1_000_000_000:
        return f"{sign}{abs_value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}{abs_value / 1_000_000:.2f}M"
    return f"{value:,.2f}"


def _missing_metric_value(row: Dict[str, object], key: str) -> str:
    amount_keys = {
        "free_cashflow",
        "operating_cashflow",
        "cash",
        "net_cash",
    }
    suffix_keys = {
        "operating_margin",
        "net_margin",
        "peer_per_gap",
    }
    if key in amount_keys:
        return _compact_amount(row.get(key))
    if key in suffix_keys:
        return _signed_txt(row.get(key), "%")
    return _txt(row.get(key))


def _missing_metric_interpretation(row: Dict[str, object], key: str) -> str:
    value = _num(row.get(key))
    if value is None:
        return "아직 수치가 없어 판단 보류"

    if key in ["free_cashflow", "operating_cashflow"]:
        return "플러스라 현금 창출 확인" if value > 0 else "마이너스라 현금 유출 부담"
    if key == "cash":
        return "현금 보유로 위기 대응 여력 확인" if value > 0 else "현금 여력 낮음"
    if key == "net_cash":
        return "순현금이라 재무 부담 낮음" if value > 0 else "순차입이라 재무 부담 확인 필요"
    if key == "operating_margin":
        return "영업 수익성이 양호" if value >= 15 else "영업 수익성 추가 확인"
    if key == "net_margin":
        return "최종 수익성이 양호" if value >= 10 else "최종 수익성 추가 확인"
    if key in ["foreign_net_buy", "institution_net_buy"]:
        return "순매수라 수급 방향 긍정" if value > 0 else "순매도라 수급 부담"
    if key == "consensus_revision":
        return "기대치 상향 흐름" if value > 0 else "기대치 하향 부담"
    if key == "peer_per_gap":
        return "업종 대비 저렴" if value < 0 else "업종 대비 비쌈"
    return "수치 확인됨"


def _metric_result_text(kind: str, row: Dict[str, object]) -> str:
    if kind == "business":
        roe = _num(row.get("roe"))
        revenue = _num(row.get("revenue_growth"))
        operating = _num(row.get("operating_growth"))
        parts = []
        if roe is not None:
            parts.append("ROE가 높아 자본 효율이 좋음" if roe >= 15 else "ROE가 낮아 높은 밸류를 받기 어려움" if roe < 8 else "ROE는 중립권")
        if revenue is not None:
            parts.append("매출 성장으로 외형 확대 확인" if revenue > 0 else "매출 성장 둔화")
        if operating is not None:
            parts.append("영업이익 성장으로 이익 레버리지 확인" if operating > 0 else "영업이익 성장 둔화")
        return " / ".join(parts) if parts else "기업 체력 판단에 필요한 성장성과 자본 효율을 확인"

    if kind == "valuation":
        per = _num(row.get("per"))
        hist_per = _num(row.get("hist_per_avg"))
        pbr = _num(row.get("pbr"))
        peg = _num(row.get("peg"))
        parts = []
        if per is not None and hist_per:
            gap = (per / hist_per - 1) * 100
            parts.append(f"PER이 과거평균 대비 {gap:+.1f}%라 기대치 반영 정도를 보여줌")
        elif per is not None:
            parts.append("PER이 높을수록 이익 대비 주가 부담이 큼" if per >= 25 else "PER 부담은 상대적으로 제한적")
        if pbr is not None:
            parts.append("PBR이 높아 자산 대비 프리미엄이 큼" if pbr >= 5 else "PBR은 자산 대비 부담이 낮은 편")
        if peg is not None:
            parts.append("PEG가 1 이하라 성장 대비 가격 부담이 낮음" if 0 < peg <= 1 else "PEG가 높아 성장 대비 가격 부담 확인")
        return " / ".join(parts) if parts else "현재 주가가 실적 대비 비싼지 판단"

    if kind == "cashflow":
        fcf = _num(row.get("free_cashflow"))
        ocf = _num(row.get("operating_cashflow"))
        if fcf is None and ocf is None:
            return "현금흐름이 비어 있어 이익의 질을 아직 확정할 수 없음"
        parts = []
        if ocf is not None:
            parts.append("영업현금흐름이 플러스라 본업 현금 창출 확인" if ocf > 0 else "영업현금흐름이 마이너스라 이익의 현금 전환 부담")
        if fcf is not None:
            parts.append("FCF가 플러스라 투자 후 남는 현금 확인" if fcf > 0 else "FCF가 마이너스라 성장에도 현금 유출 부담")
        return " / ".join(parts)

    if kind == "balance":
        debt = _num(row.get("debt_ratio"))
        cash = _num(row.get("cash"))
        net_cash = _num(row.get("net_cash"))
        parts = []
        if debt is not None:
            parts.append("부채비율이 낮아 금리 부담에 비교적 강함" if debt <= 80 else "부채비율이 높아 금리/업황 둔화에 민감" if debt >= 200 else "부채비율은 중립권")
        if cash is not None:
            parts.append("현금 보유로 위기 대응 여력 확인" if cash > 0 else "현금 여력 확인 필요")
        if net_cash is not None:
            parts.append("순현금 상태라 재무 부담 낮음" if net_cash > 0 else "순차입 상태라 재무 부담 확인 필요")
        return " / ".join(parts) if parts else "재무 안정성 데이터가 부족해 위기 대응력을 확정하기 어려움"

    if kind == "supply":
        supply = _num(row.get("foreign_supply"))
        if supply is None:
            return "수급 데이터가 부족해 주가 방향성 확인이 어려움"
        return "외국인/기관 관심이 높은 편이나 순매수 방향 확인이 추가로 필요" if supply >= 10 else "보유율이 낮아 수급 주도 여부는 추가 확인 필요"

    if kind == "technical":
        diff = _num(row.get("diff"))
        peak_diff = _num(row.get("peak_diff"))
        parts = []
        if diff is not None:
            parts.append("200일선 위라 중장기 추세가 살아 있음" if diff >= 0 else "200일선 아래라 시장의 추세 확인이 부족")
        if peak_diff is not None:
            parts.append("고점과 가까워 모멘텀은 살아 있음" if peak_diff > -10 else "고점 대비 낙폭이 커서 수급 회복 확인 필요")
        return " / ".join(parts) if parts else "가격 위치로 시장이 해당 종목을 인정하는지 확인"

    return "수치 결과가 주가 판단에 어떤 영향을 주는지 확인"


def build_metric_review(row: Dict[str, object]) -> List[Dict[str, str]]:
    per = _num(row.get("per"))
    hist_per = _num(row.get("hist_per_avg"))
    per_view = _txt(per)
    if per is not None and hist_per is not None:
        gap = (per / hist_per - 1) * 100 if hist_per else None
        per_view = f"{_txt(per)} / 과거평균 {_txt(hist_per)}"
        per_eval = "부담" if gap is not None and gap > 20 else "긍정적" if gap is not None and gap < -20 else "중립"
    else:
        per_eval = _grade_metric(per, good=12, bad=25, lower_is_better=True)

    return [
        {
            "구분": "기업 체력",
            "내가 본 항목": f"ROE {_txt(row.get('roe'), '%')} / 매출성장 {_txt(row.get('revenue_growth'), '%')} / 영업이익성장 {_txt(row.get('operating_growth'), '%')}",
            "현재 평가": _grade_metric(row.get("roe"), good=15, bad=5),
            "왜 중요함": _metric_result_text("business", row),
        },
        {
            "구분": "밸류에이션",
            "내가 본 항목": f"PER {per_view} / PBR {_txt(row.get('pbr'))} / PEG {_txt(row.get('peg'))}",
            "현재 평가": per_eval,
            "왜 중요함": _metric_result_text("valuation", row),
        },
        {
            "구분": "현금흐름",
            "내가 본 항목": f"FCF {_txt(row.get('free_cashflow'))} / 영업현금흐름 {_txt(row.get('operating_cashflow'))}",
            "현재 평가": _grade_metric(row.get("free_cashflow"), good=0, bad=0),
            "왜 중요함": _metric_result_text("cashflow", row),
        },
        {
            "구분": "재무 안정성",
            "내가 본 항목": f"부채비율 {_txt(row.get('debt_ratio'), '%')} / 현금 {_txt(row.get('cash'))} / 순현금 {_txt(row.get('net_cash'))}",
            "현재 평가": _grade_metric(row.get("debt_ratio"), good=80, bad=200, lower_is_better=True),
            "왜 중요함": _metric_result_text("balance", row),
        },
        {
            "구분": "수급",
            "내가 본 항목": f"외인/기관 보유율 {_txt(row.get('foreign_supply'), '%')}",
            "현재 평가": "참고용",
            "왜 중요함": _metric_result_text("supply", row),
        },
        {
            "구분": "기술적 위치",
            "내가 본 항목": f"200일선 괴리 {_txt(row.get('diff'), '%')} / 고점대비 {_txt(row.get('peak_diff'), '%')} / RSI {_txt(row.get('rsi'))}",
            "현재 평가": _grade_metric(row.get("diff"), good=0, bad=-20),
            "왜 중요함": _metric_result_text("technical", row),
        },
    ]


def missing_data_review(row: Dict[str, object]) -> List[Dict[str, str]]:
    required = [
        ("FCF", "free_cashflow", "보강 필요", "진짜 현금 창출 여부"),
        ("영업현금흐름", "operating_cashflow", "보강 필요", "이익의 현금 전환 확인"),
        ("현금보유액", "cash", "보강 필요", "위기 대응 능력"),
        ("순현금/순차입금", "net_cash", "보강 필요", "재무 부담 확인"),
        ("영업이익률", "operating_margin", "다음 수집 후 확인", "성장의 질"),
        ("순이익률", "net_margin", "다음 수집 후 확인", "최종 수익성"),
        ("외국인 순매수", "foreign_net_buy", "보강 필요", "단기/중기 수급 방향"),
        ("기관 순매수", "institution_net_buy", "보강 필요", "주가 방향성 수급"),
        ("컨센서스 변화", "consensus_revision", "보강 필요", "시장 기대치 상향/하향"),
        ("경쟁사 대비 PER", "peer_per_gap", "보강 필요", "업종 내 저평가 여부"),
    ]
    rows = []
    for label, key, missing_status, reason in required:
        available = _has_value(row, key)
        status = "확인" if available else missing_status
        rows.append({
            "항목": label,
            "상태": status,
            "현재 수치": _missing_metric_value(row, key) if available else "N/A",
            "해석": _missing_metric_interpretation(row, key) if available else "자료 보강 전까지 판단 제한",
            "왜 중요한가": reason,
        })
    return rows


def data_completeness(row: Dict[str, object]) -> Dict[str, object]:
    required = [
        ("PER", "per"),
        ("PBR", "pbr"),
        ("ROE", "roe"),
        ("EPS성장률", "eps_growth"),
        ("CAGR", "cagr"),
        ("PEG", "peg"),
        ("200일괴리율", "diff"),
        ("최고점대비", "peak_diff"),
        ("FCF", "free_cashflow"),
        ("영업현금흐름", "operating_cashflow"),
        ("현금", "cash"),
        ("부채비율", "debt_ratio"),
    ]
    available = [label for label, key in required if _has_value(row, key)]
    missing = [label for label, key in required if not _has_value(row, key)]
    score = round(len(available) / len(required) * 100, 1) if required else 0.0
    return {
        "score": score,
        "available_count": len(available),
        "total_count": len(required),
        "missing": missing,
        "summary": " / ".join(missing[:4]) if missing else "핵심 데이터 충분",
    }


def market_context_review(market_data: Dict[str, object]) -> List[Dict[str, str]]:
    if not market_data:
        return [{"구분": "시장환경", "항목": "미확인", "해석": "시장환경 캐시가 없어 종목 진단과 연결하지 못했습니다."}]

    score = _num(market_data.get("market_score"))
    state = market_data.get("score_state") or market_data.get("market_state") or "미확인"
    summary = market_data.get("summary") or "요약 없음"
    if score is None:
        effect = "시장환경 점수 미확인"
    elif score >= 65:
        effect = "시장 바람이 종목 상승을 도와주는 구간"
    elif score >= 50:
        effect = "시장 도움은 제한적이며 종목별 차별화 구간"
    elif score >= 35:
        effect = "좋은 회사도 시장 부담으로 주가가 눌릴 수 있음"
    else:
        effect = "시장 리스크가 커서 방어 우선 구간"

    return [
        {
            "구분": "시장환경",
            "항목": f"{score:.1f}점 / {state}" if score is not None else state,
            "해석": effect,
        },
        {
            "구분": "시장환경",
            "항목": "요약",
            "해석": summary,
        },
    ]


def diagnose_blockers(row: Dict[str, object]) -> Dict[str, object]:
    name = row.get("name", row.get("symbol", "선택 종목"))
    blockers = []
    positives = []

    per = _num(row.get("per"))
    hist_per = _num(row.get("hist_per_avg"))
    pbr = _num(row.get("pbr"))
    roe = _num(row.get("roe"))
    eps_growth = _num(row.get("eps_growth"))
    revenue_growth = _num(row.get("revenue_growth"))
    operating_growth = _num(row.get("operating_growth"))
    peg = _num(row.get("peg"))
    fcf = _num(row.get("free_cashflow"))
    operating_cashflow = _num(row.get("operating_cashflow"))
    diff = _num(row.get("diff"))
    peak_diff = _num(row.get("peak_diff"))
    rsi = _num(row.get("rsi"))
    debt_ratio = _num(row.get("debt_ratio"))
    foreign_supply = _num(row.get("foreign_supply"))

    if roe is not None and roe >= 15:
        positives.append("ROE 우수")
    if revenue_growth is not None and revenue_growth > 0:
        positives.append("매출 성장")
    if operating_growth is not None and operating_growth > 0:
        positives.append("영업이익 성장")

    if per is not None and hist_per is not None and hist_per > 0:
        per_gap = (per / hist_per - 1) * 100
        if per_gap > 20:
            blockers.append({
                "우선순위": len(blockers) + 1,
                "핵심 원인": "가격 부담",
                "결론": "좋은 회사여도 현재 가격에 기대가 많이 반영됐을 수 있습니다.",
                "상세 수치": f"현재 PER {_txt(per)} / 과거 평균 PER {_txt(hist_per)} / 괴리 {per_gap:+.1f}%",
                "판정": "매수 보류 또는 더 싼 가격 대기",
            })
    elif per is not None and per >= 25:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "높은 PER",
            "결론": "이익 성장보다 주가 기대치가 앞서 있을 수 있습니다.",
            "상세 수치": f"현재 PER {_txt(per)} / 과거 평균 PER N/A",
            "판정": "성장률 재확인",
        })

    if eps_growth is None or eps_growth <= 0:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "이익 성장 둔화",
            "결론": "이익 증가가 약하면 PER 재평가가 늦어질 수 있습니다.",
            "상세 수치": f"EPS성장률 {_txt(eps_growth, '%')} / 매출성장률 {_txt(revenue_growth, '%')} / 영업이익성장률 {_txt(operating_growth, '%')}",
            "판정": "실적 반전 확인 전까지 보수적 관찰",
        })

    if fcf is None:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "현금흐름 미확인",
            "결론": "이익이 실제 현금으로 남는지 아직 확정하기 어렵습니다.",
            "상세 수치": f"FCF N/A / 영업현금흐름 {_txt(operating_cashflow)}",
            "판정": "현금흐름 데이터 보강 필요",
        })
    elif fcf < 0:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "FCF 적자",
            "결론": "성장 중이어도 현금 유출이 크면 주가가 눌릴 수 있습니다.",
            "상세 수치": f"FCF {_txt(fcf)} / 영업현금흐름 {_txt(operating_cashflow)}",
            "판정": "현금 창출 회복 확인",
        })

    if diff is not None and diff < 0:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "추세 미회복",
            "결론": "아직 시장이 중장기 상승 추세를 인정하지 않은 상태입니다.",
            "상세 수치": f"200일선 대비 {_txt(diff, '%')} / 최고점 대비 {_txt(peak_diff, '%')} / RSI {_txt(rsi)}",
            "판정": "추세 회복 확인",
        })
    elif peak_diff is not None and peak_diff < -30:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "고점 대비 낙폭",
            "결론": "낙폭이 커서 수급 전환 신호가 필요합니다.",
            "상세 수치": f"최고점 대비 {_txt(peak_diff, '%')} / 200일선 대비 {_txt(diff, '%')} / RSI {_txt(rsi)}",
            "판정": "반등 확인 후 접근",
        })

    if pbr is not None and pbr >= 5:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "높은 PBR",
            "결론": "자산 대비 프리미엄이 커서 시장 눈높이가 높습니다.",
            "상세 수치": f"PBR {_txt(pbr)} / ROE {_txt(roe, '%')}",
            "판정": "ROE 지속성 확인",
        })

    if roe is not None and roe < 8:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "ROE 약함",
            "결론": "자본 효율이 낮으면 시장이 높은 배수를 주기 어렵습니다.",
            "상세 수치": f"ROE {_txt(roe, '%')} / PER {_txt(per)} / PBR {_txt(pbr)}",
            "판정": "기업 품질 재검토",
        })

    if debt_ratio is not None and debt_ratio > 200:
        blockers.append({
            "우선순위": len(blockers) + 1,
            "핵심 원인": "부채 부담",
            "결론": "금리와 업황 둔화에 주가가 민감할 수 있습니다.",
            "상세 수치": f"부채비율 {_txt(debt_ratio, '%')} / FCF {_txt(fcf)}",
            "판정": "재무 리스크 우선 확인",
        })

    if not blockers:
        blockers.append({
            "우선순위": 1,
            "핵심 원인": "뚜렷한 저해 요인 적음",
            "결론": "보유 데이터 기준으로는 수급, 컨센서스, 뉴스 변수가 핵심입니다.",
            "상세 수치": f"PER {_txt(per)} / ROE {_txt(roe, '%')} / 200일선 대비 {_txt(diff, '%')} / 외인·기관 {_txt(foreign_supply, '%')}",
            "판정": "관찰 유지",
        })

    severe_names = {"부채 부담", "FCF 적자", "가격 부담"}
    top_names = [item["핵심 원인"] for item in blockers[:3]]
    if any(name in severe_names for name in top_names):
        decision = "매수 보류: 핵심 리스크 확인 전까지 가격보다 원인 해소가 먼저입니다."
    elif len(blockers) <= 2 and len(positives) >= 2:
        decision = "관찰 유지: 기업 체력은 있으나 상승 신호 확인이 필요합니다."
    else:
        decision = "추가 확인: 상승을 막는 요인을 수치로 하나씩 제거해야 합니다."

    return {
        "headline": f"{name}: {decision}",
        "decision": decision,
        "positives": " · ".join(positives[:4]) if positives else "강한 긍정 요인 확인 필요",
        "top_blockers": blockers[:3],
        "detail_blockers": blockers,
    }


def diagnose_why_not_rising(row: Dict[str, object]) -> Tuple[str, List[Dict[str, str]]]:
    reasons = []
    positives = []
    per = _num(row.get("per"))
    hist_per = _num(row.get("hist_per_avg"))
    pbr = _num(row.get("pbr"))
    roe = _num(row.get("roe"))
    eps_growth = _num(row.get("eps_growth"))
    revenue_growth = _num(row.get("revenue_growth"))
    operating_growth = _num(row.get("operating_growth"))
    peg = _num(row.get("peg"))
    fcf = _num(row.get("free_cashflow"))
    diff = _num(row.get("diff"))
    peak_diff = _num(row.get("peak_diff"))
    debt_ratio = _num(row.get("debt_ratio"))

    if roe is not None and roe >= 15:
        positives.append(("ROE 강함", "자본 효율이 높아 기업 체력은 긍정적으로 보임"))
    if revenue_growth is not None and revenue_growth >= 10:
        positives.append(("매출 성장", "외형 성장이 확인됨"))
    if operating_growth is not None and operating_growth >= 10:
        positives.append(("영업이익 성장", "이익 레버리지가 확인됨"))
    if per is not None and hist_per is not None and hist_per > 0 and per <= hist_per * 1.2:
        positives.append(("PER 부담 제한", "현재 PER이 과거 평균과 크게 벌어지지 않음"))
    if peg is not None and 0 < peg <= 1:
        positives.append(("PEG 양호", "이익 성장 대비 PER 부담이 낮게 계산됨"))

    if per is not None and hist_per is not None and hist_per > 0 and per > hist_per * 1.2:
        reasons.append(("밸류 부담", "현재 PER이 과거 평균보다 높아 기대치가 이미 반영됐을 수 있음"))
    elif per is not None and per >= 25:
        reasons.append(("높은 PER", "이익 성장보다 주가 기대치가 앞서 있을 수 있음"))

    if pbr is not None and pbr >= 5:
        reasons.append(("높은 PBR", "자산 대비 프리미엄이 커서 시장 눈높이가 높을 수 있음"))

    if eps_growth is None or eps_growth <= 0:
        reasons.append(("이익 성장 둔화", "EPS 성장률이 없거나 낮아 PER 확장이 제한될 수 있음"))

    if roe is not None and roe < 8:
        reasons.append(("ROE 약함", "자본 효율이 낮으면 시장이 높은 배수를 주기 어려움"))

    if fcf is None:
        reasons.append(("현금흐름 미확인", "FCF가 없으면 이익의 질을 아직 확정하기 어려움"))
    elif fcf < 0:
        reasons.append(("FCF 적자", "성장 중이어도 현금 유출이 크면 주가가 눌릴 수 있음"))

    if debt_ratio is not None and debt_ratio > 200:
        reasons.append(("부채 부담", "부채비율이 높아 금리/업황 둔화에 민감할 수 있음"))

    if diff is not None and diff < 0:
        reasons.append(("추세 미회복", "주가가 200일선 아래라 아직 시장의 확인이 부족함"))
    if peak_diff is not None and peak_diff < -30:
        reasons.append(("고점 대비 낙폭", "고점 대비 하락폭이 커서 회복에는 수급 전환 신호가 필요함"))

    if not reasons:
        reasons.append(("뚜렷한 저해 요인 적음", "현재 보유 데이터 기준으로는 추가 수급/컨센서스 확인이 핵심"))

    rows = [{"구분": "긍정", "항목": name, "해석": desc} for name, desc in positives[:4]]
    rows += [{"구분": "확인 필요", "항목": name, "해석": desc} for name, desc in reasons[:5]]

    headline_parts = []
    if positives:
        headline_parts.append(" / ".join([p[0] for p in positives[:2]]))
    if reasons:
        headline_parts.append("확인 필요: " + " / ".join([r[0] for r in reasons[:2]]))
    headline = f"{row.get('name', row.get('symbol', '선택 종목'))}: " + " | ".join(headline_parts)
    return headline, rows
