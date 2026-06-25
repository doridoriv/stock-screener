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
        rows.append({
            "항목": label,
            "확인 가능 여부": "확인" if available else missing_status,
            "이유": reason,
        })
    return rows


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
