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

def _read(obj: Any, key: str, default: Any = None) -> Any:
    """Safely read an attribute or dict key from ``obj``.

    Works with both Pydantic models (attribute access) and plain dicts
    (key lookup), returning ``default`` when the key/attribute is absent.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def get_structural_levels(analysis: Any) -> List[float]:
    """Extract price levels from analysis results.

    Looks at ``analysis.smc`` for swings, order blocks, and FVGs.
    Also checks ``analysis.structure`` for swing highs/lows as a fallback.
    Handles both Pydantic models and plain dicts gracefully.
    """
    levels: List[float] = []

    smc = getattr(analysis, "smc", None) or {}
    if isinstance(smc, dict):
        smc_data = smc
    else:
        # Pydantic model or object
        smc_data = vars(smc) if hasattr(smc, "__dict__") else {}

    # Swing points
    swings = smc_data.get("swings", [])
    for s in swings:
        price = _read(s, "price", None)
        if price is not None:
            try:
                levels.append(float(price))
            except (TypeError, ValueError):
                pass

    # Order Blocks
    obs = smc_data.get("order_blocks", [])
    for ob in obs:
        mitigation = _read(ob, "mitigation_level", None)
        if mitigation is not None:
            try:
                levels.append(float(mitigation))
            except (TypeError, ValueError):
                pass

    # FVGs
    fvgs = smc_data.get("fvgs", [])
    for fvg in fvgs:
        top = _read(fvg, "top", None)
        bottom = _read(fvg, "bottom", None)
        if top is not None:
            try:
                levels.append(float(top))
            except (TypeError, ValueError):
                pass
        if bottom is not None:
            try:
                levels.append(float(bottom))
            except (TypeError, ValueError):
                pass

    # Fallback: check analysis.structure for swing highs/lows
    structure = getattr(analysis, "structure", None)
    if structure is not None:
        last_high = _read(structure, "last_swing_high", None)
        last_low = _read(structure, "last_swing_low", None)
        if last_high is not None:
            price = _read(last_high, "price", None)
            if price is not None:
                try:
                    levels.append(float(price))
                except (TypeError, ValueError):
                    pass
        if last_low is not None:
            price = _read(last_low, "price", None)
            if price is not None:
                try:
                    levels.append(float(price))
                except (TypeError, ValueError):
                    pass

    return list(set(levels))
