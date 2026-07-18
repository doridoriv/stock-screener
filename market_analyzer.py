from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from config import CACHE_DIR
import moving_average_data

# 시장판은 "가져온 데이터가 있으면 최대한 표시"를 목표로 한다.
# 핵심은 강세/약세를 절대값이 아니라 위험선호(risk-on) 방향으로 해석하는 것.

INDICATORS = [
    {"label": "나스닥", "symbol": "QQQ", "bullish": True, "weight": 25, "group": "growth"},
    {"label": "반도체", "symbol": "SOXX", "bullish": True, "weight": 25, "group": "semiconductor"},
    {"label": "S&P500", "symbol": "SPY", "bullish": True, "weight": 15, "group": "broad"},
    {"label": "금융", "symbol": "XLF", "bullish": True, "weight": 10, "group": "financial"},
    {"label": "미국 장기채", "symbol": "TLT", "bullish": True, "weight": 10, "group": "rates"},
    {"label": "달러인덱스", "symbol": "DX-Y.NYB", "bullish": False, "weight": 10, "group": "macro"},
    {"label": "미국10년물", "symbol": "^TNX", "bullish": False, "weight": 5, "group": "macro"},
]

MARKET_CONTEXT_CACHE_FILE = os.path.join(CACHE_DIR, "market_context_latest.json")

def _download_close(symbol: str, period: str = "9mo") -> Optional[pd.Series]:
    try:
        df = yf.download(symbol, period=period, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        if "Close" not in df.columns:
            return None

        close = df["Close"].dropna()
        if close.empty:
            return None
        return close
    except:
        return None

def _trend_metrics(close: pd.Series) -> Dict[str, float]:
    close = close.dropna()
    latest = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else float("nan")
    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else float("nan")
    ret20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else float("nan")
    ret60 = float((close.iloc[-1] / close.iloc[-61] - 1) * 100) if len(close) >= 61 else float("nan")
    return {
        "latest": latest,
        "ma20": ma20,
        "ma60": ma60,
        "ret20": ret20,
        "ret60": ret60,
    }

def _risk_score_from_metrics(metrics: Dict[str, float], bullish: bool) -> int:
    score, _ = _score_breakdown(metrics, bullish)
    return score


def _score_breakdown(metrics: Dict[str, float], bullish: bool) -> tuple[int, list[dict]]:
    direction = 1 if bullish else -1
    latest = metrics["latest"]
    checks = [
        ("20일선", latest, metrics["ma20"], 15, "above"),
        ("60일선", latest, metrics["ma60"], 15, "above"),
        ("20일 수익률", metrics["ret20"], 0, 10, "positive"),
        ("60일 수익률", metrics["ret60"], 0, 10, "positive"),
    ]
    parts = []
    score = 50
    for label, value, reference, weight, check_type in checks:
        if pd.isna(value) or pd.isna(reference):
            continue
        passed = value >= reference
        raw_points = weight if passed else -weight
        points = raw_points * direction
        score += points
        if check_type == "above":
            result = "위" if passed else "아래"
            value_text = f"{float(value):,.2f} / {float(reference):,.2f}"
        else:
            result = "상승" if passed else "하락"
            value_text = f"{float(value):+.2f}%"
        parts.append({
            "label": label,
            "result": result,
            "value_text": value_text,
            "points": int(points),
        })
    return int(max(0, min(100, score))), parts

def _state_from_score(score: float) -> str:
    if score >= 80:
        return "매우 우호"
    if score >= 65:
        return "우호"
    if score >= 50:
        return "중립"
    if score >= 35:
        return "부담"
    return "매우 부담"

def _impact_text(label: str, risk_score: Optional[float]) -> str:
    if risk_score is None:
        return "판단 보류"
    favorable = risk_score >= 65
    neutral = 50 <= risk_score < 65

    if label == "나스닥":
        if favorable:
            return "성장주 위험선호 양호"
        if neutral:
            return "성장주 방향성 제한"
        return "성장주 투자심리 부담"
    if label == "반도체":
        if favorable:
            return "반도체 종목에 우호적"
        if neutral:
            return "반도체 모멘텀 중립"
        return "반도체 종목에 부담"
    if label == "S&P500":
        if favorable:
            return "미국 대형주 흐름 양호"
        if neutral:
            return "대형주 흐름 중립"
        return "대형주 시장 체력 약함"
    if label == "금융":
        if favorable:
            return "금융주 수급 우호"
        if neutral:
            return "금융주 방향성 중립"
        return "금융주 수급 부담"
    if label == "미국 장기채":
        if favorable:
            return "장기금리 부담 완화 신호"
        if neutral:
            return "금리 부담 중립"
        return "장기금리 상승 부담"
    if label == "달러인덱스":
        if favorable:
            return "달러 약세로 수급 부담 완화"
        if neutral:
            return "달러 영향 중립"
        return "달러 강세로 외국인 수급 부담"
    if label == "미국10년물":
        if favorable:
            return "고PER 할인 부담 완화"
        if neutral:
            return "밸류에이션 부담 중립"
        return "고PER 종목 할인 요인"
    return "시장환경 참고 지표"

def _format_latest(label: str, latest: Optional[float]) -> Optional[str]:
    if latest is None or pd.isna(latest):
        return None
    if label == "미국10년물":
        return f"{latest:.2f}%"
    if label == "달러인덱스":
        return f"{latest:.1f}"
    if latest >= 100:
        return f"{latest:,.1f}"
    return f"{latest:.2f}"

def _format_pct(value: Optional[float]) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    return f"{value:+.2f}%"

def _raw_trend(metrics: Dict[str, float]) -> str:
    latest = metrics["latest"]
    ma20 = metrics["ma20"]
    ma60 = metrics["ma60"]
    ret20 = metrics["ret20"]
    ret60 = metrics["ret60"]

    bullish_marks = 0
    bearish_marks = 0

    if pd.notna(ma20):
        bullish_marks += int(latest >= ma20)
        bearish_marks += int(latest < ma20)
    if pd.notna(ma60):
        bullish_marks += int(latest >= ma60)
        bearish_marks += int(latest < ma60)
    if pd.notna(ret20):
        bullish_marks += int(ret20 >= 0)
        bearish_marks += int(ret20 < 0)
    if pd.notna(ret60):
        bullish_marks += int(ret60 >= 0)
        bearish_marks += int(ret60 < 0)

    if bullish_marks >= 3 and bullish_marks > bearish_marks:
        return "상승"
    if bearish_marks >= 3 and bearish_marks > bullish_marks:
        return "하락"
    return "중립"

def build_market_panel() -> Dict[str, object]:
    rows: List[Dict[str, object]] = []
    total_weight = sum(item["weight"] for item in INDICATORS)
    used_weight = 0
    weighted_score = 0.0

    positive_labels: List[str] = []
    negative_labels: List[str] = []

    for item in INDICATORS:
        close = _download_close(item["symbol"])
        if close is None or len(close) < 20:
            rows.append({
                "label": item["label"],
                "symbol": item["symbol"],
                "trend": "데이터없음",
                "effect": "데이터없음",
                "risk_score": None,
                "latest": None,
                "ret20": None,
                "ret60": None,
                "available": False,
                "weight": item["weight"],
            })
            continue

        metrics = _trend_metrics(close)
        risk_score, score_parts = _score_breakdown(metrics, bullish=item["bullish"])
        raw_trend = _raw_trend(metrics)

        if risk_score >= 65:
            effect = "우호"
            positive_labels.append(item["label"])
        elif risk_score < 50:
            effect = "부담"
            negative_labels.append(item["label"])
        else:
            effect = "중립"

        score_impact = round((risk_score - 50) * item["weight"] / total_weight, 1)

        if pd.notna(metrics["ret20"]) or pd.notna(metrics["ret60"]):
            used_weight += item["weight"]
            weighted_score += risk_score * item["weight"]

        rows.append({
            "label": item["label"],
            "symbol": item["symbol"],
            "trend": raw_trend,
            "effect": effect,
            "risk_score": risk_score,
            "latest": metrics["latest"],
            "ma20": metrics["ma20"],
            "ma60": metrics["ma60"],
            "ret20": metrics["ret20"],
            "ret60": metrics["ret60"],
            "latest_text": _format_latest(item["label"], metrics["latest"]),
            "ret20_text": _format_pct(metrics["ret20"]),
            "ret60_text": _format_pct(metrics["ret60"]),
            "score_impact": score_impact,
            "score_parts": score_parts,
            "meaning": _impact_text(item["label"], risk_score),
            "available": True,
            "weight": item["weight"],
        })

    if used_weight > 0:
        market_score = round(weighted_score / used_weight, 1)
    else:
        market_score = 50.0

    if market_score >= 65:
        market_state = "위험선호"
    elif market_score >= 50:
        market_state = "중립"
    else:
        market_state = "위험회피"

    if positive_labels:
        pos_text = "· ".join(dict.fromkeys(positive_labels[:3]))
    else:
        pos_text = "특정 강세 신호 미약"

    if negative_labels:
        neg_text = "· ".join(dict.fromkeys(negative_labels[:3]))
    else:
        neg_text = "특정 비우호 신호 미약"

    score_state = _state_from_score(market_score)
    if market_state == "위험선호":
        summary = f"{score_state} 구간입니다. 우호 요인: {pos_text}."
    elif market_state == "중립":
        summary = f"{score_state} 구간입니다. 우호 요인: {pos_text}. 부담 요인: {neg_text}."
    else:
        summary = f"{score_state} 구간입니다. 부담 요인: {neg_text}."

    confidence = round((sum(1 for r in rows if r["available"]) / len(rows)) * 100, 1) if rows else 0.0
    evidence_rows = sorted(
        [r for r in rows if r.get("available")],
        key=lambda r: (r.get("score_impact", 0) < 0, -abs(r.get("score_impact", 0)))
    )

    usdkrw = None
    usdkrw_close = _download_close("KRW=X", period="2y")
    if usdkrw_close is not None and not usdkrw_close.empty:
        fx_result = moving_average_data.calculate_moving_average_rows(
            usdkrw_close.tolist(),
            moving_average_data.DEFAULT_PERIODS,
        )
        usdkrw = {
            "symbol": "KRW=X",
            "name": "원·달러 환율",
            "data_date": pd.to_datetime(usdkrw_close.index[-1]).strftime("%Y-%m-%d"),
            "dates": [
                pd.to_datetime(index).strftime("%Y-%m-%d")
                for index in usdkrw_close.index[-moving_average_data.HISTORY_ROWS:]
            ],
            "values": [
                round(float(value), 6)
                for value in usdkrw_close.iloc[-moving_average_data.HISTORY_ROWS:]
            ],
            "close": fx_result["close"],
            "rows": fx_result["rows"],
            "source": "Yahoo Finance (KRW=X)",
        }

    return {
        "market_score": market_score,
        "market_state": market_state,
        "score_state": score_state,
        "summary": summary,
        "confidence": confidence,
        "rows": rows,
        "evidence_rows": evidence_rows,
        "total_weight": total_weight,
        "used_weight": used_weight,
        "usdkrw": usdkrw,
        "collected_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        "source": "yfinance",
    }

def save_market_panel_cache(path: str = MARKET_CONTEXT_CACHE_FILE) -> Dict[str, object]:
    panel = build_market_panel()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(panel, f, ensure_ascii=False, indent=2, allow_nan=False)
    return panel

def load_market_panel_cache(path: str = MARKET_CONTEXT_CACHE_FILE) -> Optional[Dict[str, object]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
