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

    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else 50.0

def _is_missing(val):
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip()
        if s in {"", "-", "N/A", "None", "nan", "비활성", "정보없음", "데이터없음", "데이터부족"}:
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

def _fmt_signed_pct(val, decimals=1):
    try:
        v = float(val)
        if pd.isna(v):
            return "-"
        if v > 0:
            return f"+{v:.{decimals}f}%"
        if v < 0:
            return f"{v:.{decimals}f}%"
        return f"{0:.{decimals}f}%"
    except:
        return "-"

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
        else:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)

        if df is None or df.empty or len(df) < 200:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        return df
    except:
        return None

def _score_per(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v < 0:
        return 0, True
    if v <= 8:
        return 15, True
    if v <= 12:
        return 12, True
    if v <= 18:
        return 8, True
    if v <= 25:
        return 4, True
    return 0, True

def _score_pbr(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v < 0:
        return 0, True
    if v <= 0.8:
        return 10, True
    if v <= 1.2:
        return 8, True
    if v <= 1.8:
        return 6, True
    if v <= 3.0:
        return 3, True
    return 0, True

def _score_roe(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v >= 20:
        return 20, True
    if v >= 15:
        return 16, True
    if v >= 10:
        return 12, True
    if v >= 5:
        return 6, True
    return 0, True

def _score_peg(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v <= 0.7:
        return 20, True
    if v <= 1.0:
        return 16, True
    if v <= 1.5:
        return 12, True
    if v <= 2.0:
        return 6, True
    return 0, True

def _score_eps3y(val, growth=None, trend=None):
    if _is_missing(val) and _is_missing(growth) and _is_missing(trend):
        return 0, False

    if isinstance(trend, str):
        t = trend.strip()
        if t in {"적자", "적자전환"}:
            return 0, True
        if t == "흑자전환":
            return 8, True

    g = _safe_float(growth)
    if not pd.isna(g):
        if g >= 100:
            return 10, True
        if g >= 50:
            return 8, True
        if g >= 20:
            return 6, True
        if g >= 5:
            return 4, True
        if g > 0:
            return 2, True
        if g == 0:
            return 1, True
        return 0, True

    s = str(val).strip()
    if s == "적자":
        return 0, True
    if s.startswith("↑"):
        return 10, True
    if s.startswith("→"):
        return 5, True
    if s.startswith("↓"):
        return 1, True
    return 0, True

def _score_cagr(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v >= 25:
        return 15, True
    if v >= 18:
        return 12, True
    if v >= 12:
        return 9, True
    if v >= 5:
        return 5, True
    return 0, True

def _score_rsi(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if 35 <= v <= 55:
        return 5, True
    if 25 <= v < 35 or 55 < v <= 65:
        return 3, True
    if 20 <= v < 25 or 65 < v <= 75:
        return 1, True
    return 0, True

def _score_peak_diff(val):
    v = _safe_float(val)
    if pd.isna(v):
        return 0, False
    if v <= -10 and v >= -45:
        return 5, True
    if v < -45 and v >= -60:
        return 3, True
    if v < -60:
        return 1, True
    return 0, True

def _missing_label(score_input_map):
    missing = []
    for key, val in score_input_map.items():
        if _is_missing(val):
            missing.append(key.upper())
    return missing

def evaluate_investment_score(stock_row, market=None):
    """
    stock_row: dict-like with keys
    per, pbr, roe, peg, eps3y, eps3y_growth, eps3y_trend, cagr, rsi, peak_diff, diff, market_cap, price, name, symbol
    """
    per_score, per_ok = _score_per(stock_row.get("per"))
    pbr_score, pbr_ok = _score_pbr(stock_row.get("pbr"))
    roe_score, roe_ok = _score_roe(stock_row.get("roe"))
    peg_score, peg_ok = _score_peg(stock_row.get("peg"))
    eps_score, eps_ok = _score_eps3y(
        stock_row.get("eps3y"),
        stock_row.get("eps3y_growth"),
        stock_row.get("eps3y_trend"),
    )
    cagr_score, cagr_ok = _score_cagr(stock_row.get("cagr"))
    rsi_score, rsi_ok = _score_rsi(stock_row.get("rsi"))
    peak_score, peak_ok = _score_peak_diff(stock_row.get("peak_diff"))

    detail_scores = {
        "PER": per_score,
        "PBR": pbr_score,
        "ROE": roe_score,
        "PEG": peg_score,
        "EPS3Y": eps_score,
        "CAGR": cagr_score,
        "RSI": rsi_score,
        "최고점대비": peak_score,
    }

    total_score = int(sum(detail_scores.values()))
    grade = _grade_from_score(total_score)

    availability_flags = {
        "PER": per_ok,
        "PBR": pbr_ok,
        "ROE": roe_ok,
        "PEG": peg_ok,
        "EPS3Y": eps_ok,
        "CAGR": cagr_ok,
        "RSI": rsi_ok,
        "최고점대비": peak_ok,
    }
    availability_weights = {
        "PER": 15,
        "PBR": 10,
        "ROE": 20,
        "PEG": 20,
        "EPS3Y": 10,
        "CAGR": 15,
        "RSI": 5,
        "최고점대비": 5,
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
    eps_growth_val = _safe_float(stock_row.get("eps3y_growth"))
    eps_trend_val = str(stock_row.get("eps3y_trend", "")).strip()
    eps_disp_val = str(stock_row.get("eps3y", "")).strip()

    if not pd.isna(per_val):
        if per_val <= 10:
            positives.append(f"PER {per_val:.1f}")
        elif per_val >= 25:
            cautions.append(f"PER {per_val:.1f}")
    if not pd.isna(pbr_val):
        if pbr_val <= 1.2:
            positives.append(f"PBR {pbr_val:.2f}")
        elif pbr_val >= 3:
            cautions.append(f"PBR {pbr_val:.2f}")
    if not pd.isna(roe_val):
        if roe_val >= 15:
            positives.append(f"ROE {roe_val:.1f}%")
        elif roe_val < 8:
            cautions.append(f"ROE {roe_val:.1f}%")
    if not pd.isna(peg_val):
        if peg_val <= 1.0:
            positives.append(f"PEG {peg_val:.2f}")
        elif peg_val >= 2.0:
            cautions.append(f"PEG {peg_val:.2f}")
    if not pd.isna(cagr_val):
        if cagr_val >= 12:
            positives.append(f"CAGR {_fmt_signed_pct(cagr_val, 1)}")
        elif cagr_val < 5:
            cautions.append(f"CAGR {_fmt_signed_pct(cagr_val, 1)}")
    if not pd.isna(rsi_val):
        if 35 <= rsi_val <= 55:
            positives.append(f"RSI {rsi_val:.1f}")
        elif rsi_val >= 70 or rsi_val <= 20:
            cautions.append(f"RSI {rsi_val:.1f}")
    if not pd.isna(peak_diff_val):
        if peak_diff_val <= -15:
            positives.append(f"최고점대비 {peak_diff_val:.1f}%")
        elif peak_diff_val > 0:
            cautions.append(f"최고점대비 +{peak_diff_val:.1f}%")

    if not pd.isna(eps_growth_val):
        if eps_growth_val >= 20:
            positives.append(f"EPS3Y {_fmt_signed_pct(eps_growth_val, 1)}")
        elif eps_growth_val < 0:
            cautions.append(f"EPS3Y {_fmt_signed_pct(eps_growth_val, 1)}")
    else:
        if eps_trend_val == "흑자전환":
            positives.append("EPS3Y 흑자전환")
        elif eps_trend_val in {"적자", "적자전환"}:
            cautions.append(f"EPS3Y {eps_trend_val}")
        elif eps_disp_val and eps_disp_val not in {"-", "정보없음"}:
            if eps_disp_val.startswith("↑"):
                positives.append(f"EPS3Y {eps_disp_val}")
            elif eps_disp_val.startswith("↓"):
                cautions.append(f"EPS3Y {eps_disp_val}")

    positives = positives[:3]
    cautions = cautions[:2]

    missing = _missing_label(stock_row)
    missing_text = ""
    if missing:
        missing_text = " / ".join(missing)

    market_note = ""
    if market:
        if market == "미국":
            market_note = "미국 시장"
        else:
            market_note = market

    if total_score >= 90:
        head = "최상위 후보"
    elif total_score >= 80:
        head = "상위 후보"
    elif total_score >= 70:
        head = "관찰 후보"
    elif total_score >= 60:
        head = "보수 관찰"
    else:
        head = "주의 구간"

    if positives:
        core = "· ".join(positives)
    else:
        core = "핵심 지표 확인 필요"

    if cautions:
        caution_text = " / ".join(cautions)
        summary = f"{head}. {core}. 주의: {caution_text}."
    else:
        summary = f"{head}. {core}."

    if missing_text:
        summary += f" 누락: {missing_text}."

    if market_note:
        summary = f"[{market_note}] {summary}"

    detail_text = (
        f"PER {per_score}/15, PBR {pbr_score}/10, ROE {roe_score}/20, PEG {peg_score}/20, "
        f"EPS3Y {eps_score}/10, CAGR {cagr_score}/15, RSI {rsi_score}/5, 최고점대비 {peak_score}/5"
    )

    return {
        "score": total_score,
        "grade": grade,
        "confidence": confidence,
        "summary": summary,
        "detail_text": detail_text,
        "score_per": per_score,
        "score_pbr": pbr_score,
        "score_roe": roe_score,
        "score_peg": peg_score,
        "score_eps3y": eps_score,
        "score_cagr": cagr_score,
        "score_rsi": rsi_score,
        "score_peak_diff": peak_score,
        "missing_fields": ", ".join(missing) if missing else "",
    }

def screening_worker(market, top_n, app_queue, stop_requested_func, opt_fundamental, opt_peak, us_market_cap_data):
    try:
        tickers_to_screen = []
        kr_fundamental_map = {}

        if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
            market_type = "KOSDAQ" if market == "한국(코스닥)" else "KOSPI"
            market_text = "코스닥" if market == "한국(코스닥)" else "코스피"

            app_queue.put({"type": "progress", "value": 5, "text": f"{market_text} 상위 {top_n}위 종목 로드 중..."})
            df_kr = fdr.StockListing(market_type)
            df_kr = df_kr.dropna(subset=["Marcap"]).sort_values(by="Marcap", ascending=False).head(top_n)

            for idx, row in enumerate(df_kr.iterrows(), 1):
                r_data = row[1]
                mcap_val = int(r_data["Marcap"] / 100000000) if not pd.isna(r_data["Marcap"]) else 0
                tickers_to_screen.append({
                    "symbol": r_data["Code"],
                    "name": r_data["Name"],
                    "rank": idx,
                    "market_cap": mcap_val
                })
                kr_fundamental_map[r_data["Code"]] = {
                    "per": r_data["PER"] if "PER" in r_data else "N/A",
                    "pbr": r_data["PBR"] if "PBR" in r_data else "N/A",
                    "bps": r_data["BPS"] if "BPS" in r_data else "N/A"
                }
        else:
            for ticker, info in list(us_market_cap_data.items())[:top_n]:
                tickers_to_screen.append({
                    "symbol": ticker,
                    "name": info["name"],
                    "rank": info["rank"],
                    "market_cap": info["market_cap"]
                })

        total_stocks = len(tickers_to_screen)
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

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
                if df is None:
                    continue

                last_date_obj = df.index[-1]
                date_str = last_date_obj.strftime("%Y-%m-%d") if hasattr(last_date_obj, "strftime") else str(last_date_obj)[:10]

                if market == "미국" and stock["market_cap"] == 0:
                    try:
                        mc = yf.Ticker(symbol).info.get("marketCap", 0)
                        stock["market_cap"] = int(mc / 100000000)
                    except:
                        pass

                close_series = df["Close"]
                current_price = float(close_series.iloc[-1])

                ma200_series = close_series.rolling(window=200).mean()
                current_ma200 = float(ma200_series.iloc[-1])
                if pd.isna(current_ma200) or current_ma200 == 0:
                    continue

                diff_val = ((current_price - current_ma200) / current_ma200) * 100
                rsi_val = calculate_rsi(close_series, 14)

                per_val, pbr_val = float("nan"), float("nan")
                roe_val, peg_val = float("nan"), float("nan")
                eps3y_str = "정보없음"
                eps3y_growth = float("nan")
                eps3y_trend = "데이터없음"
                cagr_val = float("nan")

                t_obj = None
                if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                    suffix = ".KQ" if market == "한국(코스닥)" else ".KS"
                    t_obj = yf.Ticker(f"{symbol}{suffix}")
                else:
                    t_obj = yf.Ticker(symbol)

                if opt_fundamental:
                    if market in ["한국(코스피)", "한국(코스닥)", "한국"]:
                        f_info = kr_fundamental_map.get(symbol, {"per": "N/A", "pbr": "N/A", "bps": "N/A"})
                        per_val_raw = f_info.get("per", "N/A")

                        if _is_missing(per_val_raw) or str(per_val_raw) in ["N/A", "0", "nan", "None"]:
                            try:
                                info = t_obj.info
                                per_val_raw = info.get("trailingPE") or info.get("forwardPE") or float("nan")
                            except:
                                per_val_raw = float("nan")

                        try:
                            per_val = float(per_val_raw) if not pd.isna(per_val_raw) else float("nan")
                        except:
                            per_val = float("nan")

                        try:
                            pbr_val = float(f_info.get("pbr", float("nan")))
                        except:
                            pbr_val = float("nan")
                        if pd.isna(pbr_val) or pbr_val == 0:
                            try:
                                info = t_obj.info
                                pbr_val = info.get("priceToBook", float("nan"))
                            except:
                                pass
                    else:
                        try:
                            info = t_obj.info
                            per_val_raw = info.get("trailingPE", float("nan"))
                            pbr_val_raw = info.get("priceToBook", float("nan"))

                            if (pbr_val_raw == "N/A" or pbr_val_raw is None or pd.isna(pbr_val_raw)) and info.get("bookValue"):
                                try:
                                    pbr_val_raw = current_price / float(info.get("bookValue"))
                                except:
                                    pbr_val_raw = float("nan")

                            try:
                                per_val = float(per_val_raw) if per_val_raw != "N/A" else float("nan")
                            except:
                                per_val = float("nan")
                            try:
                                pbr_val = float(pbr_val_raw) if pbr_val_raw != "N/A" else float("nan")
                            except:
                                pbr_val = float("nan")
                        except:
                            per_val, pbr_val = float("nan"), float("nan")

                try:
                    if t_obj is not None:
                        info = t_obj.info
                        if info and "returnOnEquity" in info and info["returnOnEquity"] is not None:
                            roe_val = float(info["returnOnEquity"]) * 100
                except:
                    pass

                try:
                    if t_obj is not None:
                        financials = t_obj.financials
                        if financials is not None and not financials.empty:
                            eps_rows = [r for r in financials.index if "Diluted EPS" in str(r) or "Basic EPS" in str(r)]
                            if eps_rows:
                                eps_series = financials.loc[eps_rows[0]].dropna()
                                eps_series = eps_series.sort_index(ascending=True)

                                if len(eps_series) >= 3:
                                    recent_eps = [float(x) for x in eps_series.values[-3:]]
                                    v1, v2, v3 = recent_eps[0], recent_eps[1], recent_eps[2]

                                    if v1 <= 0 and v2 <= 0 and v3 <= 0:
                                        eps3y_str = "↓ 적자"
                                        eps3y_trend = "적자"
                                    elif v1 <= 0 < v3:
                                        eps3y_str = "↑ 흑자전환"
                                        eps3y_trend = "흑자전환"
                                    elif v1 > 0 and v3 <= 0:
                                        eps3y_str = "↓ 적자전환"
                                        eps3y_trend = "적자전환"
                                    else:
                                        eps3y_growth = ((v3 / v1) - 1) * 100 if v1 != 0 else float("nan")
                                        if v1 < v2 < v3:
                                            eps3y_trend = "상승"
                                            direction = "↑"
                                        elif v1 > v2 > v3:
                                            eps3y_trend = "하락"
                                            direction = "↓"
                                        else:
                                            eps3y_trend = "중립"
                                            direction = "→"
                                        if pd.notna(eps3y_growth):
                                            eps3y_str = f"{direction} {_fmt_signed_pct(eps3y_growth, 1)}"
                                        else:
                                            eps3y_str = f"{direction} 정보없음"

                                    if len(eps_series) >= 4:
                                        eps_start = eps_series.values[-4]
                                        eps_end = eps_series.values[-1]
                                        if eps_start > 0 and eps_end > 0:
                                            cagr_val = ((eps_end / eps_start) ** (1 / 3) - 1) * 100
                                    else:
                                        eps_start = eps_series.values[-3]
                                        eps_end = eps_series.values[-1]
                                        if eps_start > 0 and eps_end > 0:
                                            cagr_val = ((eps_end / eps_start) ** (1 / 2) - 1) * 100
                except:
                    pass

                if pd.notna(per_val) and per_val > 0 and pd.notna(cagr_val) and cagr_val > 0 and eps3y_str != "↓ 적자":
                    try:
                        peg_val = per_val / cagr_val
                    except:
                        peg_val = float("nan")

                peak_price, peak_diff = float("nan"), float("nan")
                if opt_peak:
                    peak_price = float(close_series.max())
                    peak_diff = ((current_price - peak_price) / peak_price) * 100

                row_data = {
                    "rank": stock["rank"],
                    "symbol": symbol,
                    "name": name,
                    "data_date": date_str,
                    "market_cap": stock["market_cap"],
                    "price": current_price,
                    "ma200": current_ma200,
                    "diff": diff_val,
                    "rsi": rsi_val,
                    "per": per_val,
                    "pbr": pbr_val,
                    "peak": peak_price,
                    "peak_diff": peak_diff,
                    "roe": roe_val,
                    "peg": peg_val,
                    "eps3y": eps3y_str,
                    "eps3y_growth": eps3y_growth,
                    "eps3y_trend": eps3y_trend,
                    "cagr": cagr_val
                }

                eval_result = evaluate_investment_score(row_data, market=market)
                row_data.update(eval_result)

                app_queue.put({"type": "data", "data": row_data})
            except:
                continue

            time.sleep(0.05)

        if not stop_requested_func():
            app_queue.put({
                "type": "done",
                "count": total_stocks,
                "text": f"{market} 상위 {top_n}종목 스크리닝 완료!"
            })
    except Exception as e:
        app_queue.put({"type": "error", "text": f"엔진 오류 발생: {e}"})