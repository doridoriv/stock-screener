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
            "왜 중요함": "자본 효율과 외형/이익 성장의 방향을 같이 확인",
        },
        {
            "구분": "밸류에이션",
            "내가 본 항목": f"PER {per_view} / PBR {_txt(row.get('pbr'))} / PEG {_txt(row.get('peg'))}",
            "현재 평가": per_eval,
            "왜 중요함": "좋은 회사라도 이미 비싸게 평가되면 주가가 쉬어갈 수 있음",
        },
        {
            "구분": "현금흐름",
            "내가 본 항목": f"FCF {_txt(row.get('free_cashflow'))} / 영업현금흐름 {_txt(row.get('operating_cashflow'))}",
            "현재 평가": _grade_metric(row.get("free_cashflow"), good=0, bad=0),
            "왜 중요함": "회계상 이익이 실제 현금 창출로 이어지는지 확인",
        },
        {
            "구분": "재무 안정성",
            "내가 본 항목": f"부채비율 {_txt(row.get('debt_ratio'), '%')} / 현금 {_txt(row.get('cash'))} / 순현금 {_txt(row.get('net_cash'))}",
            "현재 평가": _grade_metric(row.get("debt_ratio"), good=80, bad=200, lower_is_better=True),
            "왜 중요함": "금리 상승기와 실적 둔화기에 버틸 체력 확인",
        },
        {
            "구분": "수급",
            "내가 본 항목": f"외인/기관 보유율 {_txt(row.get('foreign_supply'), '%')}",
            "현재 평가": "참고용",
            "왜 중요함": "현재 값은 보유율 중심이라 순매수/순매도 방향 데이터가 추가로 필요",
        },
        {
            "구분": "기술적 위치",
            "내가 본 항목": f"200일선 괴리 {_txt(row.get('diff'), '%')} / 고점대비 {_txt(row.get('peak_diff'), '%')} / RSI {_txt(row.get('rsi'))}",
            "현재 평가": _grade_metric(row.get("diff"), good=0, bad=-20),
            "왜 중요함": "좋은 회사라도 시장이 아직 추세 회복을 인정하지 않을 수 있음",
        },
    ]


def missing_data_review(row: Dict[str, object]) -> List[Dict[str, str]]:
    required = [
        ("FCF", "free_cashflow", "진짜 현금 창출 여부"),
        ("영업현금흐름", "operating_cashflow", "이익의 현금 전환 확인"),
        ("현금보유액", "cash", "위기 대응 능력"),
        ("순현금/순차입금", "net_cash", "재무 부담 확인"),
        ("영업이익률", "operating_margin", "성장의 질"),
        ("순이익률", "net_margin", "최종 수익성"),
        ("외국인 순매수", "foreign_net_buy", "단기/중기 수급 방향"),
        ("기관 순매수", "institution_net_buy", "주가 방향성 수급"),
        ("컨센서스 변화", "consensus_revision", "시장 기대치 상향/하향"),
        ("경쟁사 대비 PER", "peer_per_gap", "업종 내 저평가 여부"),
    ]
    rows = []
    for label, key, reason in required:
        value = row.get(key)
        available = _num(value) is not None or (isinstance(value, str) and value.strip() not in ["", "-", "N/A", "nan"])
        rows.append({
            "항목": label,
            "확인 가능 여부": "확인" if available else "부족",
            "이유": reason,
        })
    return rows


def diagnose_why_not_rising(row: Dict[str, object]) -> Tuple[str, List[Dict[str, str]]]:
    reasons = []
    per = _num(row.get("per"))
    hist_per = _num(row.get("hist_per_avg"))
    roe = _num(row.get("roe"))
    eps_growth = _num(row.get("eps_growth"))
    fcf = _num(row.get("free_cashflow"))
    diff = _num(row.get("diff"))
    peak_diff = _num(row.get("peak_diff"))
    debt_ratio = _num(row.get("debt_ratio"))

    if per is not None and hist_per is not None and hist_per > 0 and per > hist_per * 1.2:
        reasons.append(("밸류 부담", "현재 PER이 과거 평균보다 높아 기대치가 이미 반영됐을 수 있음"))
    elif per is not None and per >= 25:
        reasons.append(("높은 PER", "이익 성장보다 주가 기대치가 앞서 있을 수 있음"))

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

    rows = [{"가능한 원인": name, "해석": desc} for name, desc in reasons[:5]]
    headline = f"{row.get('name', row.get('symbol', '선택 종목'))}: " + " + ".join([r[0] for r in reasons[:3]])
    return headline, rows
