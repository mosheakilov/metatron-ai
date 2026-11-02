"""Decide whether agents run on a real LLM or in deterministic offline mode.

Two ways to reach Claude:
- course / developer: ANTHROPIC_API_KEY in .env, through CrewAI's LLM;
- installed product: METATRON's relay (llm.proxy_url + the broker's license key). The API key
  stays on the relay and never ships inside the app.
"""

from __future__ import annotations

import os

import httpx

from metatron.config import Config


def _proxy(cfg: Config) -> tuple[str, str]:
    llm = cfg["llm"]
    return llm.get("proxy_url") or "", llm.get("license_key") or ""


def use_llm(cfg: Config) -> bool:
    mode = cfg["llm"]["mode"]
    has_key = bool(os.getenv("ANTHROPIC_API_KEY")) or all(_proxy(cfg))
    if mode == "offline":
        return False
    if mode == "crew":
        if not has_key:
            raise RuntimeError("llm.mode=crew but ANTHROPIC_API_KEY is not set")
        return True
    return has_key


class RelayLLM:
    """Minimal `.call(messages=...)` client for the METATRON relay (Anthropic Messages API shape)."""

    def __init__(self, url: str, license_key: str, model: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/") + "/v1/messages"
        self.license_key = license_key
        self.model = model.removeprefix("anthropic/")
        self.client = client or httpx.Client(timeout=60)

    def call(self, messages: list[dict], max_tokens: int = 600) -> str:
        r = self.client.post(self.url, headers={"authorization": f"Bearer {self.license_key}"},
                             json={"model": self.model, "max_tokens": max_tokens,
                                   "temperature": 0.2, "messages": messages})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"]).strip()


def get_llm(cfg: Config, tier: str = "smart"):
    """Return an LLM for the given tier ("smart" | "fast")."""
    url, key = _proxy(cfg)
    if url and key:
        return RelayLLM(url, key, cfg["llm"]["models"][tier])
    from crewai import LLM

    return LLM(model=cfg["llm"]["models"][tier], temperature=0.2)
