"""
File: engine/market_location.py
Responsibility: Analyze current price location relative to key structural levels 
(Resistance/Support) to avoid entering into "walls".
"""

from typing import List, Optional, Dict, Any
from config.thresholds import RESISTANCE_PROXIMITY_THRESHOLD
from monitoring.logger import get_logger

logger = get_logger(__name__)

def is_near_resistance(
    current_price: float,
    levels: List[float],
    direction: str,
    threshold_pct: float = RESISTANCE_PROXIMITY_THRESHOLD
) -> bool:
    """
    Check if the current price is too close to a resistance level in the trade direction.
    
    Args:
        current_price: Current market price.
        levels: List of price levels (Swing Highs, OBs, etc.) to check.
        direction: 'long' or 'short'.
        threshold_pct: Proximity threshold in percentage.
        
    Returns:
        True if price is within threshold of any level in the trade direction.
    """
    if not levels or current_price <= 0:
        return False
        
    for level in levels:
        if direction == "long":
            # Resistance is above us
            if level > current_price:
                dist_pct = ((level - current_price) / current_price) * 100.0
                if dist_pct < threshold_pct:
                    return True
        elif direction == "short":
            # Resistance (Support) is below us
            if level < current_price:
                dist_pct = ((current_price - level) / current_price) * 100.0
                if dist_pct < threshold_pct:
                    return True
                    
    return False

def get_structural_levels(analysis: Any) -> List[float]:
    """Extract price levels from analysis results."""
    levels = []
    
    # Swing points
    swings = analysis.smc.get("swings", [])
    for s in swings:
        levels.append(s.price)
        
    # Order Blocks
    obs = analysis.smc.get("order_blocks", [])
    for ob in obs:
        levels.append(ob.mitigation_level)
        
    # FVGs
    fvgs = analysis.smc.get("fvgs", [])
    for fvg in fvgs:
        levels.append(fvg.top)
        levels.append(fvg.bottom)
        
    return list(set(levels))
