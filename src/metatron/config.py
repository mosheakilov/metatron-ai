"""Load config.yaml and resolve paths relative to the project root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"


class Config(dict):
    """Plain dict with attribute access for top-level sections."""

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as e:
            raise AttributeError(name) from e
        return Config(value) if isinstance(value, dict) else value

    def path(self, value: str | os.PathLike) -> Path:
        """Resolve a config path relative to the project root."""
        p = Path(value)
        return p if p.is_absolute() else ROOT / p


def load_config(path: str | os.PathLike | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    # No telemetry or trace prompts: runs must be quiet and reproducible.
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as f:
        cfg = Config(yaml.safe_load(f))
    mode = os.getenv("METATRON_LLM_MODE")
    if mode:
        cfg["llm"]["mode"] = mode
    return cfg
