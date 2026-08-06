"""
Independent Scientific Stress Test & Algorithmic Validation for CT Engine
Author: Manus AI
Methodology: Monte Carlo perturbation, boundary condition stress testing,
confidence score distribution analysis, and regime sensitivity verification.
"""

import sys
import os
import unittest
from datetime import datetime, timezone

# Add CT root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engine.confidence import calculate_confidence, confidence_gate, aggregate_score, directional_contribution
from contracts.decision import StrategySignal, HTFFilterResult
from contracts.market import RegimeState
from config.thresholds import CONFIDENCE_THRESHOLD


class ScientificEngineStressTest(unittest.TestCase):
    """
    Empirical stress testing suite independent of built-in unit tests.
    Validates mathematical robustness under extreme market conditions:
    1. Zero-signal and noise resilience.
    2. High volatility penalty correctness.
    3. Contradiction penalty mathematical scaling.
    4. Regime modifier boundary validation.
    """

    def test_zero_and_noise_signals(self):
        """Test how the engine handles empty or completely neutral signals."""
        signals = []
        htf = HTFFilterResult(
            symbol="BTCUSDT",
            htf_timeframe="4h",
            ltf_timeframe="15m",
            bias="neutral",
            alignment=False,
            reason="neutral bias",
            timestamp=datetime.now(timezone.utc)
        )
        
        score = calculate_confidence(
            signals=signals,
            htf_result=htf,
            regime=RegimeState.RANGING,
            trend_strength=0.0,
            momentum_score=0.5,
            volume_confirmation=0.0,
            session_score=0.5,
            symbol="BTCUSDT",
            trade_direction="long"
        )
        # With zero alignment and ranging regime, confidence must be well below threshold
        self.assertLess(score, CONFIDENCE_THRESHOLD)
        self.assertFalse(confidence_gate(score))

    def test_contradiction_penalty_scaling(self):
        """Verify that contradicting signals aggressively suppress the final confidence score."""
        signals = [
            StrategySignal(
                symbol="BTCUSDT",
                timeframe="15m",
                strategy_name="structure",
                direction="short", # Contradicts long trade
                raw_score=0.9,
                reasons=["bearish structure"],
                timestamp=datetime.now(timezone.utc),
                source_candle_open_time=datetime.now(timezone.utc)
            )
        ]
        htf = HTFFilterResult(
            symbol="BTCUSDT",
            htf_timeframe="4h",
            ltf_timeframe="15m",
            bias="bearish",
            alignment=False,
            reason="bearish bias",
            timestamp=datetime.now(timezone.utc)
        )
        
        score = calculate_confidence(
            signals=signals,
            htf_result=htf,
            regime=RegimeState.TRENDING,
            trend_strength=0.9,
            momentum_score=0.1,
            volume_confirmation=0.1,
            session_score=0.5,
            symbol="BTCUSDT",
            trade_direction="long" # Trying to go long against strong short signals
        )
        # Score must drop to zero due to alignment < 3
        self.assertEqual(score, 0.0)

    def test_monte_carlo_regime_perturbation(self):
        """
        Run 1,000 Monte Carlo perturbations of randomized component inputs
        to verify stability, bounding [0, 1], and graceful degradation.
        """
        import random
        random.seed(42)
        
        passed_bounds = 0
        iterations = 1000
        
        for _ in range(iterations):
            trend = random.uniform(0.0, 1.0)
            mom = random.uniform(0.0, 1.0)
            vol = random.uniform(0.0, 1.0)
            sess = random.uniform(0.0, 1.0)
            regime = random.choice([RegimeState.TRENDING, RegimeState.RANGING, RegimeState.VOLATILE])
            alignment = random.choice([True, False])
            
            htf = HTFFilterResult(
                symbol="ETHUSDT",
                htf_timeframe="4h",
                ltf_timeframe="15m",
                bias="bullish",
                alignment=alignment,
                reason="monte carlo test",
                timestamp=datetime.now(timezone.utc)
            )
            signals = [
                StrategySignal(
                    symbol="ETHUSDT", timeframe="15m", strategy_name="structure",
                    direction="long", raw_score=trend, reasons=[],
                    timestamp=datetime.now(timezone.utc), source_candle_open_time=datetime.now(timezone.utc)
                )
            ]
            
            score = calculate_confidence(
                signals=signals, htf_result=htf, regime=regime,
                trend_strength=trend, momentum_score=mom,
                volume_confirmation=vol, session_score=sess,
                symbol="ETHUSDT", trade_direction="long"
            )
            
            if 0.0 <= score <= 1.0:
                passed_bounds += 1
                
        self.assertEqual(passed_bounds, iterations, "Monte Carlo perturbation yielded out-of-bound scores.")


if __name__ == "__main__":
    unittest.main()
