"""Crews are built with real CrewAI objects; tools run without any LLM call."""

import json

import pytest

from metatron.config import load_config
from metatron.crews.data_crew import build_data_crew
from metatron.crews.model_crew import build_model_crew
from metatron.data.generate import generate
from metatron.pipeline import Run


@pytest.fixture()
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    cfg = load_config()
    cfg["runs_dir"] = str(tmp_path / "runs")
    src = tmp_path / "s.csv"
    generate(800, seed=2).to_csv(src, index=False, encoding="utf-8-sig")
    return Run.create(cfg, src, "crew")


def test_two_crews_with_four_agents_each(run):
    data, model = build_data_crew(run), build_model_crew(run)
    assert [a.role for a in data.agents] == ["Data Cleaner", "EDA Analyst", "Insights Writer",
                                             "Contract Author"]
    assert [a.role for a in model.agents] == ["Feature Engineer", "Model Trainer", "Evaluator",
                                              "Model Card Writer"]
    assert len(data.tasks) == len(model.tasks) == 4


def test_tools_do_the_work_deterministically(run):
    data = build_data_crew(run)
    tools = {t.name: t for a in data.agents for t in a.tools}
    log = json.loads(tools["clean_data"].run())
    assert log["rows_out"] < log["rows_in"]
    tools["build_data_contract"].run()
    assert (run.dir / "data_contract.json").exists()
    assert "primary_key" in tools["read_artifact"].run(artifact="data_contract.json")


def test_read_artifact_cannot_escape_run_dir(run):
    read = next(t for a in build_data_crew(run).agents for t in a.tools if t.name == "read_artifact")
    assert read.run(artifact="../../config.yaml").startswith("artifact not found")
    assert read.run(artifact="input.csv").startswith("only .json and .md")
