import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from config import DEFAULT_US_TICKERS, US_NAME_MAP, US_MARKETCAP_CACHE_FILE

def load_us_market_cap_cache():
    if os.path.exists(US_MARKETCAP_CACHE_FILE):
        try:
            with open(US_MARKETCAP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    initial_cache = {}
    for i, ticker in enumerate(DEFAULT_US_TICKERS, 1):
        initial_cache[ticker] = {\"rank\": i, \"name\": US_NAME_MAP.get(ticker, ticker), \"market_cap\": 0}
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
    \"\"\"
    '04 스크리너해석 v2.txt' 표준 규칙에 따른 가점 기반 등급(A~D) 및 커스텀 한줄평 산출 엔진
    \"\"\"
    score = 0
    reasons = []
    
    per = row.get("per")
    pbr = row.get("pbr")
    roe = row.get("roe")
    peg = row.get("peg")
    cagr = row.get("cagr")
    eps3y = str(row.get("eps3y", ""))

    # 1. PER 밸류에이션 점수
    if pd.notna(per):
        if per <= 0:
            reasons.append("PER 적자 상태")
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
            
    # 2. PBR 안전성 점수
    if pd.notna(pbr):
        if pbr <= 0:
            reasons.append("PBR 자본잠식 위험")
        elif pbr <= 1.0:
            score += 20
            reasons.append("PBR 1배 이하 청산가치 이하")
        elif 1.0 < pbr <= 2.0:
            score += 10
        elif pbr > 3.0:
            score -= 5

    # 3. ROE 수익성 점수
    if pd.notna(roe):
        if roe >= 15:
            score += 25
            reasons.append("ROE 15% 이상 고성장 지속")
        elif 10 <= roe < 15:
            score += 15
        elif roe < 5:
            score -= 10
            reasons.append("ROE 5% 미만 저효율 자본운용")

    # 4. PEG 및 CAGR 성장성 속도 점수
    if pd.notna(peg) and peg > 0:
        if peg <= 1.0:
            score += 15
            reasons.append("성장성 대비 저렴한 주가(PEG≤1)")
        elif peg >= 1.5:
            score -= 5

    if pd.notna(cagr):
        if cagr >= 15:
            score += 15
            reasons.append("3개년 CAGR 15% 이상 고속성장")
        elif 5 <= cagr < 15:
            score += 5
        elif cagr < 0:
            score -= 10
            reasons.append("역성장 구조 리스크")

    # 5. EPS 3개년 추이 모멘텀 가점
    if "↑" in eps3y or "지속성장" in eps3y:
        score += 10
    elif "↓" in eps3y or "적자" in eps3y:
        score -= 15

    # 종합 점수 기반 등급 확정 및 요약 평가 생성
    if score >= 75:
        grade = "A"
        comment = "싸고 돈 잘 버는 이상적인 탑픽 종목! " + (reasons[0] if reasons else "모든 지표 최상위 만족")
    elif score >= 45:
        grade = "B"
        comment = "밸류에이션과 기초 체력이 탄탄하여 관심 가져볼 만한 우량 종목"
    elif score >= 15:
        grade = "C"
        comment = "성장성이나 가격 메리트 중 한 축이 정체되어 있어 관망 필요"
    else:
        grade = "D"
        comment = "고평가 혹은 펀더멘털 저하 징후 감지, 투자 시 상당한 주의 요망"
        
    return grade, comment

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental=True, opt_peak=True, us_market_cap_data=None):
    \"\"\"
    기존의 멀티스레딩 병렬 수집 로직 유지 및 등급 연산 연동 처리 구조
    \"\"\"
    try:
        if market == "미국":
            tickers_source = list(us_market_cap_data.keys())[:top_n] if us_market_cap_data else DEFAULT_US_TICKERS[:top_n]
        else:
            m_code = "KOSPI" if "코스피" in market else "KOSDAQ"
            df_kr = fdr.StockListing(m_code)
            df_kr = df_kr.dropna(subset=['Marcap']).sort_values(by='Marcap', ascending=False).head(top_n)
            tickers_source = []
            for _, row in df_kr.iterrows():
                tickers_source.append({
                    "symbol": str(row['Code']),
                    "name": str(row['Name']),
                    "market_cap": round(float(row['Marcap']) / 100000000)
                })

        for idx, item in enumerate(tickers_source):
            if stop_requested_func():
                app_queue.put({"type": "info", "text": "🛑 사용자에 의해 스크리닝이 중지되었습니다."})
                break

            if market == "미국":
                symbol = item
                name = us_market_cap_data[symbol]["name"] if us_market_cap_data else US_NAME_MAP.get(symbol, symbol)
                mcap = us_market_cap_data[symbol]["market_cap"] if us_market_cap_data else 0
            else:
                symbol = item["symbol"]
                name = item["name"]
                mcap = item["market_cap"]

            try:
                ticker_obj = yf.Ticker(symbol if market == "미국" else f"{symbol}.KS" if "코스피" in market else f"{symbol}.KQ")
                hist = ticker_obj.history(period="1y")
                if hist.empty:
                    continue

                close_series = hist['Close']
                current_price = float(close_series.iloc[-1])
                date_str = hist.index[-1].strftime('%Y-%m-%d')

                # 기술적 지표 산출
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
                                cagr_val = ((eps_end / eps_start) ** (0.5) - 1) * 100
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

                # 실시간 로우 데이터 패킷 전송
                raw_row = {
                    "rank": idx + 1, "symbol": symbol, "name": name, "data_date": date_str, "market_cap": mcap,
                    "price": current_price, "ma200": current_ma200, "diff": diff_val, "rsi": rsi_val,
                    "per": per_val, "pbr": pbr_val, "peak": peak_price, "peak_diff": peak_diff,
                    "roe": roe_val, "peg": peg_val, "eps3y": eps3y_str, "cagr": cagr_val
                }
                
                # 가점제 등급 처리 바인딩 필수 추가
                grade, comment = evaluate_stock_grade(raw_row)
                raw_row["grade"] = grade
                raw_row["comment"] = comment

                app_queue.put({"type": "data", "data": raw_row})
            except:
                continue
            time.sleep(0.02)
            
        app_queue.put({"type": "done"})
    except Exception as e:
        app_queue.put({"type": "error", "text": str(e)})