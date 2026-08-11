from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd


@dataclass(frozen=True)
class TimeWindow:
    window_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def walk_forward_windows(
    frame: pd.DataFrame,
    train_days: int,
    validation_days: int,
    test_days: int,
    step_days: int,
) -> list[TimeWindow]:
    ts = pd.to_datetime(frame["timestamp"], utc=True).sort_values().reset_index(drop=True)
    if ts.empty:
        return []
    start = ts.iloc[0]
    last = ts.iloc[-1]
    windows: list[TimeWindow] = []
    i = 0
    cursor = start
    while cursor + pd.Timedelta(days=train_days + validation_days + test_days) <= last:
        train_end = cursor + pd.Timedelta(days=train_days)
        val_start = train_end
        val_end = val_start + pd.Timedelta(days=validation_days)
        test_start = val_end
        test_end = test_start + pd.Timedelta(days=test_days)
        windows.append(TimeWindow(i, cursor, train_end, val_start, val_end, test_start, test_end))
        cursor += pd.Timedelta(days=step_days)
        i += 1
    return windows


def slice_window(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, include_end: bool = False) -> pd.DataFrame:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    mask = (ts >= start) & (ts <= end if include_end else ts < end)
    return frame.loc[mask].copy().reset_index(drop=True)


def purge_embargo(frame: pd.DataFrame, train_end: pd.Timestamp, validation_start: pd.Timestamp, purge_bars: int, embargo_bars: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(ordered["timestamp"], utc=True)
    train = ordered.loc[ts < train_end].copy()
    validation = ordered.loc[ts >= validation_start].copy()
    if purge_bars:
        train = train.iloc[:-purge_bars] if len(train) > purge_bars else train.iloc[0:0]
    if embargo_bars:
        validation = validation.iloc[embargo_bars:]
    return train.reset_index(drop=True), validation.reset_index(drop=True)


def temporal_split(frame: pd.DataFrame, train_days: int, validation_days: int, test_days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    start = ts.min()
    train_end = start + pd.Timedelta(days=train_days)
    validation_end = train_end + pd.Timedelta(days=validation_days)
    test_end = validation_end + pd.Timedelta(days=test_days)
    train = frame.loc[ts < train_end].copy()
    validation = frame.loc[(ts >= train_end) & (ts < validation_end)].copy()
    test = frame.loc[(ts >= validation_end) & (ts < test_end)].copy()
    return train.reset_index(drop=True), validation.reset_index(drop=True), test.reset_index(drop=True)
