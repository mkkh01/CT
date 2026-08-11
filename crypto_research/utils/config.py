from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import numpy as np
import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def ensure_dirs(cfg: dict[str, Any]) -> None:
    for key in ("cache_dir",):
        Path(cfg["data"][key]).mkdir(parents=True, exist_ok=True)
    for key in ("output_dir", "report_dir"):
        Path(cfg["research"][key]).mkdir(parents=True, exist_ok=True)
    for folder in ("logs",):
        Path(folder).mkdir(parents=True, exist_ok=True)
