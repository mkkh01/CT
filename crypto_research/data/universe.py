from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


def _get(base_url: str, path: str, timeout: int = 30) -> Any:
    response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def discover_spot_symbols(
    base_url: str,
    quote_asset: str = "USDT",
    max_symbols: int = 30,
    exclude_base_assets: list[str] | None = None,
) -> pd.DataFrame:
    info = _get(base_url, "/api/v3/exchangeInfo")
    excluded = {x.upper() for x in (exclude_base_assets or [])}
    eligible = []
    for item in info.get("symbols", []):
        if item.get("quoteAsset") != quote_asset.upper():
            continue
        if item.get("status") != "TRADING":
            continue
        if item.get("isSpotTradingAllowed") is False:
            continue
        if item.get("baseAsset", "").upper() in excluded:
            continue
        eligible.append({
            "symbol": item["symbol"], "base_asset": item["baseAsset"],
            "quote_asset": item["quoteAsset"], "status": item["status"],
            "source": "binance_exchange_info", "discovered_at": datetime.now(timezone.utc).isoformat(),
        })
    frame = pd.DataFrame(eligible)
    if frame.empty:
        return frame
    try:
        ticker = _get(base_url, "/api/v3/ticker/24hr")
        ticker_df = pd.DataFrame(ticker)
        ticker_df["quoteVolume"] = pd.to_numeric(ticker_df["quoteVolume"], errors="coerce")
        frame = frame.merge(ticker_df[["symbol", "quoteVolume"]], on="symbol", how="left")
        frame = frame.sort_values("quoteVolume", ascending=False, na_position="last")
    except Exception:
        frame["quoteVolume"] = float("nan")
    return frame.head(max_symbols).reset_index(drop=True)


def add_user_symbol(
    symbol: str,
    universe: pd.DataFrame,
    base_url: str,
    quote_asset: str = "USDT",
) -> pd.DataFrame:
    symbol = symbol.upper().replace("/", "")
    info = _get(base_url, "/api/v3/exchangeInfo")
    item = next((x for x in info.get("symbols", []) if x.get("symbol") == symbol), None)
    if item is None or item.get("status") != "TRADING" or item.get("quoteAsset") != quote_asset.upper() or item.get("isSpotTradingAllowed") is False:
        raise ValueError(f"{symbol} is not an active Binance Spot {quote_asset} symbol")
    row = pd.DataFrame([{
        "symbol": symbol, "base_asset": item["baseAsset"], "quote_asset": item["quoteAsset"],
        "status": item["status"], "source": "user_added", "discovered_at": datetime.now(timezone.utc).isoformat(),
        "quoteVolume": float("nan"),
    }])
    return pd.concat([universe, row], ignore_index=True).drop_duplicates("symbol").reset_index(drop=True)


def save_universe(frame: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
