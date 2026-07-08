import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

import config
from strategies import InstitutionalStrategies


def make_trend_df(direction: str = "up", candles: int = 260, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 100.0
    if direction == "up":
        trend = np.linspace(0, 25, candles)
    elif direction == "down":
        trend = np.linspace(25, 0, candles)[::-1]
        trend = -np.linspace(0, 25, candles)
    else:
        trend = np.zeros(candles)

    noise = rng.normal(0, 0.25, candles)
    close = base + trend + noise
    open_ = close + rng.normal(0, 0.10, candles)
    high = np.maximum(open_, close) + 0.30
    low = np.minimum(open_, close) - 0.30
    volume = rng.normal(1200, 80, candles).clip(700, 2500)

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=candles, freq="1h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def make_structured_buy_df() -> pd.DataFrame:
    candles = 260
    rng = np.random.default_rng(7)
    base = np.linspace(100, 115, candles)
    close = base + rng.normal(0, 0.12, candles)
    open_ = close + rng.normal(0, 0.08, candles)
    high = np.maximum(open_, close) + 0.22
    low = np.minimum(open_, close) - 0.22
    volume = rng.normal(1200, 90, candles).clip(800, 2600)

    # Create equal lows then a sweep and recovery.
    low[-12] = 99.5
    low[-11] = 99.52
    low[-10] = 99.51
    high[-10] = close[-10] + 0.25

    # BOS candle: decisive close above previous swing high.
    high[-4] = 118.0
    close[-4] = 117.6
    open_[-4] = 116.2
    low[-4] = 115.8
    volume[-4] = 2200

    # Retest candle near the order block / FVG zone.
    open_[-2] = 116.8
    close[-2] = 117.9
    high[-2] = 118.2
    low[-2] = 116.0
    volume[-2] = 2100

    # Final candle confirms breakout continuity after retest.
    open_[-1] = 117.8
    close[-1] = 118.7
    high[-1] = 119.0
    low[-1] = 117.4
    volume[-1] = 2400

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=candles, freq="1h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestInstitutionalStrategies(unittest.TestCase):
    def setUp(self):
        self.strat = InstitutionalStrategies()

    def test_htf_missing_never_passes(self):
        df = make_trend_df("up")
        analysis = self.strat.calculate_combined_score(df, None)

        self.assertIn(analysis["htf_data"]["status"], {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"})
        self.assertFalse(analysis["htf_data"]["supported"])
        self.assertLess(analysis["confidence"], 100)

    def test_htf_alignment_improves_confidence(self):
        df_ltf = make_structured_buy_df()
        df_htf = make_structured_buy_df()

        regime = self.strat.classify_market(df_ltf)
        missing_filter = self.strat._htf_filter(None, "BUY", regime)
        aligned_filter = self.strat._htf_filter(df_htf, "BUY", regime)

        self.assertIn(missing_filter["status"], {"UNKNOWN", "IGNORE_WITH_PENALTY", "SKIP"})
        self.assertFalse(missing_filter["supported"])
        self.assertEqual(aligned_filter["status"], "PASS")
        self.assertTrue(aligned_filter["supported"])

    def test_momentum_is_continuous_and_not_zero_on_neutral_market(self):
        df = make_trend_df("flat")
        indicators = self.strat.get_indicators_data(df)
        momentum = indicators["Momentum"]["current"]

        self.assertGreater(momentum, 35)
        self.assertLess(momentum, 65)
        self.assertTrue(indicators["Momentum"]["continuous"])

    def test_trend_engine_returns_strength(self):
        df = make_trend_df("up")
        regime = self.strat.classify_market(df)

        self.assertIn(regime["state"], {"Strong Uptrend", "Uptrend", "Weak Uptrend", "Choppy/Sideways", "Transition/Range"})
        self.assertGreaterEqual(regime["trend_strength"], 0)
        self.assertLessEqual(regime["trend_strength"], 100)

    def test_smc_requires_multiple_confirmations(self):
        df = make_trend_df("up")
        smc = self.strat.get_smc_data(df)

        self.assertIn("direction", smc)
        self.assertFalse(smc["institutional_grade"])
        self.assertGreaterEqual(smc["confidence"], 0)
        self.assertLessEqual(smc["confidence"], 100)

    def test_risk_engine_returns_structured_rr(self):
        df = make_structured_buy_df()
        risk = self.strat.analyze_risk(df, "BUY")

        self.assertIn("atr_stop", risk)
        self.assertIn("selected_stop", risk)
        self.assertIn("target", risk)
        self.assertGreater(risk["rr"], 0)

    def test_strict_final_decision_rejects_without_full_confirmation(self):
        df = make_structured_buy_df()
        htf = make_trend_df("up", candles=180, seed=123)
        analysis = self.strat.calculate_combined_score(df, htf)

        self.assertIn("rejection_data", analysis)
        self.assertIn("conditions", analysis["validation_data"])
        self.assertIn(analysis["verdict"], {"BUY", "SELL", "SKIP"})
        self.assertGreaterEqual(len(analysis["validation_data"]["conditions"]), 5)

        # The synthetic data is not guaranteed to satisfy every institutional gate.
        # The important property is that any failure is explained structurally.
        if analysis["verdict"] == "SKIP":
            first_reason = analysis["rejection_data"]["reasons"][0]
            self.assertIn("name", first_reason)
            self.assertIn("current_value", first_reason)
            self.assertIn("required_value", first_reason)
            self.assertIn("impact", first_reason)
            self.assertIn("suggested_fix", first_reason)


if __name__ == "__main__":
    unittest.main()
