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
        "status": "확정",
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
    rows = payload.get("earningsCalendar") or []
    events = []
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        event_date = str(row.get("date", ""))
        if symbol not in allowed:
            continue
        try:
            day = date.fromisoformat(event_date)
        except ValueError:
            continue
        if not (start <= day <= end):
            continue
        hour = str(row.get("hour", "")).lower()
        time_label = "장 시작 전" if hour == "bmo" else "장 마감 후" if hour == "amc" else "시간 미정"
        name = (names or {}).get(symbol, symbol)
        estimate = row.get("epsEstimate")
        detail = f"예상 EPS {estimate}" if estimate is not None else "실적 발표 예정"
        events.append(_event(
            event_date, f"{name} 실적 발표", "실적", "미국", "Finnhub", "https://finnhub.io/",
            time_kst=time_label, symbol=symbol, name=name, detail=detail, importance="기업",
        ))
    return events


def _deduplicate(events: Iterable[dict]) -> list[dict]:
    unique = {}
    for event in events:
        if not event.get("date") or not event.get("title"):
            continue
        unique[event.get("id") or _event_id(event["date"], event["title"])] = event
    return sorted(unique.values(), key=lambda event: (event["date"], event.get("time_kst", ""), event["title"]))


def save_event_calendar_cache(
    us_symbols: Iterable[str] = (),
    us_names: Optional[dict[str, str]] = None,
    path: str = EVENT_CALENDAR_CACHE_FILE,
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
    collectors = [
        ("BLS", lambda: collect_bls_events(start, end)),
        ("BEA", lambda: collect_bea_events(start, end)),
        ("Finnhub", lambda: collect_finnhub_earnings(start, min(end, today + timedelta(days=90)), us_symbols, us_names)),
    ]
    for source, collector in collectors:
        try:
            collected = collector()
            events.extend(collected)
            sources[source] = f"ok:{len(collected)}"
        except Exception as exc:
            sources[source] = f"error:{type(exc).__name__}"

    payload = {
        "version": 1,
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
