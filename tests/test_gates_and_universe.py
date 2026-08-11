from __future__ import annotations

import pandas as pd

from crypto_research.paper_gate import evaluate_gate
from crypto_research.data.universe import discover_spot_symbols


def test_paper_gate_rejects_weak_oos():
    cfg = {"research": {"min_oos_trades": 30, "min_oos_profit_factor": 1.1, "min_oos_expectancy": 0.0, "max_oos_drawdown": -0.30}}
    decision = evaluate_gate({"trades": 100, "profit_factor": 0.8, "expectancy": -1, "max_drawdown": -0.2}, cfg)
    assert decision.status == "FAILED_NO_ROBUST_EDGE"
    assert decision.paper_trading_allowed is False
    assert decision.live_trading_allowed is False


def test_universe_ranking_keeps_spot_usdt_only(monkeypatch):
    payload = {
        "symbols": [
            {"symbol": "AAAUSDT", "baseAsset": "AAA", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "AAAUSDC", "baseAsset": "AAA", "quoteAsset": "USDC", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "BBBUSDT", "baseAsset": "BBB", "quoteAsset": "USDT", "status": "BREAK", "isSpotTradingAllowed": True},
        ]
    }
    def fake_get(base_url, path, timeout=30):
        if path.endswith("exchangeInfo"):
            return payload
        return [{"symbol": "AAAUSDT", "quoteVolume": "10"}]
    monkeypatch.setattr("crypto_research.data.universe._get", fake_get)
    frame = discover_spot_symbols("https://example.com", "USDT", 30, [])
    assert frame["symbol"].tolist() == ["AAAUSDT"]
