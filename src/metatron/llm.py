"""Decide whether agents run on a real LLM or in deterministic offline mode."""

from __future__ import annotations

import os

from metatron.config import Config


def use_llm(cfg: Config) -> bool:
    mode = cfg["llm"]["mode"]
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if mode == "offline":
        return False
    if mode == "crew":
        if not has_key:
            raise RuntimeError("llm.mode=crew but ANTHROPIC_API_KEY is not set")
        return True
    return has_key


def get_llm(cfg: Config, tier: str = "smart"):
    """Return a CrewAI LLM for the given tier ("smart" | "fast")."""
    from crewai import LLM

    return LLM(model=cfg["llm"]["models"][tier], temperature=0.2)
