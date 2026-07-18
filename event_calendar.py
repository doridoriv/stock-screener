from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from yfinance.calendars import CalendarQuery

from config import CACHE_DIR, REQUEST_TIMEOUT


EVENT_CALENDAR_CACHE_FILE = os.path.join(CACHE_DIR, "event_calendar_latest.json")
KST = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")
FED_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_SOURCE = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_CPI_SOURCE = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_EMPLOYMENT_SOURCE = "https://www.bls.gov/schedule/news_release/empsit.htm"
BEA_SOURCE = "https://www.bea.gov/news/schedule/full"
BOK_SOURCE = "https://www.bok.or.kr/portal/bbs/B0000502/view.do?menuNo=201265&nttId=10094300"


FOMC_MEETINGS = {
    2026: [(1, 28, False), (3, 18, True), (4, 29, False), (6, 17, True), (7, 29, False), (9, 16, True), (10, 28, False), (12, 9, True)],
    2027: [(1, 27, False), (3, 17, True), (4, 28, False), (6, 9, True), (7, 28, False), (9, 15, True), (10, 27, False), (12, 8, True)],
}

BOK_POLICY_MEETINGS = {
    2026: [(1, 15), (2, 12), (4, 10), (5, 14), (7, 16), (8, 13), (10, 22), (11, 12)],
}

# Official 2026 schedules keep the calendar useful when agency pages reject or
# change automated requests. Live collectors overwrite matching entries.
BLS_RELEASES_2026 = [
    ("2026-01-13", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-02-13", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-03-11", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-04-10", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-05-12", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-06-10", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-07-14", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-08-12", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-09-11", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-10-14", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-11-10", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-12-10", "미국 소비자물가지수(CPI)", "물가", BLS_CPI_SOURCE),
    ("2026-01-09", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-02-11", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-03-06", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-04-03", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-05-08", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-06-05", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-07-02", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-08-07", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-09-04", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-10-02", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-11-06", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
    ("2026-12-04", "미국 고용보고서", "고용", BLS_EMPLOYMENT_SOURCE),
]

BEA_RELEASES_2026 = [
    ("2026-07-30", "미국 GDP 발표", "성장", "2분기 속보치"),
    ("2026-07-30", "미국 개인소득·PCE 발표", "물가", "6월"),
    ("2026-08-26", "미국 GDP 발표", "성장", "2분기 수정치"),
    ("2026-08-26", "미국 개인소득·PCE 발표", "물가", "7월"),
    ("2026-09-30", "미국 GDP 발표", "성장", "2분기 확정치"),
    ("2026-09-30", "미국 개인소득·PCE 발표", "물가", "8월"),
    ("2026-10-29", "미국 GDP 발표", "성장", "3분기 속보치"),
    ("2026-10-29", "미국 개인소득·PCE 발표", "물가", "9월"),
    ("2026-11-25", "미국 GDP 발표", "성장", "3분기 수정치"),
    ("2026-11-25", "미국 개인소득·PCE 발표", "물가", "10월"),
    ("2026-12-23", "미국 GDP 발표", "성장", "3분기 확정치"),
    ("2026-12-23", "미국 개인소득·PCE 발표", "물가", "11월"),
]


def _event_id(*parts: object) -> str:
    return "|".join(str(part).strip().lower() for part in parts if str(part).strip())


def _event(
    event_date: str,
    title: str,
    category: str,
    market: str,
    source: str,
    source_url: str,
    *,
    time_kst: str = "",
    symbol: str = "",
    name: str = "",
    detail: str = "",
    importance: str = "주요",
    status: str = "확정",
) -> dict:
    return {
        "id": _event_id(event_date, category, symbol, title),
        "date": event_date,
        "title": title,
        "category": category,
        "market": market,
        "time_kst": time_kst,
        "symbol": symbol,
        "name": name,
        "detail": detail,
        "importance": importance,
        "status": status,
        "source": source,
        "source_url": source_url,
    }


def _to_kst_event_date(value: datetime) -> tuple[str, str]:
    local = value.astimezone(KST)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M KST")


def collect_fomc_events(start: date, end: date) -> list[dict]:
    events = []
    for year, meetings in FOMC_MEETINGS.items():
        for month, end_day, has_projection in meetings:
            release = datetime(year, month, end_day, 14, 0, tzinfo=NEW_YORK)
            event_date, time_kst = _to_kst_event_date(release)
            parsed = date.fromisoformat(event_date)
            if start <= parsed <= end:
                title = "FOMC 금리결정·경제전망" if has_projection else "FOMC 금리결정"
                events.append(_event(
                    event_date, title, "금리", "미국", "Federal Reserve", FED_SOURCE,
                    time_kst=time_kst,
                    detail="미 연준 통화정책 결정",
                    importance="매우 중요",
                ))
    return events


def collect_bok_events(start: date, end: date) -> list[dict]:
    events = []
    for year, meetings in BOK_POLICY_MEETINGS.items():
        for month, day in meetings:
            event_date = date(year, month, day)
            if start <= event_date <= end:
                events.append(_event(
                    event_date.isoformat(), "한국은행 기준금리 결정", "금리", "한국",
                    "한국은행", BOK_SOURCE, detail="금융통화위원회 통화정책방향 결정회의", importance="매우 중요",
                ))
    return events


def collect_official_schedule_fallback_events(start: date, end: date) -> list[dict]:
    events = []
    for raw_date, title, category, source_url in BLS_RELEASES_2026:
        release = datetime.combine(date.fromisoformat(raw_date), datetime.min.time()).replace(
            hour=8, minute=30, tzinfo=NEW_YORK
        )
        event_date, time_kst = _to_kst_event_date(release)
        if start <= date.fromisoformat(event_date) <= end:
            events.append(_event(
                event_date,
                title,
                category,
                "미국",
                "U.S. Bureau of Labor Statistics",
                source_url,
                time_kst=time_kst,
                detail="공식 2026 발표 일정",
                importance="매우 중요",
            ))

    for raw_date, title, category, detail in BEA_RELEASES_2026:
        release = datetime.combine(date.fromisoformat(raw_date), datetime.min.time()).replace(
            hour=8, minute=30, tzinfo=NEW_YORK
        )
        event_date, time_kst = _to_kst_event_date(release)
        if start <= date.fromisoformat(event_date) <= end:
            events.append(_event(
                event_date,
                title,
                category,
                "미국",
                "U.S. Bureau of Economic Analysis",
                BEA_SOURCE,
                time_kst=time_kst,
                detail=detail,
                importance="매우 중요",
            ))
    return events


def _unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _parse_ics_datetime(key: str, raw_value: str) -> Optional[datetime]:
    value = raw_value.strip().rstrip("Z")
    formats = ["%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"]
    parsed = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    if raw_value.strip().endswith("Z"):
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    timezone_match = re.search(r"TZID=([^;:]+)", key)
    timezone = NEW_YORK
    if timezone_match:
        try:
            timezone = ZoneInfo(timezone_match.group(1))
        except Exception:
            timezone = NEW_YORK
    return parsed.replace(tzinfo=timezone)


def collect_bls_events(start: date, end: date, session: Optional[requests.Session] = None) -> list[dict]:
    client = session or requests.Session()
    response = client.get(BLS_SOURCE, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    tracked = {
        "consumer price index": ("미국 소비자물가지수(CPI)", "물가", "매우 중요"),
        "employment situation": ("미국 고용보고서", "고용", "매우 중요"),
        "producer price index": ("미국 생산자물가지수(PPI)", "물가", "주요"),
        "job openings and labor turnover": ("미국 구인·이직보고서(JOLTS)", "고용", "주요"),
        "employment cost index": ("미국 고용비용지수", "고용", "주요"),
    }
    events = []
    current: dict[str, str] = {}
    for line in _unfold_ics(response.text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            summary = current.get("SUMMARY", "")
            matched = next((meta for needle, meta in tracked.items() if needle in summary.lower()), None)
            if matched and current.get("DTSTART"):
                parsed = _parse_ics_datetime(current.get("DTSTART_KEY", "DTSTART"), current["DTSTART"])
                if parsed:
                    event_date, time_kst = _to_kst_event_date(parsed)
                    day = date.fromisoformat(event_date)
                    if start <= day <= end:
                        title, category, importance = matched
                        events.append(_event(
                            event_date, title, category, "미국", "U.S. Bureau of Labor Statistics", BLS_SOURCE,
                            time_kst=time_kst, detail=summary, importance=importance,
                        ))
            current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        base_key = key.split(";", 1)[0]
        if base_key in {"SUMMARY", "DTSTART"}:
            current[base_key] = value.replace("\\,", ",").replace("\\n", " ")
            current[f"{base_key}_KEY"] = key
    return events


def collect_bea_events(start: date, end: date, session: Optional[requests.Session] = None) -> list[dict]:
    client = session or requests.Session()
    response = client.get(BEA_SOURCE, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    events = []
    for table in tables:
        normalized = {str(column).lower(): column for column in table.columns}
        date_col = next((column for key, column in normalized.items() if "date" in key), None)
        time_col = next((column for key, column in normalized.items() if "time" in key), None)
        title_col = next((column for key, column in normalized.items() if "release" in key or "title" in key), None)
        if date_col is None or title_col is None:
            continue
        for _, row in table.iterrows():
            title_raw = str(row.get(title_col, ""))
            title_lower = title_raw.lower()
            if "gdp" in title_lower:
                title = "미국 GDP 발표"
                category = "성장"
                importance = "매우 중요"
            elif "personal income and outlays" in title_lower:
                title = "미국 개인소득·PCE 발표"
                category = "물가"
                importance = "매우 중요"
            else:
                continue
            raw_date = str(row.get(date_col, "")).strip()
            raw_time = str(row.get(time_col, "8:30 AM")).strip() if time_col is not None else "8:30 AM"
            parsed = pd.to_datetime(f"{raw_date} {datetime.now().year} {raw_time}", errors="coerce")
            if pd.isna(parsed):
                parsed = pd.to_datetime(f"{raw_date} {raw_time}", errors="coerce")
            if pd.isna(parsed):
                continue
            release = parsed.to_pydatetime().replace(tzinfo=NEW_YORK)
            event_date, time_kst = _to_kst_event_date(release)
            day = date.fromisoformat(event_date)
            if start <= day <= end:
                events.append(_event(
                    event_date, title, category, "미국", "U.S. Bureau of Economic Analysis", BEA_SOURCE,
                    time_kst=time_kst, detail=title_raw, importance=importance,
                ))
    return events


def collect_finnhub_earnings(
    start: date,
    end: date,
    symbols: Iterable[str],
    names: Optional[dict[str, str]] = None,
    api_key: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    token = api_key or os.getenv("FINNHUB_API_KEY", "").strip()
    allowed = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    if not token or not allowed:
        return []
    client = session or requests.Session()
    response = client.get(
        "https://finnhub.io/api/v1/calendar/earnings",
        params={"from": start.isoformat(), "to": end.isoformat(), "token": token},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"Finnhub earnings calendar error: {payload['error']}")
    rows = payload.get("earningsCalendar")
    if not isinstance(rows, list):
        raise ValueError("Finnhub earnings calendar response is missing earningsCalendar")
    events = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        raw_event_date = str(row.get("date", ""))
        if symbol not in allowed:
            continue
        try:
            day = date.fromisoformat(raw_event_date)
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        hour = str(row.get("hour", "")).lower()
        time_label = "장 시작 전" if hour == "bmo" else "장 마감 후" if hour == "amc" else "시간 미정"
        event_date = (day + timedelta(days=1)).isoformat() if hour == "amc" else day.isoformat()
        name = (names or {}).get(symbol, symbol)
        estimate = row.get("epsEstimate")
        detail = f"예상 EPS {estimate}" if estimate is not None else "실적 발표 예정"
        events.append(_event(
            event_date, f"{name} 실적 발표", "실적", "미국", "Finnhub", "https://finnhub.io/",
            time_kst=time_label, symbol=symbol, name=name, detail=detail, importance="기업", status="예상",
        ))
    return events


def _calendar_query_for_tickers(tickers: list[str], start: date, end: date) -> CalendarQuery:
    ticker_operands = [CalendarQuery("eq", ["ticker", ticker]) for ticker in tickers]
    ticker_query = ticker_operands[0] if len(ticker_operands) == 1 else CalendarQuery("or", ticker_operands)
    return CalendarQuery(
        "and",
        [
            ticker_query,
            CalendarQuery(
                "or",
                [
                    CalendarQuery("eq", ["eventtype", "EAD"]),
                    CalendarQuery("eq", ["eventtype", "ERA"]),
                ],
            ),
            CalendarQuery("gte", ["startdatetime", start.isoformat()]),
            CalendarQuery("lte", ["startdatetime", end.isoformat()]),
        ],
    )


def _format_eps_estimate(value: object) -> str:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return ""
    number = float(number)
    return f"{number:,.0f}" if abs(number) >= 100 else f"{number:,.2f}"


def collect_yahoo_earnings(
    start: date,
    end: date,
    earnings_universes: Optional[dict[str, list[dict]]] = None,
    calendar_client=None,
) -> list[dict]:
    records_by_ticker = {}
    for market, records in (earnings_universes or {}).items():
        for record in records or []:
            yahoo_symbol = str(record.get("yahoo_symbol") or record.get("symbol") or "").strip().upper()
            symbol = str(record.get("symbol") or "").strip().upper()
            if not yahoo_symbol or not symbol:
                continue
            records_by_ticker[yahoo_symbol] = {
                "market": market,
                "symbol": symbol,
                "name": str(record.get("name") or symbol),
            }
    if not records_by_ticker:
        return []

    if calendar_client is None:
        yf.set_tz_cache_location(os.path.join(CACHE_DIR, "yfinance_runtime"))
        calendar_client = yf.Calendars()

    events = []
    tickers = sorted(records_by_ticker)
    chunk_size = 35
    for offset in range(0, len(tickers), chunk_size):
        chunk = tickers[offset:offset + chunk_size]
        query = _calendar_query_for_tickers(chunk, start, end)
        frame = calendar_client._get_data(
            "sp_earnings", query, limit=100, offset=0, force=True,
        )
        if frame is None or frame.empty:
            continue
        for yahoo_symbol, row in frame.iterrows():
            yahoo_symbol = str(yahoo_symbol).strip().upper()
            metadata = records_by_ticker.get(yahoo_symbol)
            if not metadata:
                continue
            timestamp = pd.to_datetime(row.get("Event Start Date"), errors="coerce", utc=True)
            if pd.isna(timestamp):
                continue
            local = timestamp.to_pydatetime().astimezone(KST)
            event_day = local.date()
            if not (start <= event_day <= end + timedelta(days=1)):
                continue

            timing = str(row.get("Timing") or "").upper()
            timing_label = {"BMO": "장 시작 전", "AMC": "장 마감 후", "TNS": "시간 미정"}.get(timing, "시간 미정")
            time_label = timing_label if timing_label == "시간 미정" else f"{local.strftime('%H:%M KST')} · {timing_label}"
            raw_event_name = str(row.get("Event Name") or "")
            quarter_match = re.search(r"Q(\d)\s+(\d{4})", raw_event_name, re.IGNORECASE)
            detail_parts = []
            if quarter_match:
                detail_parts.append(f"{quarter_match.group(2)}년 {quarter_match.group(1)}분기")
            estimate = _format_eps_estimate(row.get("EPS Estimate"))
            if estimate:
                detail_parts.append(f"예상 EPS {estimate}")
            detail = " · ".join(detail_parts) or "실적 발표 예정"
            name = metadata["name"]
            source_url = f"https://finance.yahoo.com/quote/{yahoo_symbol}/"
            events.append(_event(
                event_day.isoformat(), f"{name} 실적 발표", "실적", metadata["market"],
                "Yahoo Finance", source_url, time_kst=time_label,
                symbol=metadata["symbol"], name=name, detail=detail,
                importance="기업", status="예상",
            ))
    return events


def _deduplicate(events: Iterable[dict]) -> list[dict]:
    unique = {}
    source_priority = {"Yahoo Finance": 1, "Finnhub": 2}
    for event in events:
        if not event.get("date") or not event.get("title"):
            continue
        if event.get("category") == "실적" and event.get("symbol"):
            identity = _event_id(event["date"], event["category"], event["symbol"])
        else:
            identity = event.get("id") or _event_id(event["date"], event["title"])
        current = unique.get(identity)
        if current and source_priority.get(current.get("source"), 0) > source_priority.get(event.get("source"), 0):
            continue
        unique[identity] = event
    return sorted(unique.values(), key=lambda event: (event["date"], event.get("time_kst", ""), event["title"]))


def save_event_calendar_cache(
    us_symbols: Iterable[str] = (),
    us_names: Optional[dict[str, str]] = None,
    path: str = EVENT_CALENDAR_CACHE_FILE,
    earnings_universes: Optional[dict[str, list[dict]]] = None,
) -> dict:
    today = datetime.now(KST).date()
    start = today - timedelta(days=365)
    end = today + timedelta(days=365)
    official_fallbacks = collect_official_schedule_fallback_events(start, end)
    events = collect_fomc_events(start, end) + collect_bok_events(start, end) + official_fallbacks
    sources = {
        "Federal Reserve": "ok",
        "한국은행": "ok",
        "BLS official schedule": f"ok:{sum(event['source'].startswith('U.S. Bureau of Labor Statistics') for event in official_fallbacks)}",
        "BEA official schedule": f"ok:{sum(event['source'].startswith('U.S. Bureau of Economic Analysis') for event in official_fallbacks)}",
    }
    earnings_universes = dict(earnings_universes or {})
    if not earnings_universes.get("미국") and us_symbols:
        earnings_universes["미국"] = [
            {"symbol": str(symbol).upper(), "yahoo_symbol": str(symbol).upper(), "name": (us_names or {}).get(str(symbol).upper(), str(symbol).upper())}
            for symbol in us_symbols
        ]
    earnings_start = max(start, today - timedelta(days=30))
    earnings_end = min(end, today + timedelta(days=90))
    collectors = [
        ("BLS", lambda: collect_bls_events(start, end)),
        ("BEA", lambda: collect_bea_events(start, end)),
        ("Yahoo Finance", lambda: collect_yahoo_earnings(earnings_start, earnings_end, earnings_universes)),
    ]
    token = os.getenv("FINNHUB_API_KEY", "").strip()
    if token:
        collectors.append(("Finnhub", lambda: collect_finnhub_earnings(today, earnings_end, us_symbols, us_names, token)))
    else:
        sources["Finnhub"] = "disabled:no_api_key"
    for source, collector in collectors:
        try:
            collected = collector()
            events.extend(collected)
            sources[source] = f"ok:{len(collected)}"
        except Exception as exc:
            sources[source] = f"error:{type(exc).__name__}"

    payload = {
        "version": 2,
        "collected_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "events": _deduplicate(events),
        "sources": sources,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(temp_path, path)
    return payload


def load_event_calendar_cache(path: str = EVENT_CALENDAR_CACHE_FILE) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload.get("events"), list):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
