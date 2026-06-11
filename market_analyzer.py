from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

# 시장판은 "가져온 데이터가 있으면 최대한 표시"를 목표로 한다.
# 핵심은 강세/약세를 절대값이 아니라 위험선호(risk-on) 방향으로 해석하는 것.

INDICATORS = [
    {"label": "나스닥", "symbol": "QQQ", "bullish": True, "weight": 25, "group": "growth"},
    {"label": "반도체", "symbol": "SOXX", "bullish": True, "weight": 25, "group": "semiconductor"},
    {"label": "S&P500", "symbol": "SPY", "bullish": True, "weight": 15, "group": "broad"},
    {"label": "금융", "symbol": "XLF", "bullish": True, "weight": 10, "group": "financial"},
    {"label": "장기채", "symbol": "TLT", "bullish": False, "weight": 10, "group": "defensive"},
    {"label": "달러인덱스", "symbol": "DX-Y.NYB", "bullish": False, "weight": 10, "group": "macro"},
    {"label": "미국10년물", "symbol": "^TNX", "bullish": False, "weight": 5, "group": "macro"},
]

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
    score = 50

    latest = metrics["latest"]
    ma20 = metrics["ma20"]
    ma60 = metrics["ma60"]
    ret20 = metrics["ret20"]
    ret60 = metrics["ret60"]

    if pd.notna(ma20):
        score += 15 if latest >= ma20 else -15
    if pd.notna(ma60):
        score += 15 if latest >= ma60 else -15
    if pd.notna(ret20):
        score += 10 if ret20 >= 0 else -10
    if pd.notna(ret60):
        score += 10 if ret60 >= 0 else -10

    score = max(0, min(100, score))

    if not bullish:
        score = 100 - score

    return int(max(0, min(100, score)))


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
                "trend_note": "데이터 없음",
                "effect_note": "데이터 없음",
            })
            continue

        metrics = _trend_metrics(close)
        risk_score = _risk_score_from_metrics(metrics, bullish=item["bullish"])
        raw_trend = _raw_trend(metrics)

        if risk_score >= 70:
            effect = "우호적"
            effect_note = "위험자산 선호"
            positive_labels.append(item["label"])
        elif risk_score <= 30:
            effect = "비우호적"
            effect_note = "방어 선호"
            negative_labels.append(item["label"])
        else:
            effect = "중립"
            effect_note = "중립"
        
        if raw_trend == "상승":
            trend_note = "우상향 흐름"
        elif raw_trend == "하락":
            trend_note = "우하향 흐름"
        else:
            trend_note = "방향성 혼재"

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
            "ret20": metrics["ret20"],
            "ret60": metrics["ret60"],
            "available": True,
            "weight": item["weight"],
            "trend_note": trend_note,
            "effect_note": effect_note,
        })

    if used_weight > 0:
        market_score = round(weighted_score / used_weight, 1)
    else:
        market_score = 50.0

    if market_score >= 70:
        market_state = "위험선호"
        market_state_note = "성장/리스크 자산 우호"
    elif market_score >= 55:
        market_state = "중립"
        market_state_note = "방향성 혼재"
    else:
        market_state = "위험회피"
        market_state_note = "방어 성향 우세"

    if positive_labels:
        pos_text = "· ".join(dict.fromkeys(positive_labels[:3]))
    else:
        pos_text = "특정 강세 신호 미약"

    if negative_labels:
        neg_text = "· ".join(dict.fromkeys(negative_labels[:3]))
    else:
        neg_text = "특정 비우호 신호 미약"

    if market_state == "위험선호":
        summary = f"현재는 위험자산 선호 구간입니다. {pos_text}가 우호적입니다."
    elif market_state == "중립":
        summary = f"시장 방향성이 혼재되어 있습니다. {pos_text} / {neg_text}를 함께 봐야 합니다."
    else:
        summary = f"현재는 방어 성향이 우세합니다. {neg_text}가 부담 요인입니다."

    confidence = round((sum(1 for r in rows if r["available"]) / len(rows)) * 100, 1) if rows else 0.0

    return {
        "market_score": market_score,
        "market_state": market_state,
        "market_state_note": market_state_note,
        "summary": summary,
        "confidence": confidence,
        "rows": rows,
        "total_weight": total_weight,
        "used_weight": used_weight,
    }