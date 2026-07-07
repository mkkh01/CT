import unittest
import pandas as pd
import numpy as np
from strategies import InstitutionalStrategies

class TestInstitutionalStrategies(unittest.TestCase):
    def setUp(self):
        self.strat = InstitutionalStrategies()
        self.strat.thresholds["min_score"] = 50 # Lower for testing

    def create_mock_df(self, trend="bullish"):
        dates = pd.date_range(start="2023-01-01", periods=250, freq="1h")
        if trend == "bullish":
            close = np.linspace(100, 150, 250)
        elif trend == "bearish":
            close = np.linspace(150, 100, 250)
        else:
            close = np.full(250, 100)
        
        df = pd.DataFrame({
            "timestamp": dates,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.random.normal(1000, 100, 250)
        })
        return df

    def test_classify_market_bullish(self):
        df = self.create_mock_df("bullish")
        regime = self.strat.classify_market(df)
        self.assertIn("Uptrend", regime["state"])
        self.assertEqual(regime["bias"], "BULLISH")

    def test_classify_market_bearish(self):
        df = self.create_mock_df("bearish")
        regime = self.strat.classify_market(df)
        self.assertIn("Downtrend", regime["state"])
        self.assertEqual(regime["bias"], "BEARISH")

    def test_smc_detection(self):
        df = self.create_mock_df("bullish")
        # Force a BOS
        df.loc[df.index[-1], "close"] = 200
        smc = self.strat.get_smc_data(df)
        self.assertIn("BOS", smc["detected_structures"])
        self.assertEqual(smc["direction"], "BUY")

    def test_combined_score_logic(self):
        df = self.create_mock_df("bullish")
        # Add volume spike and sweep
        df.loc[df.index[-1], "volume"] = 5000
        df.loc[df.index[-1], "low"] = 50
        df.loc[df.index[-1], "close"] = 160
        
        analysis = self.strat.calculate_combined_score(df, df)
        self.assertGreater(analysis["total_score"], 0)
        self.assertIn("verdict", analysis)

if __name__ == "__main__":
    unittest.main()
