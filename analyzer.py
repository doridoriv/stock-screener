import os
import json
import time
from datetime import datetime
import pandas as pd
import yfinance as yf
from config import (
    DEFAULT_US_TICKERS, US_NAME_MAP, 
    DEFAULT_KOSPI_TICKERS, KOSPI_NAME_MAP, 
    DEFAULT_KOSDAQ_TICKERS, KOSDAQ_NAME_MAP, 
    US_MARKETCAP_CACHE_FILE
)

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    initial_cache = {}
    for i, ticker in enumerate(DEFAULT_US_TICKERS, 1):
        initial_cache[ticker] = {"rank": i, "name": US_NAME_MAP.get(ticker, ticker), "market_cap": 0}
    return initial_cache

def calculate_rsi(series, period=14):
    if len(series) < period:
        return 50.0
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else 50.0

def evaluate_stock_grade(row):
    """
    04 스크리너해석 v2 규칙 기반 종합 가점 평가 엔진
    """
    score = 0
    reasons = []
    
    per = row.get("per")
    pbr = row.get("pbr")
    roe = row.get("roe")
    peg = row.get("peg")
    cagr = row.get("cagr")
    eps3y = str(row.get("eps3y", ""))

    # 1. PER 평가
    if pd.notna(per):
        if per <= 0:
            reasons.append("PER 적자")
        elif 5 <= per <= 10:
            score += 25
            reasons.append("PER 최적 저평가(5~10)")
        elif 10 <= per <= 15:
            score += 15
            reasons.append("PER 적정 저평가(10~15)")
        elif 15 <= per <= 20:
            score += 5
        elif per > 20:
            score -= 10
            reasons.append("밸류에이션 고평가")
            
    # 2. PBR 평가
    if pd.notna(pbr):
        if pbr <= 0:
            reasons.append("PBR 위험군")
        elif pbr <= 1.0:
            score += 20
            reasons.append("PBR 1배 이하 자산 메리트")
        elif 1.0 < pbr <= 2.0:
            score += 10
        elif pbr > 3.0:
            score -= 5

    # 3. ROE 평가
    if pd.notna(roe):
        if roe >= 15:
            score += 25
            reasons.append("ROE 15% 이상 우수 고수익성")
        elif 10 <= roe < 15:
            score += 15
        elif roe < 5:
            score -= 10
            reasons.append("ROE 5% 미만 효율성 저하")

    # 4. PEG / CAGR 성장성 평가
    if pd.notna(peg) and peg > 0:
        if peg <= 1.0:
            score += 15
            reasons.append("성장성 대비 매력적인 가격(PEG≤1)")
        elif peg >= 1.5:
            score -= 5

    if pd.notna(cagr):
        if cagr >= 15:
            score += 15
            reasons.append("3개년 고속 성장 흐름 유지")
        elif 5 <= cagr < 15:
            score += 5
        elif cagr < 0:
            score -= 10
            reasons.append("이익 역성장 리스크 가중")

    # 5. EPS 3개년 연속성 모멘텀 평가
    if "↑" in eps3y or "지속성장" in eps3y:
        score += 10
    elif "↓" in eps3y or "쇠퇴" in eps3y:
        score -= 15

    # 가점 기반 등급 판정 및 맞춤 한줄평 세팅
    if score >= 75:
        grade = "A"
        comment = "싸고 펀더멘털과 성장성이 완벽하게 결합된 핵심 최우선 관찰 종목! " + (reasons[0] if reasons else "")
    elif score >= 45:
        grade = "B"
        comment = "엄청 싸진 않지만 기초 체력과 실적 모멘텀이 충분히 탄탄한 우량 우상향 기업"
    elif score >= 15:
        grade = "C"
        comment = "성장성 혹은 가치 메리트 중 어느 한 축이 정체되어 있어 보수적 관망 권장"
    else:
        grade = "D"
        comment = "고평가 국면이거나 수익성·성장성 훼손 징후 뚜렷. 단기 리스크 관리 절대 주의"
        
    return grade, comment

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental=True, opt_peak=True, us_market_cap_data=None):
    """
    [방법 B 적용]: fdr 호출을 전면 제거하고 yfinance 고정 풀링 리스트로 통일 및 장중 결측치 예외 완벽 제어
    """
    try:
        # 시장 선택 분기 로직 전면 재조정
        if market == "미국":
            source_tickers = list(us_market_cap_data.keys())[:top_n] if us_market_cap_data else DEFAULT_US_TICKERS[:top_n]
        elif "코스피" in market:
            source_tickers = DEFAULT_KOSPI_TICKERS[:top_n]
        else:
            source_tickers = DEFAULT_KOSDAQ_TICKERS[:top_n]

        for idx, symbol in enumerate(source_tickers):
            if stop_requested_func():
                app_queue.put({"type": "info", "text": "⏹ 사용자의 요청으로 스크리닝 분석을 즉시 중지합니다."})
                break

            # 종목명과 기본 정보 매핑 매커니즘 분기
            if market == "미국":
                name = us_market_cap_data[symbol]["name"] if us_market_cap_data else US_NAME_MAP.get(symbol, symbol)
                mcap = us_market_cap_data[symbol]["market_cap"] if us_market_cap_data else 0
            elif "코스피" in market:
                name = KOSPI_NAME_MAP.get(symbol, symbol)
                mcap = 0
            else:
                name = KOSDAQ_NAME_MAP.get(symbol, symbol)
                mcap = 0

            try:
                ticker_obj = yf.Ticker(symbol)
                # 장중 가용 실시간 캔들 수집을 위해 1y 데이터 로드 및 결측 처리 보강
                hist = ticker_obj.history(period="1y")
                if hist.empty:
                    continue

                hist = hist.dropna(subset=['Close'])
                if len(hist) < 5:
                    continue

                close_series = hist['Close']
                current_price = float(close_series.iloc[-1])
                date_str = hist.index[-1].strftime('%Y-%m-%d')

                # 지표 산출
                rsi_val = calculate_rsi(close_series, 14)
                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1]) if not pd.isna(ma200_series.iloc[-1]) else current_price
                diff_val = ((current_price - current_ma200) / current_ma200) * 100

                per_val, pbr_val, roe_val, peg_val, cagr_val = float('nan'), float('nan'), float('nan'), float('nan'), float('nan')
                eps3y_str = "데이터 없음"

                if opt_fundamental:
                    info = ticker_obj.info
                    per_val = info.get('trailingPE') or info.get('forwardPE') or float('nan')
                    pbr_val = info.get('priceToBook') or float('nan')
                    roe_val = (info.get('returnOnEquity') * 100) if info.get('returnOnEquity') else float('nan')
                    
                    if market != "미국" and pd.isna(mcap):
                        mcap = round((info.get('marketCap', 0)) / 100000000) if info.get('marketCap') else 0

                    try:
                        financials = ticker_obj.financials
                        if 'Net Income' in financials.index and 'Share Issued' in financials.index:
                            net_inc = financials.loc['Net Income']
                            shares = financials.loc['Share Issued']
                            eps_series = (net_inc / shares).dropna().iloc[::-1]
                        else:
                            eps_series = pd.Series()

                        if len(eps_series) >= 3:
                            eps_vals = eps_series.values[-3:]
                            if eps_vals[0] > 0 and eps_vals[1] > eps_vals[0] and eps_vals[2] > eps_vals[1]:
                                eps3y_str = "지속성장(↑)"
                            elif eps_vals[2] < eps_vals[0]:
                                eps3y_str = "하락세(↓)"
                            else:
                                eps3y_str = "정체(→)"
                            
                            eps_start, eps_end = eps_vals[0], eps_vals[2]
                            if eps_start > 0 and eps_end > 0:
                                cagr_val = ((eps_end / eps_start) ** 0.5 - 1) * 100
                        elif len(eps_series) == 2:
                            eps_vals = eps_series.values[-2:]
                            eps3y_str = "성장" if eps_vals[1] > eps_vals[0] else "쇠퇴"
                    except:
                        pass

                    if pd.notna(per_val) and per_val > 0 and pd.notna(cagr_val) and cagr_val > 0:
                        peg_val = per_val / cagr_val

                peak_price, peak_diff = float('nan'), float('nan')
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100

                # 패킷 조립 및 실시간 데이터 스트리밍 연동
                raw_row = {
                    "rank": idx + 1, "symbol": symbol, "name": name, "data_date": date_str, "market_cap": mcap,
                    "price": current_price, "ma200": current_ma200, "diff": diff_val, "rsi": rsi_val,
                    "per": per_val, "pbr": pbr_val, "peak": peak_price, "peak_diff": peak_diff,
                    "roe": roe_val, "peg": peg_val, "eps3y": eps3y_str, "cagr": cagr_val
                }
                
                # 가점 스코어링 시스템 결합
                grade, comment = evaluate_stock_grade(raw_row)
                raw_row["grade"] = grade
                raw_row["comment"] = comment

                app_queue.put({"type": "data", "data": raw_row})
            except Exception as inner_e:
                # 장중 특정 단일 종목 파싱 에러 우회 방어
                continue
            time.sleep(0.02)
            
        app_queue.put({"type": "done"})
    except Exception as e:
        app_queue.put({"type": "error", "text": str(e)})