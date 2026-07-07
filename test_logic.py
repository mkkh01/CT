import pandas as pd
import numpy as np
import asyncio
import json
from strategies import InstitutionalStrategies
from Core.utils import make_json_safe, diag_logger

def generate_mock_data(trend="bullish"):
    """توليد بيانات وهمية للاختبار"""
    np.random.seed(42)
    candles = 300
    base_price = 50000
    
    if trend == "bullish":
        # اتجاه صاعد مع محاذاة EMA
        prices = base_price + np.cumsum(np.random.normal(10, 5, candles))
        # إضافة تذبذب
        prices += np.random.normal(0, 20, candles)
    else:
        # اتجاه هابط
        prices = base_price - np.cumsum(np.random.normal(10, 5, candles))
        prices += np.random.normal(0, 20, candles)
        
    df = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=candles, freq='15min'),
        'open': prices - 5,
        'high': prices + 15,
        'low': prices - 15,
        'close': prices,
        'volume': np.random.randint(100, 1000, candles)
    })
    
    # محاكاة FVG
    if trend == "bullish":
        df.loc[candles-1, 'low'] = df.loc[candles-3, 'high'] + 10
    else:
        df.loc[candles-1, 'high'] = df.loc[candles-3, 'low'] - 10
        
    return df

async def test_analysis():
    strategies = InstitutionalStrategies()
    
    print("\n--- Testing Bullish Scenario ---")
    df_bull = generate_mock_data(trend="bullish")
    analysis_bull = strategies.calculate_combined_score(df_bull)
    
    diag_logger.market_regime_phase(analysis_bull["regime_data"])
    diag_logger.indicators_phase(analysis_bull["indicators_data"])
    diag_logger.smart_money_phase(analysis_bull["smc_data"])
    diag_logger.strategy_validation_phase(analysis_bull["validation_data"])
    diag_logger.score_engine_phase(analysis_bull["score_data"])
    diag_logger.quality_phase(analysis_bull["quality_data"])
    diag_logger.final_decision_phase(analysis_bull)
    
    print("\n--- Testing JSON Serialization ---")
    safe_data = make_json_safe(analysis_bull)
    print(f"JSON Safe: {type(safe_data)}")
    try:
        json.dumps(safe_data)
        print("✅ JSON Serialization Success")
    except Exception as e:
        print(f"❌ JSON Serialization Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_analysis())
