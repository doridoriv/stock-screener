import requests

from config import REQUEST_TIMEOUT
from secret_utils import get_secret


FINNHUB_BASE = "https://finnhub.io/api/v1"
_FORBIDDEN_PATHS = set()


def _get(path: str, params: dict) -> object:
    if path in _FORBIDDEN_PATHS:
        return None
    api_key = get_secret("FINNHUB_API_KEY")
    if not api_key:
        return None
    query = dict(params or {})
    query["token"] = api_key.strip()
    try:
        response = requests.get(FINNHUB_BASE + path, params=query, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                _FORBIDDEN_PATHS.add(path)
            return None
        return response.json()
    except Exception:
        return None


def _buy_ratio(row: dict) -> float | None:
    strong_buy = float(row.get("strongBuy") or 0)
    buy = float(row.get("buy") or 0)
    hold = float(row.get("hold") or 0)
    sell = float(row.get("sell") or 0)
    strong_sell = float(row.get("strongSell") or 0)
    total = strong_buy + buy + hold + sell + strong_sell
    if total <= 0:
        return None
    return round(((strong_buy + buy) / total) * 100, 2)


def fetch_finnhub_metrics(symbol: str) -> dict:
    metrics = {}

    recommendations = _get("/stock/recommendation", {"symbol": symbol})
    if isinstance(recommendations, list) and recommendations:
        latest = recommendations[0]
        latest_buy_ratio = _buy_ratio(latest)
        if latest_buy_ratio is not None:
            metrics["analyst_buy_ratio"] = latest_buy_ratio
            metrics["finnhub_source"] = "Finnhub"
        if len(recommendations) > 1:
            previous_buy_ratio = _buy_ratio(recommendations[1])
            if previous_buy_ratio is not None and latest_buy_ratio is not None:
                metrics["consensus_revision"] = round(latest_buy_ratio - previous_buy_ratio, 2)

    target = _get("/stock/price-target", {"symbol": symbol})
    if isinstance(target, dict):
        for source_key, target_key in [
            ("targetMean", "target_mean"),
            ("targetHigh", "target_high"),
            ("targetLow", "target_low"),
        ]:
            value = target.get(source_key)
            if value is not None:
                try:
                    metrics[target_key] = round(float(value), 2)
                    metrics["finnhub_source"] = "Finnhub"
                except Exception:
                    pass

    earnings = _get("/stock/earnings", {"symbol": symbol, "limit": 4})
    if isinstance(earnings, list) and earnings:
        surprises = []
        for row in earnings:
            value = row.get("surprisePercent")
            if value is None:
                continue
            try:
                surprises.append(float(value))
            except Exception:
                pass
        if surprises:
            metrics["earnings_surprise_pct"] = round(sum(surprises) / len(surprises), 2)
            metrics["finnhub_source"] = "Finnhub"

    return metrics
