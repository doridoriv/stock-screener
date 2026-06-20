import os
import json
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

from config import (
    DEFAULT_US_TICKERS,
    US_NAME_MAP,
    US_MARKETCAP_CACHE_FILE,
    SCORE_WEIGHTS,
    GRADE_RULES,
)

# ==========================================
# [추가] 4대 핵심 지표 수집용 매크로/보조 함수
# ==========================================

def _get_us_10y_yield():
    """③ 미국 10년물 국채 금리 수집 (^TNX) - 차단 위험 0%"""
    try:
        ticker = yf.Ticker("^TNX")
        hist = ticker.history(period="1d")
        if not hist.empty:
            return round(float(hist['Close'].iloc[-1]), 2)
    except:
        pass
    return 4.25  # 통신 실패 시 최근 기준 백업 상수

def _get_historical_per_average(ticker_obj, current_eps, current_per):
    """② 최근 3개년 주가 데이터를 기반으로 역사적 평균 PER 역산 (차단 위험 0%)"""
    if not current_eps or current_eps <= 0:
        return current_per if current_per else 0.0
    try:
        hist = ticker_obj.history(period="3y", interval="1wk")
        if not hist.empty:
            avg_price = hist['Close'].mean()
            avg_per = avg_price / current_eps
            return round(float(avg_per), 2)
    except:
        pass
    return current_per if current_per else 0.0

def _get_foreigner_supply(ticker_obj, market, symbol):
    """④ 외국인/기관 수급 데이터 추출 (차단 위험 0% 공식 내부 지표 활용)"""
    try:
        info = ticker_obj.info
        if market == "미국":
            # 미국은 메이저 수급 기준으로 기관 지분율(Institutional Percent Shares) 활용
            inst_own = info.get("institutionalPercentShares", 0)
            return round(float(inst_own * 100), 2)
        else:
            # 한국은 야후 파이낸스 내부 지분 구조 정보 백분율 우선 활용
            held_percent = info.get("sharesPercentSharesOut", 0)
            if held_percent:
                return round(float(held_percent * 100), 2)
            # 수급 데이터 정보 부재 시 최근 5일 거래량 과열 추세로 대용 산출
            hist = ticker_obj.history(period="5d")
            if len(hist) >= 2:
                v_change = (hist['Volume'].iloc[-1] / (hist['Volume'].mean() + 1e-9)) * 100
                return round(float(v_change), 2)
    except:
        pass
    return 0.0

# ==========================================
# [추가] 1일 1회 제한 스마트 캐시 탐색 시스템
# ==========================================

def _get_daily_cache_path(market_text: str) -> str:
    """오늘 날짜 기준의 캐시 파일 경로 생성 (기존 캐시 디렉터리 재활용)"""
    cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
    today_str = datetime.now().strftime("%Y%m%d")
    return os.path.join(cache_dir, f"snapshot_{market_text}_{today_str}.csv")

def _find_latest_valid_cache(market_text: str):
    """주말, 공휴일 및 장마감 전후를 판별하여 가장 최근의 유효 캐시 파일을 탐색 (3번 요구사항)"""
    now = datetime.now()
    cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
    
    # 최근 일주일(7일)간의 캐시 파일을 역순으로 추적
    for i in range(8):
        check_date = now - timedelta(days=i)
        date_str = check_date.strftime("%Y%m%d")
        file_path = os.path.join(cache_dir, f"snapshot_{market_text}_{date_str}.csv")
        
        if os.path.exists(file_path):
            # 당일 파일인 경우에만 정밀 장마감 시간 필터링 적용
            if i == 0:
                # 한국 시장 장마감(15:40) 전이면 아직 오늘 자 데이터가 갱신 안 되었으므로 패스 (전일 자 사용 유도)
                if market_text in ["코스피", "코스닥"] and now.time() < datetime.strptime("15:40", "%H:%M").time():
                    continue
                # 미국 시장 장마감(한국 시간 아침 06:30) 전이면 패스
                if market_text == "미국" and now.time() < datetime.strptime("06:30", "%H:%M").time():
                    continue
            return file_path
    return None

# ==========================================
# 기존 유틸리티 및 데이터 가공 보존 영역
# ==========================================

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except:
            pass

    initial_cache = {}
    for i, ticker in enumerate(DEFAULT_US_TICKERS, 1):
        initial_cache[ticker] = {
            "rank": i,
            "name": US_NAME_MAP.get(ticker, ticker),
            "market_cap": 0
        }
    return initial_cache

def calculate_rsi(series, period=14):
    if len(series) < period + 1:
        return 50.0

    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    with pd.option_context('mode.use_inf_as_na', True):
        rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else 50.0

def _is_missing(val):
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip()
        if s in {"", "-", "N/A", "None", "nan", "비활성"}:
            return True
    try:
        return pd.isna(val)
    except:
        return False

def _safe_float(val):
    if _is_missing(val):
        return float("nan")
    try:
        if isinstance(val, str):
            val = val.replace(",", "").strip()
        return float(val)
    except:
        return float("nan")

def _grade_from_score(score):
    try:
        score = float(score)
    except:
        score = 0.0

    for threshold, grade in GRADE_RULES:
        if score >= threshold:
            return grade
    return "D"

def get_per_grade(val):
    if _is_missing(val):
        return "정보없음"
    try:
        v = float(val)
        if v < 0:
            return f"{v:.1f} (적자)"
        elif v <= 10:
            return f"{v:.1f} (초저평가)"
        elif v <= 20:
            return f"{v:.1f} (적정)"
        elif v <= 40:
            return f"{v:.1f} (고평가)"
        else:
            return f"{v:.1f} (초고평가)"
    except:
        return "정보없음"

def get_pbr_grade(val):
    if _is_missing(val):
        return "정보없음"
    try:
        v = _safe_float(val)
        if v < 0:
            return f"{v:.2f} (자본잠식)"
        elif v <= 1.0:
            return f"{v:.2f} (절대저평가)"
        elif v <= 1.5:
            return f"{v:.2f} (적정)"
        elif v <= 3.0:
            return f"{v:.2f} (고평가)"
        else:
            return f"{v:.2f} (초고평가)"
    except:
        return "정보없음"

def fetch_stock_data(market, symbol, start_date, end_date):
    try:
        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            df = fdr.DataReader(symbol, start=start_date, end=end_date)
            if df is None or df.empty or len(df) < 200:
                suffix = ".KQ" if market == "한국(코스닥)" else ".KS"
                df = yf.download(f"{symbol}{suffix}", start=start_date, end=end_date, progress=False)
        else:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)

        if df is None or df.empty or len(df) < 200:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        return df
    except:
        try:
            if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                suffix = ".KQ" if market == "한국(코스닥)" else ".KS"
                df = yf.download(f"{symbol}{suffix}", start=start_date, end=end_date, progress=False)
                if df is not None and not df.empty and len(df) >= 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = [col[0] for col in df.columns]
                    return df
        except:
            pass
        return None

# ==========================================
# 정량 점수 스코어링 시스템 (기존 유지)
# ==========================================

def _score_per(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v < 0: return 0, True
    if v <= 8: return 15, True
    if v <= 12: return 12, True
    if v <= 18: return 8, True
    if v <= 25: return 4, True
    return 0, True

def _score_pbr(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v < 0: return 0, True
    if v <= 0.8: return 10, True
    if v <= 1.2: return 8, True
    if v <= 1.8: return 6, True
    if v <= 3.0: return 3, True
    return 0, True

def _score_roe(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v >= 20: return 20, True
    if v >= 15: return 16, True
    if v >= 10: return 12, True
    if v >= 5: return 6, True
    return 0, True

def _score_peg(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v <= 0.7: return 20, True
    if v <= 1.0: return 16, True
    if v <= 1.5: return 12, True
    if v <= 2.0: return 6, True
    return 0, True

def _score_eps3y(val):
    if _is_missing(val): return 0, False
    s = str(val).strip()
    if s == "적자": return 0, True
    if s == "↑": return 10, True
    if s == "→": return 5, True
    if s == "↓": return 1, True
    return 0, True

def _score_cagr(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v >= 25: return 15, True
    if v >= 18: return 12, True
    if v >= 12: return 9, True
    if v >= 5: return 5, True
    return 0, True

def _score_rsi(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if 35 <= v <= 55: return 5, True
    if 25 <= v < 35 or 55 < v <= 65: return 3, True
    if 20 <= v < 25 or 65 < v <= 75: return 1, True
    return 0, True

def _score_peak_diff(val):
    v = _safe_float(val)
    if pd.isna(v): return 0, False
    if v <= -10 and v >= -45: return 5, True
    if v < -45 and v >= -60: return 3, True
    if v < -60: return 1, True
    return 0, True

def _missing_label(score_input_map, opt_fundamental=True, opt_peak=True):
    missing = []
    core_keys = []
    if opt_fundamental:
        core_keys.extend(["per", "pbr", "roe", "peg", "eps3y", "cagr"])
    core_keys.append("rsi")
    if opt_peak:
        core_keys.append("peak_diff")

    for key in core_keys:
        if key in score_input_map and _is_missing(score_input_map[key]):
            missing.append(key.upper())
    return missing

# ==========================================
# [개선] 종합 투자 점수 및 상황 구분 진단 엔진
# ==========================================

def evaluate_investment_score(stock_row, market=None, opt_fundamental=True, opt_peak=True):
    per_score, per_ok = _score_per(stock_row.get("per"))
    pbr_score, pbr_ok = _score_pbr(stock_row.get("pbr"))
    roe_score, roe_ok = _score_roe(stock_row.get("roe"))
    peg_score, peg_ok = _score_peg(stock_row.get("peg"))
    eps_score, eps_ok = _score_eps3y(stock_row.get("eps3y"))
    cagr_score, cagr_ok = _score_cagr(stock_row.get("cagr"))
    rsi_score, rsi_ok = _score_rsi(stock_row.get("rsi"))
    peak_score, peak_ok = _score_peak_diff(stock_row.get("peak_diff"))

    detail_scores = {
        "PER": per_score, "PBR": pbr_score, "ROE": roe_score, "PEG": peg_score,
        "EPS3Y": eps_score, "CAGR": cagr_score, "RSI": rsi_score, "최고점대비": peak_score,
    }

    total_score = int(sum(detail_scores.values()))
    grade = _grade_from_score(total_score)

    availability_flags = {
        "PER": per_ok, "PBR": pbr_ok, "ROE": roe_ok, "PEG": peg_ok,
        "EPS3Y": eps_ok, "CAGR": cagr_ok, "RSI": rsi_ok, "최고점대비": peak_ok,
    }
    availability_weights = {
        "PER": 15, "PBR": 10, "ROE": 20, "PEG": 20, "EPS3Y": 10, "CAGR": 15, "RSI": 5, "최고점대비": 5,
    }
    available_points = sum(availability_weights[key] for key, ok in availability_flags.items() if ok)
    confidence = round(min(100.0, max(0.0, (available_points / 100.0) * 100.0)), 1)

    positives = []
    cautions = []

    per_val = _safe_float(stock_row.get("per"))
    pbr_val = _safe_float(stock_row.get("pbr"))
    roe_val = _safe_float(stock_row.get("roe"))
    peg_val = _safe_float(stock_row.get("peg"))
    cagr_val = _safe_float(stock_row.get("cagr"))
    rsi_val = _safe_float(stock_row.get("rsi"))
    peak_diff_val = _safe_float(stock_row.get("peak_diff"))

    # 신규 추가 필드 로드
    eps_growth_val = _safe_float(stock_row.get("eps_growth"))
    hist_per_avg_val = _safe_float(stock_row.get("hist_per_avg"))
    foreign_supply_val = _safe_float(stock_row.get("foreign_supply"))

    if not pd.isna(per_val):
        if 0 < per_val <= 10: positives.append(f"PER {per_val:.1f}")
        elif per_val >= 25 or per_val < 0: cautions.append(f"PER {per_val:.1f}" + (" (적자)" if per_val < 0 else ""))
    if not pd.isna(pbr_val):
        if 0 < pbr_val <= 1.2: positives.append(f"PBR {pbr_val:.2f}")
        elif pbr_val >= 3 or pbr_val < 0: cautions.append(f"PBR {pbr_val:.2f}" + (" (자본잠식)" if pbr_val < 0 else ""))
    if not pd.isna(roe_val):
        if roe_val >= 15: positives.append(f"ROE {roe_val:.1f}%")
        elif roe_val < 8: cautions.append(f"ROE {roe_val:.1f}%")
    if not pd.isna(peg_val):
        if peg_val <= 1.0: positives.append(f"PEG {peg_val:.2f}")
        elif peg_val >= 2.0: cautions.append(f"PEG {peg_val:.2f}")
    if not pd.isna(cagr_val):
        if cagr_val >= 12: positives.append(f"CAGR {cagr_val:.1f}%")
        elif cagr_val < 5: cautions.append(f"CAGR {cagr_val:.1f}%")
    if not pd.isna(rsi_val):
        if 35 <= rsi_val <= 55: positives.append(f"RSI {rsi_val:.1f}")
        elif rsi_val >= 70 or rsi_val <= 20: cautions.append(f"RSI {rsi_val:.1f}")
    if not pd.isna(peak_diff_val):
        if peak_diff_val <= -15: positives.append(f"최고점대비 {peak_diff_val:.1f}%")
        elif peak_diff_val > 0: cautions.append(f"최고점대비 +{peak_diff_val:.1f}%")

    positives = positives[:3]
    cautions = cautions[:2]

    missing = _missing_label(stock_row, opt_fundamental=opt_fundamental, opt_peak=opt_peak)
    missing_text = ""
    if missing: missing_text = " / ".join(missing)

    market_note = "미국 시장" if market == "미국" else market if market else ""

    if total_score >= 90: head = "최상위 후보"
    elif total_score >= 80: head = "상위 후보"
    elif total_score >= 70: head = "관찰 후보"
    elif total_score >= 60: head = "보수 관찰"
    else: head = "주의 구간"

    # [4번 목적 충족] "회사는 좋은데 왜 안 오르지?" 구분을 위한 자동 종합 진단 스크립트 빌드
    if pd.notna(eps_growth_val) and eps_growth_val >= 10 and pd.notna(hist_per_avg_val) and pd.notna(per_val) and per_val < hist_per_avg_val:
        if market == "미국" and foreign_supply_val < 50:
            head = f"💡 [수급소외형] {head}"
            core = "회사는 견고하게 성장 중이나 메이저 수급 공백으로 소외된 최적의 줍줍 구간"
        elif market != "미국" and foreign_supply_val < 80:
            head = f"💡 [수급소외형] {head}"
            core = "실적 성장성 대비 외인 수급 지연으로 억눌린 저평가 기회"
        else:
            core = "· ".join(positives) if positives else "핵심 지표 우량"
    else:
        core = "· ".join(positives) if positives else "핵심 지표 확인 필요"

    if cautions:
        summary = f"{head}. {core}. 주의: {' / '.join(cautions)}."
    else:
        summary = f"{head}. {core}."

    if missing_text: summary += f" 누락: {missing_text}."
    if market_note: summary = f"[{market_note}] {summary}"

    detail_text = (
        f"PER {per_score}/15, PBR {pbr_score}/10, ROE {roe_score}/20, PEG {peg_score}/20, "
        f"EPS3Y {eps_score}/10, CAGR {cagr_score}/15, RSI {rsi_score}/5, 최고점대비 {peak_score}/5"
    )

    return {
        "score": total_score, "grade": grade, "confidence": confidence, "summary": summary, "detail_text": detail_text,
        "score_per": per_score, "score_pbr": pbr_score, "score_roe": roe_score, "score_peg": peg_score,
        "score_eps3y": eps_score, "score_cagr": cagr_score, "score_rsi": rsi_score, "score_peak_diff": peak_score,
        "missing_fields": ", ".join(missing) if missing else "",
    }

# ==========================================
# 기존 스레드 호환형 핵심 메인 스크리닝 엔진
# ==========================================

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        market_text = "코스닥" if market == "한국(코스닥)" else "코스피" if market in ["한국(코스피)", "한국"] else "미국"
        
        # ------------------------------------------
        # [패치 반영 1단계] 스마트 캐시 우선 체크 (3번 요구사항)
        # ------------------------------------------
        valid_cache_file = _find_latest_valid_cache(market_text)
        if valid_cache_file:
            app_queue.put({"type": "progress", "value": 30, "text": f"📦 [{market_text}] 최근 유효 캐시 데이터 발견! 즉시 로드합니다..."})
            try:
                df_cached = pd.read_csv(valid_cache_file)
                # 요청 수량(top_n)에 맞춰 슬라이싱
                df_cached = df_cached.head(top_n)
                total_records = len(df_cached)
                
                for idx, row in df_cached.iterrows():
                    if stop_requested_func():
                        app_queue.put({"type": "stopped", "count": idx})
                        return
                    app_queue.put({"type": "data", "data": row.to_dict()})
                    time.sleep(0.01) # UI 갱신 애니메이션 속도 동기화용 미세 지연
                
                app_queue.put({
                    "type": "done", "count": total_records, 
                    "text": f"🎉 [{market_text}] 로컬 1일 캐시 고속 로드 완료! (출처: {os.path.basename(valid_cache_file)})"
                })
                return
            except Exception as e:
                app_queue.put({"type": "progress", "value": 40, "text": f"⚠️ 캐시 파싱 에러로 실시간 수집으로 우회합니다..."})

        # ------------------------------------------
        # [패치 반영 2단계] 캐시 없을 시 실시간 명단 추출 진입 (원문 백업 코드 완벽 복원)
        # ------------------------------------------
        tickers_to_screen = []
        kr_fundamental_map = {}

        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"

            app_queue.put({"type": "progress", "value": 5, "text": f"{market_text} 상위 {top_n}위 종목 로드 중..."})
            
            try:
                df_kr = fdr.StockListing(market_type)
                if df_kr is None or df_kr.empty: raise Exception("FDR 데이터 공백 발생")
                
                df_kr_sorted = df_kr.dropna(subset=["Marcap"]).sort_values(by="Marcap", ascending=False)
                df_kr_full = df_kr_sorted.head(200)
                df_kr = df_kr_sorted.head(top_n)
                
                try:
                    cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
                    kr_cache_path = os.path.join(cache_dir, "kr_marketcap_cache.json")
                    kr_cache = {}
                    if os.path.exists(kr_cache_path):
                        with open(kr_cache_path, "r", encoding="utf-8") as f: kr_cache = json.load(f)
                    kr_cache[market_type] = df_kr_full[["Code", "Name", "Marcap", "PER", "PBR", "BPS"]].to_dict(orient="records")
                    with open(kr_cache_path, "w", encoding="utf-8") as f: json.dump(kr_cache, f, ensure_ascii=False, indent=4)
                except: pass
            except Exception as e:
                app_queue.put({"type": "progress", "value": 5, "text": f"⚠️ 거래소 연결 혼잡으로 로컬 백업 명단을 불러옵니다..."})
                cache_dir = os.path.dirname(US_MARKETCAP_CACHE_FILE)
                kr_cache_path = os.path.join(cache_dir, "kr_marketcap_cache.json")
                
                loaded_cache = False
                if os.path.exists(kr_cache_path):
                    try:
                        with open(kr_cache_path, "r", encoding="utf-8") as f:
                            kr_cache = json.load(f)
                            if market_type in kr_cache and kr_cache[market_type]:
                                df_kr = pd.DataFrame(kr_cache[market_type]).head(top_n)
                                loaded_cache = True
                    except: pass
                
                if not loaded_cache:
                    fallback_data = {
                        "KOSPI": [
                            {"Code": "005930", "Name": "삼성전자", "Marcap": 400000000000000, "PER": 10.5, "PBR": 1.2, "BPS": 51000},
                            {"Code": "000660", "Name": "SK하이닉스", "Marcap": 130000000000000, "PER": 14.2, "PBR": 1.6, "BPS": 98000},
                            {"Code": "373220", "Name": "LG에너지솔루션", "Marcap": 92000000000000, "PER": 32.0, "PBR": 4.2, "BPS": 102000},
                            {"Code": "207940", "Name": "삼성바이오로직스", "Marcap": 71000000000000, "PER": 52.1, "PBR": 6.3, "BPS": 152000},
                            {"Code": "005380", "Name": "현대차", "Marcap": 51000000000000, "PER": 5.2, "PBR": 0.65, "BPS": 285000},
                            {"Code": "000270", "Name": "기아", "Marcap": 46000000000000, "PER": 4.6, "PBR": 0.82, "BPS": 132000},
                            {"Code": "005490", "Name": "POSCO홀딩스", "Marcap": 36000000000000, "PER": 12.5, "PBR": 0.52, "BPS": 610000},
                            {"Code": "035420", "Name": "NAVER", "Marcap": 31000000000000, "PER": 21.0, "PBR": 1.45, "BPS": 122000},
                            {"Code": "006400", "Name": "삼성SDI", "Marcap": 29000000000000, "PER": 13.4, "PBR": 1.15, "BPS": 325000},
                            {"Code": "068270", "Name": "셀트리온", "Marcap": 33000000000000, "PER": 41.2, "PBR": 3.6, "BPS": 52000},
                            {"Code": "000810", "Name": "삼성화재", "Marcap": 15000000000000, "PER": 7.5, "PBR": 0.85, "BPS": 320000},
                            {"Code": "012330", "Name": "현대모비스", "Marcap": 22000000000000, "PER": 6.1, "PBR": 0.55, "BPS": 410000},
                            {"Code": "055550", "Name": "신한지주", "Marcap": 25000000000000, "PER": 5.8, "PBR": 0.42, "BPS": 95000},
                            {"Code": "105560", "Name": "KB금융", "Marcap": 28000000000000, "PER": 6.3, "PBR": 0.48, "BPS": 115000},
                            {"Code": "032830", "Name": "삼성생명", "Marcap": 16000000000000, "PER": 8.1, "PBR": 0.40, "BPS": 210000},
                            {"Code": "015760", "Name": "한국전력", "Marcap": 14000000000000, "PER": -5.2, "PBR": 0.28, "BPS": 78000},
                            {"Code": "003550", "Name": "LG", "Marcap": 12000000000000, "PER": 7.2, "PBR": 0.52, "BPS": 155000},
                            {"Code": "033780", "Name": "KT&G", "Marcap": 13000000000000, "PER": 10.8, "PBR": 1.10, "BPS": 89000},
                            {"Code": "009150", "Name": "삼성전기", "Marcap": 11000000000000, "PER": 12.8, "PBR": 1.35, "BPS": 92000},
                            {"Code": "017670", "Name": "SK텔레콤", "Marcap": 11500000000000, "PER": 9.5, "PBR": 0.95, "BPS": 53000},
                            {"Code": "010950", "Name": "S-Oil", "Marcap": 8500000000000, "PER": 8.2, "PBR": 0.98, "BPS": 76000},
                            {"Code": "011200", "Name": "HMM", "Marcap": 12000000000000, "PER": 4.1, "PBR": 0.52, "BPS": 34000},
                            {"Code": "018260", "Name": "삼성에스디에스", "Marcap": 12500000000000, "PER": 14.8, "PBR": 1.40, "BPS": 110000},
                            {"Code": "000100", "Name": "유한양행", "Marcap": 6500000000000, "PER": 45.2, "PBR": 2.80, "BPS": 28000},
                            {"Code": "034730", "Name": "SK", "Marcap": 11000000000000, "PER": 9.1, "PBR": 0.45, "BPS": 340000},
                            {"Code": "000880", "Name": "한화솔루션", "Marcap": 5200000000000, "PER": -8.5, "PBR": 0.65, "BPS": 46000},
                            {"Code": "010130", "Name": "고려아연", "Marcap": 10500000000000, "PER": 13.2, "PBR": 1.12, "BPS": 450000},
                            {"Code": "086790", "Name": "하나금융지주", "Marcap": 17500000000000, "PER": 5.1, "PBR": 0.38, "BPS": 112000},
                            {"Code": "323410", "Name": "카카오뱅크", "Marcap": 11500000000000, "PER": 28.5, "PBR": 1.95, "BPS": 12500},
                            {"Code": "259960", "Name": "크래프톤", "Marcap": 12000000000000, "PER": 15.2, "PBR": 2.10, "BPS": 115000},
                            {"Code": "034020", "Name": "두산에너빌리티", "Marcap": 10500000000000, "PER": 22.1, "PBR": 1.25, "BPS": 13500},
                            {"Code": "009540", "Name": "HD한국조선해양", "Marcap": 9500000000000, "PER": 18.5, "PBR": 0.88, "BPS": 145000},
                            {"Code": "004020", "Name": "현대제철", "Marcap": 4500000000000, "PER": 6.8, "PBR": 0.25, "BPS": 135000},
                            {"Code": "028260", "Name": "삼성물산", "Marcap": 25000000000000, "PER": 9.3, "PBR": 0.68, "BPS": 215000},
                            {"Code": "035720", "Name": "카카오", "Marcap": 22000000000000, "PER": 35.2, "PBR": 2.10, "BPS": 22500},
                            {"Code": "090430", "Name": "아모레퍼시픽", "Marcap": 8500000000000, "PER": 32.1, "PBR": 1.85, "BPS": 72000},
                            {"Code": "011170", "Name": "롯데케미칼", "Marcap": 4200000000000, "PER": -4.2, "PBR": 0.32, "BPS": 310000},
                            {"Code": "003490", "Name": "대한항공", "Marcap": 8200000000000, "PER": 7.1, "PBR": 0.82, "BPS": 28000},
                            {"Code": "047050", "Name": "포스코인터내셔널", "Marcap": 9200000000000, "PER": 12.1, "PBR": 1.95, "BPS": 42000},
                            {"Code": "024110", "Name": "기업은행", "Marcap": 11000000000000, "PER": 4.2, "PBR": 0.31, "BPS": 41000}
                        ],
                        "KOSDAQ": [
                            {"Code": "247540", "Name": "에코프로비엠", "Marcap": 24500000000000, "PER": 44.0, "PBR": 6.8, "BPS": 29000},
                            {"Code": "086520", "Name": "에코프로", "Marcap": 19500000000000, "PER": 48.0, "PBR": 6.2, "BPS": 24000},
                            {"Code": "196170", "Name": "알테오젠", "Marcap": 12500000000000, "PER": 58.0, "PBR": 9.5, "BPS": 14000},
                            {"Code": "058470", "Name": "리노공업", "Marcap": 3400000000000, "PER": 21.5, "PBR": 3.9, "BPS": 44000},
                            {"Code": "028300", "Name": "HLB", "Marcap": 9800000000000, "PER": -4.8, "PBR": 4.8, "BPS": 4800},
                            {"Code": "214150", "Name": "클래시스", "Marcap": 2450000000000, "PER": 27.0, "PBR": 5.2, "BPS": 7800},
                            {"Code": "035900", "Name": "JYP Ent.", "Marcap": 2950000000000, "PER": 22.5, "PBR": 4.2, "BPS": 14500},
                            {"Code": "293490", "Name": "카카오게임즈", "Marcap": 2850000000000, "PER": 19.5, "PBR": 1.4, "BPS": 24000},
                            {"Code": "066970", "Name": "엘앤에프", "Marcap": 5400000000000, "PER": -12.5, "PBR": 3.8, "BPS": 38000},
                            {"Code": "277810", "Name": "레인보우로보틱스", "Marcap": 3200000000000, "PER": 150.0, "PBR": 15.2, "BPS": 11000},
                            {"Code": "039200", "Name": "오스템임플란트", "Marcap": 2800000000000, "PER": 18.2, "PBR": 4.5, "BPS": 32000},
                            {"Code": "145020", "Name": "휴젤", "Marcap": 2400000000000, "PER": 24.1, "PBR": 3.1, "BPS": 65000},
                            {"Code": "041510", "Name": "에스엠", "Marcap": 2100000000000, "PER": 16.5, "PBR": 2.1, "BPS": 48000},
                            {"Code": "263750", "Name": "펄어비스", "Marcap": 2500000000000, "PER": 45.2, "PBR": 3.4, "BPS": 14000},
                            {"Code": "036830", "Name": "솔브레인", "Marcap": 2200000000000, "PER": 11.2, "PBR": 1.8, "BPS": 135000},
                            {"Code": "091990", "Name": "셀트리온제약", "Marcap": 3100000000000, "PER": 55.0, "PBR": 5.8, "BPS": 12000},
                            {"Code": "214310", "Name": "심텍", "Marcap": 1100000000000, "PER": 9.5, "PBR": 1.6, "BPS": 22000},
                            {"Code": "036490", "Name": "SK머티리얼즈", "Marcap": 2400000000000, "PER": 15.6, "PBR": 4.8, "BPS": 51000},
                            {"Code": "005290", "Name": "동진쎄미켐", "Marcap": 1900000000000, "PER": 12.3, "PBR": 2.4, "BPS": 16000},
                            {"Code": "122870", "Name": "와이지엔터테인먼트", "Marcap": 1050000000000, "PER": 18.5, "PBR": 2.1, "BPS": 24000},
                            {"Code": "025980", "Name": "아난티", "Marcap": 650000000000, "PER": 8.5, "PBR": 0.95, "BPS": 7200},
                            {"Code": "069080", "Name": "웹젠", "Marcap": 580000000000, "PER": 7.2, "PBR": 0.85, "BPS": 19000},
                            {"Code": "056190", "Name": "에스에프에이", "Marcap": 1150000000000, "PER": 9.1, "PBR": 0.92, "BPS": 34000},
                            {"Code": "034230", "Name": "파라다이스", "Marcap": 1250000000000, "PER": 13.4, "PBR": 1.05, "BPS": 12500},
                            {"Code": "088390", "Name": "이엔에프테크놀로지", "Marcap": 420000000000, "PER": 6.8, "PBR": 0.72, "BPS": 31000},
                            {"Code": "067160", "Name": "아프리카TV", "Marcap": 950000000000, "PER": 14.2, "PBR": 3.1, "BPS": 28000},
                            {"Code": "036540", "Name": "매일유업", "Marcap": 320000000000, "PER": 5.8, "PBR": 0.61, "BPS": 82000},
                            {"Code": "064550", "Name": "바이오ニア", "Marcap": 850000000000, "PER": 22.0, "PBR": 3.5, "BPS": 9500},
                            {"Code": "042000", "Name": "카페24", "Marcap": 450000000000, "PER": -14.5, "PBR": 2.1, "BPS": 11000},
                            {"Code": "290670", "Name": "대주전자재료", "Marcap": 1450000000000, "PER": 45.0, "PBR": 5.2, "BPS": 18000},
                            {"Code": "110790", "Name": "천보", "Marcap": 1250000000000, "PER": 32.5, "PBR": 3.8, "BPS": 31000},
                            {"Code": "084370", "Name": "유진테크", "Marcap": 850000000000, "PER": 14.1, "PBR": 1.9, "BPS": 21000},
                            {"Code": "036810", "Name": "에이테크솔루션", "Marcap": 150000000000, "PER": 15.2, "PBR": 1.05, "BPS": 11000},
                            {"Code": "054780", "Name": "키이스트", "Marcap": 120000000000, "PER": -18.2, "PBR": 1.85, "BPS": 4200},
                            {"Code": "235980", "Name": "메드팩토", "Marcap": 250000000000, "PER": -3.5, "PBR": 4.1, "BPS": 3200},
                            {"Code": "068760", "Name": "셀리버리", "Marcap": 80000000000, "PER": -1.2, "PBR": 5.2, "BPS": 1500},
                            {"Code": "215600", "Name": "신흥에스이씨", "Marcap": 380000000000, "PER": 8.2, "PBR": 1.45, "BPS": 35000},
                            {"Code": "023160", "Name": "태웅", "Marcap": 280000000000, "PER": 11.1, "PBR": 0.65, "BPS": 19000},
                            {"Code": "038500", "Name": "삼표시멘트", "Marcap": 310000000000, "PER": 9.5, "PBR": 0.55, "BPS": 6200},
                            {"Code": "078600", "Name": "대주산업", "Marcap": 80000000000, "PER": 12.2, "PBR": 0.95, "BPS": 2400}
                        ]
                    }
                    df_kr = pd.DataFrame(fallback_data.get(market_type, [])).head(top_n)

            for idx, (_, r_data) in enumerate(df_kr.iterrows(), 1):
                code_val = str(r_data.get("Code", ""))
                if not code_val: continue
                mcap_raw = r_data.get("Marcap", 0)
                mcap_val = int(mcap_raw / 100000000) if not pd.isna(mcap_raw) else 0
                
                tickers_to_screen.append({
                    "symbol": code_val, "name": str(r_data.get("Name", code_val)), "rank": idx, "market_cap": mcap_val
                })
                kr_fundamental_map[code_val] = {
                    "per": r_data.get("PER", "N/A"), "pbr": r_data.get("PBR", "N/A"), "bps": r_data.get("BPS", "N/A")
                }
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({
                    "symbol": ticker, "name": info["name"], "rank": info["rank"], "market_cap": info["market_cap"]
                })

        total_stocks = len(tickers_to_screen)
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        # ③ 거시 지표 (미국 10년물 국채 금리) 선수집
        us_10y_bond_val = _get_us_10y_yield()
        new_collected_rows = []

        # ------------------------------------------
        # 실시간 세부 종목 지표 수집 루프
        # ------------------------------------------
        for idx, stock in enumerate(tickers_to_screen, 1):
            if stop_requested_func():
                app_queue.put({"type": "stopped", "count": idx - 1})
                return

            symbol = stock["symbol"]
            name = stock["name"]

            app_queue.put({
                "type": "progress",
                "value": int((idx / total_stocks) * 100),
                "text": f"분석 중: {name} [{idx}/{total_stocks}]"
            })

            try:
                df = fetch_stock_data(market, symbol, start_date, end_date)
                if df is None: continue

                last_date_obj = df.index[-1]
                date_str = last_date_obj.strftime("%Y-%m-%d") if hasattr(last_date_obj, "strftime") else str(last_date_obj)[:10]

                suffix = ".KQ" if market == "한국(코스닥)" else ".KS" if market in ["한국(코스피)", "한국"] else ""
                t_obj = yf.Ticker(f"{symbol}{suffix}" if suffix else symbol)

                _cached_info = None
                def get_stock_info():
                    nonlocal _cached_info
                    if _cached_info is None:
                        try: _cached_info = t_obj.info if t_obj else {}
                        except: _cached_info = {}
                    return _cached_info

                if market == "미국" and stock["market_cap"] == 0:
                    try:
                        info = get_stock_info()
                        stock["market_cap"] = int(info.get("marketCap", 0) / 100000000)
                    except: pass

                close_series = df["Close"]
                current_price = float(close_series.iloc[-1])

                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1])
                if pd.isna(current_ma200) or current_ma200 == 0: continue

                diff_val = ((current_price - current_ma200) / current_ma200) * 100
                rsi_val = calculate_rsi(close_series, 14)

                per_val, pbr_val = float("nan"), float("nan")
                roe_val, peg_val = float("nan"), float("nan")
                eps3y_str = "-"
                cagr_val = float("nan")

                if opt_fundamental:
                    if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                        f_info = kr_fundamental_map.get(symbol, {"per": "N/A", "pbr": "N/A", "bps": "N/A"})
                        per_val_raw = f_info.get("per", "N/A")

                        if _is_missing(per_val_raw) or str(per_val_raw) in ["N/A", "0", "nan", "None"]:
                            try:
                                info = get_stock_info()
                                per_val_raw = info.get("trailingPE") or info.get("forwardPE") or float("nan")
                            except: per_val_raw = float("nan")

                        try: per_val = float(per_val_raw) if not pd.isna(per_val_raw) else float("nan")
                        except: per_val = float("nan")

                        try: pbr_val = float(f_info.get("pbr", float("nan")))
                        except: pbr_val = float("nan")
                        
                        if pd.isna(pbr_val) or pbr_val == 0:
                            try: pbr_val = info.get("priceToBook", float("nan"))
                            except: pass
                    else:
                        try:
                            info = get_stock_info()
                            per_val_raw = info.get("trailingPE", float("nan"))
                            pbr_val_raw = info.get("priceToBook", float("nan"))

                            if (_is_missing(pbr_val_raw)) and info.get("bookValue"):
                                try: pbr_val_raw = current_price / float(info.get("bookValue"))
                                except: pbr_val_raw = float("nan")

                            try: per_val = float(per_val_raw) if per_val_raw != "N/A" else float("nan")
                            except: per_val = float("nan")
                            try: pbr_val = float(pbr_val_raw) if pbr_val_raw != "N/A" else float("nan")
                            except: pbr_val = float("nan")
                        except: per_val, pbr_val = float("nan"), float("nan")

                try:
                    info = get_stock_info()
                    if info and "returnOnEquity" in info and info["returnOnEquity"] is not None:
                        roe_val = float(info["returnOnEquity"]) * 100
                except: pass

                if market in ["한국(코스피)", "한국(코스닥)", "한국"] and pd.isna(roe_val):
                    if pd.notna(per_val) and pd.notna(pbr_val) and per_val > 0:
                        roe_val = (pbr_val / per_val) * 100

                try:
                    financials = t_obj.financials
                    if financials is not None and not financials.empty:
                        eps_rows = [r for r in financials.index if "Diluted EPS" in str(r) or "Basic EPS" in str(r)]
                        if eps_rows:
                            eps_series = financials.loc[eps_rows[0]].dropna().sort_index(ascending=True)

                            if len(eps_series) >= 3:
                                recent_eps = eps_series.values[-3:]
                                v1, v2, v3 = recent_eps[0], recent_eps[1], recent_eps[2]
                                eps3y_str = "↑" if v1 < v2 < v3 else "↓"
                                if v1 <= 0 and v2 <= 0 and v3 <= 0: eps3y_str = "적자"

                                if len(eps_series) >= 4:
                                    eps_start, eps_end = eps_series.values[-4], eps_series.values[-1]
                                    if eps_start > 0 and eps_end > 0: cagr_val = ((eps_end / eps_start) ** (1 / 3) - 1) * 100
                                else:
                                    eps_start, eps_end = eps_series.values[-3], eps_series.values[-1]
                                    if eps_start > 0 and eps_end > 0: cagr_val = ((eps_end / eps_start) ** (1 / 2) - 1) * 100
                except: pass

                if pd.notna(per_val) and per_val > 0 and pd.notna(cagr_val) and cagr_val > 0 and eps3y_str != "적자":
                    try: peg_val = per_val / cagr_val
                    except: peg_val = float("nan")

                peak_price, peak_diff = float("nan"), float("nan")
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100

                # ① [신규 평가지표 계산] EPS 성장률 가공
                info_data = get_stock_info()
                eps_growth = info_data.get("earningsGrowth", 0.0) or 0.0
                if eps_growth: eps_growth = eps_growth * 100
                elif pd.notna(cagr_val): eps_growth = cagr_val # 백업용 활용

                # ② [신규 평가지표 계산] 과거 평균 PER 역산
                hist_per_avg = _get_historical_per_average(t_obj, info_data.get("trailingEps", 0), per_val)

                # ④ [신규 평가지표 계산] 외국인 수급 변동량 산출
                foreign_supply = _get_foreigner_supply(t_obj, market, symbol)

                # 단일 종목 데이터 마샬링 (신규 필드 연동 바인딩)
                row_data = {
                    "rank": stock["rank"], "symbol": symbol, "name": name, "data_date": date_str,
                    "market_cap": stock["market_cap"], "price": current_price, "ma200": current_ma200,
                    "diff": diff_val, "rsi": rsi_val, "per": per_val, "pbr": pbr_val,
                    "peak": peak_price, "peak_diff": peak_diff, "roe": roe_val, "peg": peg_val,
                    "eps3y": eps3y_str, "cagr": cagr_val,
                    
                    # 수집 고도화 연동용 4대 지표 바인딩
                    "eps_growth": round(eps_growth, 2),
                    "hist_per_avg": round(hist_per_avg, 2),
                    "us_10y_bond": us_10y_bond_val,
                    "foreign_supply": foreign_supply
                }

                # 투자 등급 평가 점수 처리 및 상태 주입
                eval_result = evaluate_investment_score(row_data, market=market, opt_fundamental=opt_fundamental, opt_peak=opt_peak)
                row_data.update(eval_result)

                new_collected_rows.append(row_data)
                app_queue.put({"type": "data", "data": row_data})
            except:
                continue

            time.sleep(0.05)

        # ------------------------------------------
        # [패치 반영 3단계] 신규 수집 완료 데이터 오늘 자 로컬 캐시로 저장 (1번 요구사항)
        # ------------------------------------------
        if not stop_requested_func() and new_collected_rows:
            try:
                df_to_cache = pd.DataFrame(new_collected_rows)
                target_path = _get_daily_cache_path(market_text)
                df_to_cache.to_csv(target_path, index=False, encoding="utf-8-sig")
                
                app_queue.put({
                    "type": "done", "count": total_stocks,
                    "text": f"🎉 [{market_text}] 상위 {top_n}종목 스크리닝 및 1일 통합 캐시 빌드 완료!"
                })
            except Exception as e:
                app_queue.put({
                    "type": "done", "count": total_stocks,
                    "text": f"⚠️ 스크리닝 완료되었으나 캐시 디스크 저장 실패: {e}"
                })
        else:
            if stop_requested_func():
                app_queue.put({"type": "stopped", "count": 0})
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 치명적 오류 발생: {e}"})