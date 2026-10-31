"""TrainingFlow: ingest -> Data Crew -> contract gate -> Model Crew -> model + card.

    ingest_file ──► data_crew ──► validate_contract ──┬─ "failed" ──► stop (validation_report.json)
                                                      └─ "valid"  ──► model_crew ──► publish
"""

from __future__ import annotations

from pathlib import Path

from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from metatron import reports
from metatron.config import Config, load_config
from metatron.llm import use_llm
from metatron.pipeline import Run


class TrainingState(BaseModel):
    input_path: str = ""
    run_id: str | None = None
    run_dir: str = ""
    mode: str = ""                    # "crew" | "offline"
    status: str = "pending"           # pending | stopped | trained | failed
    errors: list[dict] = []
    data_error: str | None = None     # exception raised inside the Data Crew step
    selected: str | None = None
    metrics: dict = {}


class TrainingFlow(Flow[TrainingState]):
    cfg: Config = Field(default_factory=load_config, exclude=True)

    def _run(self) -> Run:
        return Run(self.cfg, Path(self.state.run_dir))

    @start()
    def ingest_file(self):
        run = Run.create(self.cfg, Path(self.state.input_path), self.state.run_id)
        self.state.run_dir = str(run.dir)
        self.state.mode = "crew" if use_llm(self.cfg) else "offline"

    @listen(ingest_file)
    def data_crew(self):
        run = self._run()
        try:
            if self.state.mode == "crew":
                from metatron.crews.data_crew import build_data_crew
                build_data_crew(run).kickoff()
            else:
                log = run.clean()
                summary = run.eda()
                run.p("insights.md").write_text(reports.insights_md(summary, log),
                                                encoding="utf-8")
                run.build_contract()
        except Exception as e:  # the gate turns this into a clear stop, not a crash
            self.state.data_error = f"{type(e).__name__}: {e}"

    @router(data_crew)
    def validate_contract(self):
        report = self._run().validate(self.state.data_error)
        if not report["valid"]:
            self.state.errors = report["errors"]
            return "failed"
        return "valid"

    @listen("failed")
    def stop(self):
        self.state.status = "stopped"
        self._run().finish("stopped", reason="data contract validation failed",
                           n_failed=len(self.state.errors))

    @listen("valid")
    def model_crew(self):
        run = self._run()
        if self.state.mode == "crew":
            from metatron.crews.model_crew import build_model_crew
            build_model_crew(run).kickoff()
        else:
            run.build_features()
            run.train()
            metrics = run.evaluate()
            card = reports.model_card_md(metrics, run.read_json("run.json"),
                                         run.read_json("data_contract.json"))
            run.p("MODEL_CARD.md").write_text(card, encoding="utf-8")

    @listen(model_crew)
    def publish(self):
        run = self._run()
        if not run.p("metrics.json").exists():
            self.state.status = "failed"
            self.state.errors = [{"check": "metrics_present", "ok": False,
                                  "detail": "Model Crew did not produce metrics.json",
                                  "fix": "re-run training"}]
            run.finish("failed", reason="metrics.json missing")
            return
        metrics = run.read_json("metrics.json")
        self.state.selected = metrics["selected"]
        self.state.metrics = {v: {k: m[k] for k in ("roc_auc", "pr_auc", "lift_at_top")}
                              for v, m in metrics["versions"].items()}
        self.state.status = "trained"
        run.finish("trained", selected=metrics["selected"])
        latest = self.cfg.path(self.cfg.runs_dir) / "LATEST"
        latest.write_text(run.dir.name, encoding="utf-8")


def run_training(input_path: str | Path, cfg: Config | None = None,
                 run_id: str | None = None) -> TrainingState:
    flow = TrainingFlow(cfg=cfg or load_config(), suppress_flow_events=True)
    flow.kickoff(inputs={"input_path": str(input_path), "run_id": run_id})
    return flow.state
