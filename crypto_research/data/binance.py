from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

LOG = logging.getLogger(__name__)

COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trade_count",
    "taker_buy_base_volume", "taker_buy_quote_volume", "symbol",
]


@dataclass(frozen=True)
class BinanceClient:
    base_url: str = "https://api.binance.com"
    pause_seconds: float = 0.15
    timeout: int = 30
    max_retries: int = 5

    def _request(self, params: dict) -> list:
        url = f"{self.base_url}/api/v3/klines"
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429:
                    wait = float(response.headers.get("Retry-After", "2"))
                    time.sleep(wait * (attempt + 1))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise RuntimeError(f"Unexpected Binance response: {payload}")
                return payload
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                time.sleep(min(30.0, 2.0 ** attempt))
        raise RuntimeError(f"Binance request failed after retries: {last_error}")

    def fetch_symbol(
        self,
        symbol: str,
        interval: str,
        start: str | datetime,
        end: str | datetime | None = None,
    ) -> pd.DataFrame:
        start_ms = _to_ms(start)
        end_ms = _to_ms(end) if end is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        rows: list[list] = []
        cursor = start_ms
        while cursor < end_ms:
            payload = self._request({
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            })
            if not payload:
                break
            rows.extend(payload)
            last_open = int(payload[-1][0])
            next_cursor = last_open + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(payload) < 1000:
                break
            time.sleep(self.pause_seconds)
        frame = _normalize(rows, symbol)
        now = pd.Timestamp.now(tz="UTC")
        if not frame.empty:
            frame = frame.loc[frame["close_time"] <= now].reset_index(drop=True)
        return frame


def _to_ms(value: str | datetime | None) -> int:
    if value is None:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    ts = pd.Timestamp(value, tz="UTC")
    return int(ts.timestamp() * 1000)


def _normalize(rows: list[list], symbol: str) -> pd.DataFrame:
    records = []
    for row in rows:
        if len(row) < 12:
            continue
        records.append({
            "timestamp": pd.to_datetime(int(row[0]), unit="ms", utc=True),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": pd.to_datetime(int(row[6]), unit="ms", utc=True),
            "quote_volume": float(row[7]), "trade_count": int(row[8]),
            "taker_buy_base_volume": float(row[9]),
            "taker_buy_quote_volume": float(row[10]),
            "symbol": symbol.upper(),
        })
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(records, columns=COLUMNS).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def cache_path(cache_dir: str | Path, symbol: str, interval: str, start: str, end: str | None) -> Path:
    token = f"{symbol.upper()}|{interval}|{start}|{end or 'now'}".encode()
    digest = hashlib.sha256(token).hexdigest()[:16]
    return Path(cache_dir) / f"{symbol.upper()}_{interval}_{digest}.parquet"


def load_or_download(
    client: BinanceClient,
    cache_dir: str | Path,
    symbol: str,
    interval: str,
    start: str,
    end: str | None,
    force: bool = False,
) -> tuple[pd.DataFrame, Path]:
    path = cache_path(cache_dir, symbol, interval, start, end)
    if path.exists() and not force:
        cached = pd.read_parquet(path)
        now = pd.Timestamp.now(tz="UTC")
        if "close_time" in cached.columns:
            cached = cached.loc[pd.to_datetime(cached["close_time"], utc=True) <= now].reset_index(drop=True)
        return cached, path
    frame = client.fetch_symbol(symbol, interval, start, end)
    if frame.empty:
        raise ValueError(f"No candles returned for {symbol} {interval}")
    frame.to_parquet(path, index=False)
    return frame, path


def download_universe(cfg: dict, force: bool = False) -> dict[str, pd.DataFrame]:
    data_cfg = cfg["data"]
    symbols = list(data_cfg["symbols"])[: int(data_cfg.get("max_symbols", 30))]
    client_kwargs = {
        "base_url": cfg["exchange"]["base_url"],
        "pause_seconds": float(cfg["exchange"].get("request_pause_seconds", 0.15)),
    }

    def load_one(symbol: str) -> tuple[str, pd.DataFrame, Path]:
        client = BinanceClient(**client_kwargs)
        LOG.info("Loading %s %s", symbol, data_cfg["interval"])
        frame, path = load_or_download(
            client, data_cfg["cache_dir"], symbol, data_cfg["interval"],
            data_cfg["start"], data_cfg.get("end"), force=force,
        )
        return symbol, frame, path

    universe: dict[str, pd.DataFrame] = {}
    workers = max(1, min(int(cfg["exchange"].get("download_workers", 5)), len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(load_one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                name, frame, path = future.result()
                universe[name] = frame
                LOG.info("%s: %d rows cached at %s", name, len(frame), path)
            except Exception as exc:
                LOG.error("Skipping %s after download failure: %s", symbol, exc)
    return dict(sorted(universe.items()))
