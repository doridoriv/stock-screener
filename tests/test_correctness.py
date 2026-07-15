import logging
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import analyzer
import opendart_client


logging.disable(logging.CRITICAL)
import app_web
logging.disable(logging.NOTSET)


class CacheCorrectnessTests(unittest.TestCase):
    def test_cache_validation_requires_complete_unique_rows(self):
        valid = pd.DataFrame({
            "symbol": ["A", "B", "C"],
            "name": ["Alpha", "Beta", "Gamma"],
            "price": [10, 20, 30],
            "data_date": ["20260710"] * 3,
        })
        self.assertEqual(analyzer.validate_cache_dataframe(valid, expected_rows=3), (True, []))

        duplicate = valid.copy()
        duplicate.loc[2, "symbol"] = "A"
        is_valid, reasons = analyzer.validate_cache_dataframe(duplicate, expected_rows=3)
        self.assertFalse(is_valid)
        self.assertTrue(any("unique symbols" in reason for reason in reasons))

        missing_price = valid.copy()
        missing_price.loc[2, "price"] = np.nan
        is_valid, reasons = analyzer.validate_cache_dataframe(missing_price, expected_rows=3)
        self.assertFalse(is_valid)
        self.assertTrue(any("valid prices" in reason for reason in reasons))
        self.assertTrue(
            analyzer.validate_cache_dataframe(
                missing_price,
                expected_rows=3,
                require_complete_prices=False,
            )[0]
        )

    def test_us_universe_normalizes_aliases_and_removes_duplicates(self):
        cached = {
            "ABV": {"name": "ABV", "market_cap": 100},
            "ABBV": {"name": "AbbVie", "market_cap": 200},
            "MMC": {"name": "Marsh McLennan", "market_cap": 150},
        }
        with patch.object(analyzer, "load_us_market_cap_cache", return_value=cached):
            candidates = analyzer.fetch_us_top100_tickers(5)
        symbols = [item["symbol"] for item in candidates]
        self.assertEqual(len(symbols), 5)
        self.assertEqual(len(set(symbols)), 5)
        self.assertIn("ABBV", symbols)
        self.assertIn("MRSH", symbols)
        self.assertNotIn("ABV", symbols)
        self.assertNotIn("MMC", symbols)

    def test_market_date_comes_from_last_real_close(self):
        closes = pd.DataFrame(
            {"A": [10, 11]},
            index=pd.to_datetime(["2026-07-09", "2026-07-10"]),
        )
        self.assertEqual(analyzer.market_date_from_prices(closes), "20260710")

    def test_korean_cashflow_scale_mismatch_is_quarantined(self):
        source = pd.DataFrame([{
            "symbol": "241560",
            "revenue": 87919.0,
            "operating_cashflow": 8.22,
            "free_cashflow": 5.81,
            "cash": 13.90,
            "total_debt": 35.47,
            "net_cash": -21.57,
        }])
        normalized = analyzer.normalize_financial_sanity_metrics(source)
        self.assertEqual(normalized.loc[0, "cashflow_status"], "통화 단위 확인 필요")
        self.assertTrue(pd.isna(normalized.loc[0, "operating_cashflow"]))
        self.assertTrue(pd.isna(normalized.loc[0, "free_cashflow"]))

    def test_peer_comparison_uses_leave_one_out_median(self):
        source = pd.DataFrame({
            "symbol": ["A", "B", "C", "D"],
            "sector": ["Tech"] * 4,
            "per": [5.0, 10.0, 15.0, 100.0],
            "pbr": [1.0, 2.0, 3.0, 4.0],
            "roe": [5.0, 10.0, 15.0, 20.0],
        })
        compared = analyzer.add_peer_comparison_metrics(source)
        row_d = compared.loc[compared["symbol"] == "D"].iloc[0]
        self.assertEqual(row_d["peer_per_count"], 3)
        self.assertEqual(row_d["peer_per_avg"], 10.0)


class DartCorrectnessTests(unittest.TestCase):
    def test_foreign_currency_row_does_not_hide_valid_krw_row(self):
        rows = [
            {"sj_nm": "재무상태표", "account_id": "cash", "account_nm": "현금", "currency": "USD", "thstrm_amount": "1000000000"},
            {"sj_nm": "재무상태표", "account_id": "cash", "account_nm": "현금", "currency": "KRW", "thstrm_amount": "500000000"},
        ]
        picked = opendart_client._pick(rows, account_ids=["cash"])
        summed = opendart_client._sum_picks(rows, account_ids=["cash"])
        self.assertEqual(picked, 5.0)
        self.assertEqual(summed, 5.0)

    def test_mixed_currency_statement_prefers_krw_without_false_warning(self):
        rows = [
            {"sj_nm": "재무상태표", "account_id": "ifrs-full_CashAndCashEquivalents", "account_nm": "현금", "currency": "USD", "thstrm_amount": "1000000000"},
            {"sj_nm": "재무상태표", "account_id": "ifrs-full_CashAndCashEquivalents", "account_nm": "현금", "currency": "KRW", "thstrm_amount": "500000000"},
        ]
        metrics = opendart_client._statement_metrics(rows)
        self.assertEqual(metrics["cash"], 5.0)
        self.assertEqual(metrics["financial_currency"], "KRW")
        self.assertNotIn("cashflow_status", metrics)

    def test_dividend_history_requires_true_consecutive_years(self):
        continuous = [
            {"year": year, "dividend_per_share": value}
            for year, value in zip(range(2025, 2020, -1), [100, 90, 80, 70, 60])
        ]
        summary = opendart_client._summarize_dividend_history(continuous, 2025, 5)
        self.assertEqual(summary["dividend_consecutive_years"], 5)
        self.assertFalse(summary["dividend_cut_flag"])
        self.assertIn("dividend_growth_3y", summary)

        with_gap = [item for item in continuous if item["year"] != 2023]
        gap_summary = opendart_client._summarize_dividend_history(with_gap, 2025, 5)
        self.assertEqual(gap_summary["dividend_consecutive_years"], 2)
        self.assertIsNone(gap_summary["dividend_cut_flag"])
        self.assertNotIn("dividend_growth_3y", gap_summary)

    def test_dividend_cut_is_detected(self):
        history = [
            {"year": 2025, "dividend_per_share": 80},
            {"year": 2024, "dividend_per_share": 100},
        ]
        summary = opendart_client._summarize_dividend_history(history, 2025, 5)
        self.assertTrue(summary["dividend_cut_flag"])


class SupplementalDataCorrectnessTests(unittest.TestCase):
    def test_us_dividend_history_excludes_special_dividend(self):
        dates = pd.to_datetime([
            "2022-02-01", "2022-05-01", "2022-08-01", "2022-11-01",
            "2023-02-01", "2023-05-01", "2023-08-01", "2023-11-01",
            "2024-02-01", "2024-05-01", "2024-08-01", "2024-11-01", "2024-12-01",
            "2025-02-01", "2025-05-01", "2025-08-01", "2025-11-01",
        ])
        payments = pd.Series(
            [0.9] * 4 + [1.0] * 4 + [1.1] * 4 + [15.0] + [1.2] * 4,
            index=dates,
        )
        summary = analyzer.summarize_us_dividend_history(payments, reference_year=2025)
        self.assertEqual(summary["dividend_consecutive_years"], 4)
        self.assertFalse(summary["dividend_cut_flag"])
        self.assertAlmostEqual(summary["dividend_growth_3y"], 10.06, places=2)

    def test_consensus_fallbacks_parse_real_target_values(self):
        self.assertEqual(analyzer.extract_naver_target_mean("4.04매수 l 513,958"), 513958.0)
        self.assertEqual(analyzer.extract_naver_opinion_score("4.04매수 l 513,958"), 4.04)
        metrics = analyzer.consensus_metrics_from_yfinance_info({
            "targetMeanPrice": 125.5,
            "targetHighPrice": 150,
            "targetLowPrice": 90,
            "recommendationMean": 1.8,
            "numberOfAnalystOpinions": 24,
        })
        self.assertEqual(metrics["target_mean"], 125.5)
        self.assertEqual(metrics["analyst_opinion_score"], 4.2)
        self.assertEqual(metrics["analyst_opinion_count"], 24)
        self.assertEqual(metrics["consensus_source"], "yfinance")

    def test_price_update_banner_uses_last_reflection_and_next_window(self):
        pending = app_web.build_price_update_status(
            {"price_time": "2026-07-13 22:38 KST", "data_date": "2026-07-13"},
            "코스피",
            now=datetime(2026, 7, 14, 21, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )
        self.assertEqual(pending["tone"], "pending")
        self.assertEqual(
            pending["message"],
            "표시 가격: 7/13 22:38 반영 · 다음 업데이트: 오늘 22:30~23:30 예정",
        )

        complete = app_web.build_price_update_status(
            {"price_time": "2026-07-14 23:12 KST", "data_date": "2026-07-14"},
            "코스피",
            now=datetime(2026, 7, 14, 23, 20, tzinfo=ZoneInfo("Asia/Seoul")),
        )
        self.assertEqual(complete["tone"], "complete")
        self.assertIn("다음 업데이트: 내일 22:30~23:30 예정", complete["message"])


class CustomViewCorrectnessTests(unittest.TestCase):
    def test_custom_metric_catalog_is_unique_and_hides_empty_metrics(self):
        self.assertEqual(len(app_web.CUSTOM_METRIC_IDS), len(set(app_web.CUSTOM_METRIC_IDS)))
        self.assertTrue(set(app_web.CUSTOM_DEFAULT_METRICS).issubset(app_web.CUSTOM_METRIC_DEFS))

        data = pd.DataFrame({
            "price": [1000],
            "per": [np.nan],
            "roe": [12.5],
            "dividend_cut_flag": [False],
        })
        available = app_web.available_custom_metric_ids(data)
        self.assertIn("price", available)
        self.assertIn("roe", available)
        self.assertIn("dividend_cut_flag", available)
        self.assertNotIn("per", available)
        self.assertNotIn("target_mean", available)

    def test_custom_table_keeps_numeric_sort_values_and_compact_display(self):
        data = pd.DataFrame([{
            "symbol": "000001",
            "name": "테스트회사",
            "per": 8.25,
            "roe": 14.1,
            "free_cashflow": 41000,
        }])
        metric_ids = ["per", "roe", "free_cashflow"]
        rows = app_web.build_custom_table_rows(data, metric_ids, is_kr=True)
        self.assertEqual(rows[0]["per"], 8.25)
        self.assertEqual(rows[0]["display"]["roe"], "14.10%")
        self.assertEqual(rows[0]["display"]["free_cashflow"], "4.1조")

        invalid = app_web.build_custom_table_rows(
            pd.DataFrame([{"symbol": "000002", "name": "적자회사", "per": -20}]),
            ["per"],
            is_kr=True,
        )[0]
        self.assertIsNone(invalid["per"])
        self.assertEqual(invalid["display"]["per"], "-")

        table_html = app_web.build_custom_table_html(data, metric_ids, True, "테스트")
        self.assertIn('state.sortDir = "desc"', table_html)
        self.assertIn('state.sortDir = "asc"', table_html)
        self.assertIn("if (aMissing) return 1", table_html)
        self.assertIn("orderedRows().slice(0, visibleLimit())", table_html)


class LensCorrectnessTests(unittest.TestCase):
    def test_negative_per_and_pbr_are_not_cheapness_signals(self):
        invalid = {"per": -5, "pbr": -1, "peak_diff": -40, "diff": -10}
        valid = {"per": 7, "pbr": 0.7, "peak_diff": -40, "diff": -10}
        self.assertLessEqual(app_web.mobile_cheapness_score(invalid), 12)
        self.assertGreater(app_web.mobile_cheapness_score(valid), app_web.mobile_cheapness_score(invalid))
        self.assertIn("사용할 수 없습니다", app_web.metric_explanation("PER", invalid, -5))
        self.assertIn("해석하면 안 됩니다", app_web.metric_explanation("PBR", invalid, -1))

    def test_financial_business_is_held_out_of_cash_lens(self):
        bank = {
            "name": "Example Bank",
            "sector": "Banks",
            "operating_cashflow": 100,
            "free_cashflow": 90,
            "net_cash": 80,
        }
        self.assertFalse(app_web.cashflow_metrics_usable(bank))
        self.assertEqual(app_web.mobile_lens_score(bank, "💸 현금창출"), 0)

    def test_empty_cashflow_status_from_csv_remains_usable(self):
        company = {
            "name": "Manufacturer",
            "sector": "Industrials",
            "cashflow_status": np.nan,
        }
        self.assertTrue(app_web.cashflow_metrics_usable(company))

    def test_new_candidate_uses_score_rank_not_market_cap_rank(self):
        row = {
            "symbol": "A",
            "score": 80,
            "rank": 2,
            "_score_rank_current": 10,
        }
        history = {
            "previous": {"A": {"score": 75, "_score_rank": 35}},
            "price_20": {},
            "price_60": {},
        }
        metrics = app_web.mobile_history_metrics(row, history, total_count=100)
        self.assertEqual(metrics["rank_delta"], 25)
        self.assertTrue(metrics["new_top20"])

    def test_dividend_tie_uses_lens_metrics_before_market_rank(self):
        source = pd.DataFrame([
            {"symbol": "LOW", "rank": 1, "dividend_yield": 2.0, "dividend_consecutive_years": 5, "dividend_growth_3y": 5, "payout_ratio": 45},
            {"symbol": "HIGH", "rank": 100, "dividend_yield": 4.0, "dividend_consecutive_years": 5, "dividend_growth_3y": 5, "payout_ratio": 45},
        ])
        with patch.object(app_web, "mobile_lens_score", return_value=50):
            sorted_df = app_web.sort_mobile_candidates(source, "🏦 배당")
        self.assertEqual(sorted_df.iloc[0]["symbol"], "HIGH")

    def test_display_text_hides_nan(self):
        self.assertEqual(app_web.display_text(np.nan, "업종 확인"), "업종 확인")


if __name__ == "__main__":
    unittest.main()
