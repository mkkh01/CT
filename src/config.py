"""
Configuration Module for Smart Trading Bot (Integrated with CT)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import os
from config import settings

class CapitalMode(Enum):
    SMALL = "small"
    MEDIUM = "medium"

@dataclass
class RiskConfig:
    risk_per_trade: float
    max_daily_loss: float
    max_leverage: int
    max_positions: int
    max_lot_size: float
    min_lot_size: float
    lot_step: float

@dataclass
class SMCConfig:
    swing_length: int = 5
    fvg_min_gap_pips: float = 2.0
    ob_lookback: int = 10
    bos_close_break: bool = True

@dataclass
class MLConfig:
    model_path: str = "models/xgboost_model.pkl" # Updated to .pkl
    confidence_threshold: float = 0.65
    retrain_frequency_days: int = 7
    lookback_periods: int = 1000

@dataclass
class ThresholdsConfig:
    ml_min_confidence: float = 0.65
    ml_entry_confidence: float = 0.70
    ml_high_confidence: float = 0.75
    ml_very_high_confidence: float = 0.80
    dynamic_threshold_aggressive: float = 0.65
    dynamic_threshold_moderate: float = 0.70
    dynamic_threshold_conservative: float = 0.75
    trend_reversal_confidence: float = 0.75
    protected_mode_threshold: float = 0.80
    min_profit_to_secure: float = 15.0
    good_profit_level: float = 25.0
    great_profit_level: float = 40.0
    trade_cooldown_seconds: int = 300
    loop_interval_seconds: float = 30.0
    sydney_lot_multiplier: float = 0.5

@dataclass
class RegimeConfig:
    n_regimes: int = 3
    lookback_periods: int = 500
    retrain_frequency: int = 20

@dataclass
class AdvancedExitConfig:
    enabled: bool = True
    ekf_friction: float = 0.05
    ekf_accel_decay: float = 0.95
    ekf_adaptive_noise: bool = True
    ekf_process_noise: float = 0.01
    ekf_measurement_noise_profit: float = 0.25
    ekf_measurement_noise_velocity: float = 0.05
    ekf_measurement_noise_momentum: float = 0.10
    pid_kp: float = 0.15
    pid_ki: float = 0.05
    pid_kd: float = 0.10
    pid_target_velocity: float = 0.10
    pid_max_integral: float = 0.5
    pid_output_min: float = -0.2
    pid_output_max: float = 0.2
    fuzzy_exit_threshold: float = 0.70
    fuzzy_warning_threshold: float = 0.50
    fuzzy_partial_threshold: float = 0.75
    toxicity_threshold: float = 1.5
    toxicity_critical: float = 2.5
    ofi_divergence_threshold: float = 0.3
    hjb_theta: float = 0.5
    hjb_mu: float = 0.0
    hjb_sigma: float = 1.0
    hjb_exit_cost: float = 0.1
    kelly_base_win_rate: float = 0.55
    kelly_avg_win: float = 8.0
    kelly_avg_loss: float = 4.0
    kelly_fraction: float = 0.5
    kelly_hold_threshold: float = 0.70
    kelly_partial_threshold: float = 0.25

@dataclass
class TradingConfig:
    mt5_login: int = field(default_factory=lambda: settings.MT5_LOGIN)
    mt5_password: str = field(default_factory=lambda: settings.MT5_PASSWORD)
    mt5_server: str = field(default_factory=lambda: settings.MT5_SERVER)
    mt5_path: Optional[str] = field(default_factory=lambda: settings.MT5_PATH)
    simulation_mode: bool = field(default_factory=lambda: settings.SIMULATION_MODE)
    symbol: str = field(default_factory=lambda: settings.SYMBOL)
    execution_timeframe: str = field(default_factory=lambda: settings.TIMEFRAME)
    trend_timeframe: str = "H4"
    capital: float = field(default_factory=lambda: settings.CAPITAL)
    capital_mode: CapitalMode = CapitalMode.SMALL
    risk: RiskConfig = field(default_factory=lambda: RiskConfig(
        risk_per_trade=settings.RISK_PER_TRADE,
        max_daily_loss=3.0,
        max_leverage=100,
        max_positions=3,
        max_lot_size=0.5,
        min_lot_size=0.01,
        lot_step=0.01,
    ))
    smc: SMCConfig = field(default_factory=SMCConfig)
    ml: MLConfig = field(default_factory=MLConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    advanced_exit: AdvancedExitConfig = field(default_factory=AdvancedExitConfig)
    slippage_points: int = 20
    magic_number: int = 123456
    flash_crash_threshold: float = 2.5

    def __post_init__(self):
        self._configure_by_capital()

    def _configure_by_capital(self):
        if self.capital <= 10000:
            self.capital_mode = CapitalMode.SMALL
            self.risk.risk_per_trade = settings.RISK_PER_TRADE
        else:
            self.capital_mode = CapitalMode.MEDIUM
            self.risk.risk_per_trade = settings.RISK_PER_TRADE
            self.risk.max_positions = 5
            self.risk.max_lot_size = 2.0

    @classmethod
    def from_env(cls) -> "TradingConfig":
        return cls()

def get_config() -> TradingConfig:
    return TradingConfig.from_env()
