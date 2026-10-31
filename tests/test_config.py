from metatron.config import ROOT, load_config
from metatron.llm import use_llm


def test_config_loads():
    cfg = load_config()
    assert cfg.seed == 42
    assert cfg.data.target == "agreed_to_meeting"
    assert cfg.path("runs") == ROOT / "runs"


def test_offline_mode_never_uses_llm(monkeypatch):
    monkeypatch.setenv("METATRON_LLM_MODE", "offline")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert use_llm(load_config()) is False
