#!/usr/bin/env python3
"""Reproducible long-only Spot backtest for Sweep + HTF POI + IFVG + CISD.

The strategy emits a signal only after the source candle closes and fills at the
next candle open.  It contains no exchange credentials and never sends orders.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVAL_MS = {"1h": 3_600_000}


@dataclass(frozen=True)
class CostModel:
    fee_bps: float
    slippage_bps: float
    half_spread_bps: float

    @property
    def fill_bps(self) -> float:
        return self.fee_bps + self.slippage_bps + self.half_spread_bps

    @property
    def buy_multiplier(self) -> float:
        return 1.0 + self.fill_bps / 10_000.0

    @property
    def sell_multiplier(self) -> float:
        return 1.0 - self.fill_bps / 10_000.0


BASE_COSTS = CostModel(fee_bps=10.0, slippage_bps=2.0, half_spread_bps=2.0)
STRESS_COSTS = CostModel(fee_bps=15.0, slippage_bps=5.0, half_spread_bps=4.0)


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "baseline"
    sweep_window: int = 12
    volume_multiplier: float = 0.0
    trend_filter: str = "none"
    cisd_atr_multiplier: float = 1.0
    target_r: float = 2.0
    max_bars_in_trade: int = 48
    stop_atr_multiplier: float = 0.25


DEFAULT_STRATEGY = StrategyConfig()
SignalContext = tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class Position:
    entry_time: pd.Timestamp
    entry_bar: int
    entry_raw: float
    entry_effective: float
    quantity: float
    stop: float
    target: float
    sweep_time: pd.Timestamp
    signal_time: pd.Timestamp
    cash_before: float


@dataclass
class BacktestResult:
    metrics: dict[str, Any]
    trades: pd.DataFrame
    equity: pd.DataFrame
    signals: pd.DataFrame


def utc_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def cache_path(data_dir: Path, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    return data_dir / f"{symbol}_1h_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"


def validate_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"{symbol}: missing OHLCV columns")
    if df.index.tz is None:
        raise ValueError(f"{symbol}: timestamps must be UTC-aware")
    df = df.sort_index().loc[~df.index.duplicated(keep="last")].copy()
    numeric = ["open", "high", "low", "close", "volume"]
    if not np.isfinite(df[numeric].to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol}: non-finite OHLCV value found")
    if (df[numeric] < 0).any().any() or (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{symbol}: negative or zero price found")
    if ((df["high"] < df[["open", "close", "low"]].max(axis=1)) | (df["low"] > df[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError(f"{symbol}: invalid high/low relationship")
    if not df.index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: timestamps are not ordered")
    return df


def download_klines(symbol: str, start: pd.Timestamp, end: pd.Timestamp, data_dir: Path, force: bool) -> pd.DataFrame:
    """Download completed 1h Binance Spot candles, pagination included."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(data_dir, symbol, start, end)
    if path.exists() and not force:
        cached = pd.read_csv(path, parse_dates=["timestamp"])
        cached["timestamp"] = pd.to_datetime(cached["timestamp"], utc=True)
        return validate_ohlcv(cached.set_index("timestamp"), symbol).loc[start:end]

    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[list[Any]] = []
    session = requests.Session()
    while cursor < end_ms:
        response = session.get(
            BASE_URL,
            params={"symbol": symbol, "interval": "1h", "startTime": cursor, "endTime": end_ms - 1, "limit": 1000},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + INTERVAL_MS["1h"]
        if next_cursor <= cursor:
            raise RuntimeError(f"{symbol}: non-advancing API pagination")
        cursor = next_cursor
        time.sleep(0.08)

    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
    raw = pd.DataFrame(rows, columns=columns)
    if raw.empty:
        raise RuntimeError(f"{symbol}: no data returned from Binance")
    raw["timestamp"] = pd.to_datetime(raw["open_time"], unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    df = raw.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
    df = validate_ohlcv(df, symbol).loc[start:end]
    df.reset_index().to_csv(path, index=False, compression="gzip")
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.rolling(14, min_periods=14).mean()
    frame["tr"] = true_range
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    frame["ema200"] = frame["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    frame["volume_sma20"] = frame["volume"].rolling(20, min_periods=20).mean()
    return frame


def confirmed_htf_zones(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Create demand zones from 4h pivot lows, only after two later 4h bars close."""
    htf = (
        df.resample("4h", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    zones: list[dict[str, Any]] = []
    for i in range(2, len(htf) - 2):
        left = htf["low"].iloc[i - 2 : i]
        right = htf["low"].iloc[i + 1 : i + 3]
        low = float(htf["low"].iloc[i])
        if low < float(left.min()) and low <= float(right.min()):
            pivot_time = htf.index[i]
            available = htf.index[i + 2] + pd.Timedelta(hours=4)
            invalidated_at: pd.Timestamp | None = None
            for j in range(i + 3, len(htf)):
                if float(htf["close"].iloc[j]) < low:
                    invalidated_at = htf.index[j] + pd.Timedelta(hours=4)
                    break
            zones.append(
                {
                    "pivot_time": pivot_time,
                    "available": available,
                    "low": low,
                    "high": float(max(htf["open"].iloc[i], htf["close"].iloc[i])),
                    "invalidated_at": invalidated_at,
                }
            )
    return zones


def active_zone_at(zones: list[dict[str, Any]], when: pd.Timestamp, candle_low: float, candle_close: float) -> dict[str, Any] | None:
    """Return the most recent observable demand zone touched by the candle."""
    candidates = [
        z
        for z in zones
        if z["available"] <= when
        and (z["invalidated_at"] is None or when < z["invalidated_at"])
        and candle_low <= z["high"]
        and candle_close >= z["low"]
    ]
    return max(candidates, key=lambda z: z["pivot_time"]) if candidates else None


def bearish_fvgs(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Bearish FVG: current high below low from two bars earlier."""
    gaps: list[dict[str, Any]] = []
    for i in range(2, len(df)):
        upper = float(df["low"].iloc[i - 2])
        lower = float(df["high"].iloc[i])
        if lower < upper:
            gaps.append({"created_bar": i, "created_time": df.index[i], "lower": lower, "upper": upper})
    return gaps


def recent_cisd(frame: pd.DataFrame, i: int, atr_multiplier: float = 1.0) -> bool:
    """Bullish displacement above the high of a recent bearish candle."""
    if i < 6 or not np.isfinite(frame["atr"].iloc[i]):
        return False
    candle = frame.iloc[i]
    if float(candle["close"]) <= float(candle["open"]) or float(candle["tr"]) < atr_multiplier * float(candle["atr"]):
        return False
    lookback = frame.iloc[max(0, i - 6) : i]
    bearish = lookback[lookback["close"] < lookback["open"]]
    if bearish.empty:
        return False
    return float(candle["close"]) > float(bearish["high"].iloc[-1])


def prepare_signal_context(df: pd.DataFrame) -> SignalContext:
    frame = add_indicators(df)
    return frame, confirmed_htf_zones(frame), bearish_fvgs(frame)


def find_signals(
    df: pd.DataFrame,
    config: StrategyConfig = DEFAULT_STRATEGY,
    context: SignalContext | None = None,
) -> pd.DataFrame:
    """Find valid sequential signals without reading future bars."""
    frame, zones, gaps = context if context is not None else prepare_signal_context(df)
    signals: list[dict[str, Any]] = []
    active_sweep: dict[str, Any] | None = None

    start_bar = max(30, 200 if config.trend_filter == "ema" else 30)
    for i in range(start_bar, len(frame) - 1):
        candle = frame.iloc[i]
        timestamp = frame.index[i]
        prior_low = float(frame["low"].iloc[i - config.sweep_window : i].min())
        volume_ok = config.volume_multiplier <= 0 or (
            np.isfinite(candle["volume_sma20"]) and float(candle["volume"]) >= config.volume_multiplier * float(candle["volume_sma20"])
        )
        trend_ok = config.trend_filter == "none" or (
            config.trend_filter == "ema"
            and np.isfinite(candle["ema50"])
            and np.isfinite(candle["ema200"])
            and float(candle["close"]) > float(candle["ema200"])
            and float(candle["ema50"]) > float(candle["ema200"])
        )
        is_sweep = bool(float(candle["low"]) < prior_low and float(candle["close"]) > prior_low and volume_ok and trend_ok)
        zone = active_zone_at(zones, timestamp, float(candle["low"]), float(candle["close"]))
        if is_sweep and zone is not None and np.isfinite(candle["atr"]):
            active_sweep = {
                "bar": i,
                "time": timestamp,
                "low": float(candle["low"]),
                "atr": float(candle["atr"]),
                "zone_pivot": zone["pivot_time"],
                "zone_low": zone["low"],
                "zone_high": zone["high"],
            }

        if active_sweep is None:
            continue
        if i - int(active_sweep["bar"]) > 8:
            active_sweep = None
            continue
        if i <= int(active_sweep["bar"]):
            continue

        matching_gaps = [
            g
            for g in gaps
            if g["created_bar"] < i
            and i - int(g["created_bar"]) <= 30
            and float(candle["low"]) <= float(g["upper"])
            and float(candle["close"]) > float(g["upper"])
        ]
        if recent_cisd(frame, i, config.cisd_atr_multiplier) and matching_gaps:
            gap = matching_gaps[-1]
            signals.append(
                {
                    "signal_time": timestamp,
                    "signal_bar": i,
                    "entry_bar": i + 1,
                    "entry_time": frame.index[i + 1],
                    "sweep_time": active_sweep["time"],
                    "sweep_low": active_sweep["low"],
                    "atr": active_sweep["atr"],
                    "zone_pivot": active_sweep["zone_pivot"],
                    "zone_low": active_sweep["zone_low"],
                    "zone_high": active_sweep["zone_high"],
                    "fvg_created": gap["created_time"],
                    "fvg_lower": gap["lower"],
                    "fvg_upper": gap["upper"],
                    "strategy": config.name,
                }
            )
            active_sweep = None
    columns = ["signal_time", "signal_bar", "entry_bar", "entry_time", "sweep_time", "sweep_low", "atr", "zone_pivot", "zone_low", "zone_high", "fvg_created", "fvg_lower", "fvg_upper"]
    return pd.DataFrame(signals, columns=columns)


def max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0


def calculate_metrics(equity: pd.DataFrame, trades: pd.DataFrame, initial_capital: float, buy_hold_return: float) -> dict[str, Any]:
    final_equity = float(equity["equity"].iloc[-1])
    duration_days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86_400.0, 1.0)
    total_return = final_equity / initial_capital - 1.0
    cagr = (final_equity / initial_capital) ** (365.25 / duration_days) - 1.0 if final_equity > 0 else -1.0
    returns = equity["equity"].pct_change().dropna()
    sharpe = 0.0
    if len(returns) > 2 and float(returns.std(ddof=1)) > 0:
        sharpe = float(np.sqrt(24 * 365.25) * returns.mean() / returns.std(ddof=1))
    if trades.empty:
        win_rate = profit_factor = expectancy = 0.0
        avg_hold = 0.0
    else:
        winners = trades.loc[trades["net_pnl"] > 0, "net_pnl"]
        losers = trades.loc[trades["net_pnl"] < 0, "net_pnl"]
        win_rate = float((trades["net_pnl"] > 0).mean())
        profit_factor = float(winners.sum() / abs(losers.sum())) if not losers.empty else (float("inf") if not winners.empty else 0.0)
        expectancy = float(trades["net_pnl"].mean())
        avg_hold = float(trades["holding_bars"].mean())
    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_return": total_return,
        "buy_hold_return": buy_hold_return,
        "excess_vs_buy_hold": total_return - buy_hold_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown(equity["equity"]),
        "sharpe_hourly_annualized": sharpe,
        "trades": int(len(trades)),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy_usdt": expectancy,
        "average_holding_bars": avg_hold,
        "start": equity.index[0].isoformat(),
        "end": equity.index[-1].isoformat(),
    }


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float,
    risk_per_trade: float,
    costs: CostModel,
    config: StrategyConfig = DEFAULT_STRATEGY,
    context: SignalContext | None = None,
) -> BacktestResult:
    frame = context[0] if context is not None else add_indicators(df)
    signals = find_signals(df, config, context)
    signal_by_entry = {int(row.entry_bar): row for row in signals.itertuples(index=False)}
    cash = float(initial_capital)
    position: Position | None = None
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for i in range(len(frame)):
        candle = frame.iloc[i]
        when = frame.index[i]
        if position is None and i in signal_by_entry:
            signal = signal_by_entry[i]
            raw_entry = float(candle["open"])
            entry = raw_entry * costs.buy_multiplier
            stop = float(signal.sweep_low) - config.stop_atr_multiplier * float(signal.atr)
            if stop > 0 and stop < entry:
                unit_risk = entry - stop
                risk_quantity = (cash * risk_per_trade) / unit_risk
                quantity = min(risk_quantity, cash / entry)
                if quantity > 0:
                    target = entry + config.target_r * unit_risk
                    position = Position(
                        entry_time=when,
                        entry_bar=i,
                        entry_raw=raw_entry,
                        entry_effective=entry,
                        quantity=quantity,
                        stop=stop,
                        target=target,
                        sweep_time=signal.sweep_time,
                        signal_time=signal.signal_time,
                        cash_before=cash,
                    )
                    cash -= quantity * entry

        if position is not None:
            hit_stop = float(candle["low"]) <= position.stop
            hit_target = float(candle["high"]) >= position.target
            time_exit = i - position.entry_bar >= config.max_bars_in_trade
            if hit_stop or hit_target or time_exit:
                if hit_stop:  # Conservative if stop and target occurred inside one candle.
                    exit_raw, reason = position.stop, "stop"
                elif hit_target:
                    exit_raw, reason = position.target, "target"
                else:
                    exit_raw, reason = float(candle["close"]), "time"
                exit_effective = exit_raw * costs.sell_multiplier
                proceeds = position.quantity * exit_effective
                cash += proceeds
                trade_rows.append(
                    {
                        "signal_time": position.signal_time,
                        "sweep_time": position.sweep_time,
                        "entry_time": position.entry_time,
                        "exit_time": when,
                        "entry_raw": position.entry_raw,
                        "entry_effective": position.entry_effective,
                        "stop": position.stop,
                        "target": position.target,
                        "exit_raw": exit_raw,
                        "exit_effective": exit_effective,
                        "quantity": position.quantity,
                        "cash_before": position.cash_before,
                        "cash_after": cash,
                        "net_pnl": cash - position.cash_before,
                        "net_return_on_equity": cash / position.cash_before - 1.0,
                        "holding_bars": i - position.entry_bar + 1,
                        "exit_reason": reason,
                    }
                )
                position = None

        mark_equity = cash if position is None else cash + position.quantity * float(candle["close"]) * costs.sell_multiplier
        equity_rows.append({"timestamp": when, "equity": mark_equity, "cash": cash, "in_position": position is not None})

    if position is not None:
        candle = frame.iloc[-1]
        exit_raw = float(candle["close"])
        exit_effective = exit_raw * costs.sell_multiplier
        cash += position.quantity * exit_effective
        trade_rows.append(
            {
                "signal_time": position.signal_time,
                "sweep_time": position.sweep_time,
                "entry_time": position.entry_time,
                "exit_time": frame.index[-1],
                "entry_raw": position.entry_raw,
                "entry_effective": position.entry_effective,
                "stop": position.stop,
                "target": position.target,
                "exit_raw": exit_raw,
                "exit_effective": exit_effective,
                "quantity": position.quantity,
                "cash_before": position.cash_before,
                "cash_after": cash,
                "net_pnl": cash - position.cash_before,
                "net_return_on_equity": cash / position.cash_before - 1.0,
                "holding_bars": len(frame) - position.entry_bar,
                "exit_reason": "end_of_sample",
            }
        )
        equity_rows[-1]["equity"] = cash
        equity_rows[-1]["cash"] = cash
        equity_rows[-1]["in_position"] = False

    equity = pd.DataFrame(equity_rows).set_index("timestamp")
    trades = pd.DataFrame(trade_rows)
    buy_hold = (float(frame["close"].iloc[-1]) * costs.sell_multiplier) / (float(frame["open"].iloc[0]) * costs.buy_multiplier) - 1.0
    metrics = calculate_metrics(equity, trades, initial_capital, buy_hold)
    return BacktestResult(metrics=metrics, trades=trades, equity=equity, signals=signals)


def slice_period(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return df.loc[utc_timestamp(start) : utc_timestamp(end)]


def display_pct(value: float) -> str:
    if math.isinf(value):
        return "∞"
    return f"{100.0 * value:.2f}%"


def write_report(summary: pd.DataFrame, output: Path, start: pd.Timestamp, end: pd.Timestamp, symbols: list[str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    display = summary.copy()
    percent_cols = ["net_return", "buy_hold_return", "excess_vs_buy_hold", "cagr", "max_drawdown", "win_rate"]
    for col in percent_cols:
        if col in display:
            display[col] = display[col].map(display_pct)
    for col in ["final_equity", "expectancy_usdt"]:
        if col in display:
            display[col] = display[col].map(lambda x: f"{x:,.2f}")
    if "profit_factor" in display:
        display["profit_factor"] = display["profit_factor"].map(lambda x: "∞" if math.isinf(float(x)) else f"{float(x):.2f}")
    markdown_table = display.to_markdown(index=False)
    robust = summary[(summary["split"] == "oos") & (summary["scenario"] == "base")]
    median_return = float(robust["net_return"].median()) if not robust.empty else float("nan")
    positive = int((robust["net_return"] > 0).sum()) if not robust.empty else 0
    conclusion = "لم تثبت الصياغة الحالية ميزة متينة خارج العينة." if robust.empty or positive < max(2, len(symbols)) or median_return <= 0 else "أظهرت الصياغة الحالية نتائج موجبة في أغلب الرموز خارج العينة، لكنها تحتاج اختباراً مستقلاً إضافياً قبل أي استخدام." 
    report = f"""# تقرير الباك تيست: Sweep + HTF POI + IFVG + CISD

> **تنبيه:** أنا لست مستشاراً مالياً مرخّصاً. هذا تحليل بحثي تاريخي وليس نصيحة استثمارية أو ضماناً للربح؛ الاستثمار في الأصول المشفرة ينطوي على مخاطر.

## النطاق

اختبرنا نظام Spot طويل فقط على شموع ساعة عامة من Binance للأزواج {', '.join(symbols)} خلال الفترة من `{start.isoformat()}` إلى `{end.isoformat()}`. يدخل النظام في افتتاح الشمعة التالية للإشارة، ولا يبيع على المكشوف ولا يستخدم الرافعة. المواصفات الدقيقة وتعريفات الشروط الأربع موجودة في [`docs/strategy_spec.md`](../docs/strategy_spec.md).

التكاليف في سيناريو الأساس هي 10 نقاط أساس رسوم تنفيذ + نقطتا أساس انزلاق + نقطتا أساس نصف فارق سعر لكل جهة. وتكرر نتيجة الضغط بكلفة 15 + 5 + 4 نقاط أساس لكل جهة. سياسة اللمس داخل الشمعة تحفظية: إذا لمس السعر وقف الخسارة والهدف في الشمعة ذاتها، يُسجّل الوقف أولاً.

## النتائج

{markdown_table}

## القراءة الصحيحة للنتيجة

{conclusion} يُفحص العائد الصافي بعد التكاليف جنباً إلى جنب مع `Profit Factor` و`Max Drawdown` وعدد الصفقات، ولا تكفي نسبة الفوز وحدها للحكم على الاستراتيجية. يمثل `Buy & Hold` شراءً في بداية الشريحة وبيعاً في نهايتها تحت افتراض التكاليف ذاته، ولذلك فإن `Excess vs Buy & Hold` يوضح ما إذا كانت إدارة الدخول والخروج أضافت قيمة ضمن العينة المعنية.

## القيود المهمة

بيانات OHLCV بالساعة لا تحدد ترتيب الحركة داخل الشمعة؛ لهذا اختيرت سياسة وقف أولاً لتجنب تضخيم النتائج. كما أن POI وIFVG وCISD مصطلحات تحليلية تقديرية، والنتيجة تخص تعريفها الكمي هنا فقط. واختيار الرموز الحالية السائلة لا يمثل كوناً تاريخياً كاملاً، وقد يحمل تحيز البقاء. لا توجد في هذا المشروع أوامر تداول حقيقية أو مفاتيح وصول للمنصات.

## المراجع

[1]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints "Binance Spot API: market-data endpoints"
[2]: https://data.binance.vision/ "Binance public market-data archive"

**الإفصاح:** الأساس هو عوائد صافية بعد رسوم وانزلاق وفارق سعر مفترضين؛ زمن البيانات هو نطاق التشغيل أعلاه؛ المعلمات ثابتة كما في المواصفة؛ المصدر هو بيانات Binance Spot العامة مع تحققات OHLCV محلية. هذا بحث وتحليل فقط وليس نصيحة مالية شخصية.
"""
    (output / "backtest_report.md").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spot long-only backtest for Sweep + HTF POI + IFVG + CISD")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-08-01", help="exclusive UTC date")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.01)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.no_download and args.force_download:
        raise ValueError("--no-download and --force-download cannot be combined")
    start, end = utc_timestamp(args.start), utc_timestamp(args.end)
    if end <= start:
        raise ValueError("end must be after start")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    data_dir, output_dir = Path(args.data_dir), Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "development": ("2022-01-01", "2024-06-30 23:00:00"),
        "validation": ("2024-07-01", "2025-03-31 23:00:00"),
        "oos": ("2025-04-01", "2026-07-31 23:00:00"),
    }
    all_rows: list[dict[str, Any]] = []
    run_metadata = {
        "symbols": symbols,
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "source": BASE_URL,
        "interval": "1h",
        "base_costs": asdict(BASE_COSTS),
        "stress_costs": asdict(STRESS_COSTS),
        "risk_per_trade": args.risk_per_trade,
        "initial_capital_per_symbol": args.initial_capital,
        "same_bar_policy": "conservative_stop_first",
        "entry_policy": "next_bar_open_after_signal_close",
    }
    (output_dir / "run_metadata.json").write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")

    for symbol in symbols:
        path = cache_path(data_dir, symbol, start, end)
        if args.no_download and not path.exists():
            raise FileNotFoundError(f"Cache not found for {symbol}: {path}")
        df = download_klines(symbol, start, end, data_dir, force=args.force_download) if not args.no_download else download_klines(symbol, start, end, data_dir, force=False)
        for split_name, (split_start, split_end) in splits.items():
            period = slice_period(df, split_start, split_end)
            if len(period) < 200:
                continue
            for scenario, costs in (("base", BASE_COSTS), ("stress", STRESS_COSTS)):
                result = run_backtest(period, args.initial_capital, args.risk_per_trade, costs)
                result.trades.to_csv(output_dir / f"trades_{symbol}_{split_name}_{scenario}.csv", index=False)
                result.signals.to_csv(output_dir / f"signals_{symbol}_{split_name}_{scenario}.csv", index=False)
                result.equity.reset_index().to_csv(output_dir / f"equity_{symbol}_{split_name}_{scenario}.csv", index=False)
                row = {"symbol": symbol, "split": split_name, "scenario": scenario, **result.metrics}
                all_rows.append(row)
                print(f"{symbol} {split_name:11s} {scenario:6s} return={result.metrics['net_return']:.2%} trades={result.metrics['trades']} PF={result.metrics['profit_factor']:.2f}")

    summary = pd.DataFrame(all_rows)
    summary.to_csv(output_dir / "summary.csv", index=False)
    write_report(summary, output_dir, start, end, symbols)
    print(f"Wrote {output_dir / 'summary.csv'} and {output_dir / 'backtest_report.md'}")


if __name__ == "__main__":
    main()
