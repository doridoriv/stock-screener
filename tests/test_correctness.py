import logging
import unittest
from unittest.mock import patch

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
