"""CrewAI tools. Each wraps one deterministic pipeline step bound to the current run directory.

Agents decide when to call a tool and interpret its JSON result; the tool does the data work.
"""

from __future__ import annotations

import json
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from metatron.pipeline import Run

MAX_CHARS = 6000  # keep tool results inside the agent's context budget


def _short(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + " …(truncated)"


class _NoArgs(BaseModel):
    pass


class RunTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    args_schema: type[BaseModel] = _NoArgs
    workspace: Run = Field(exclude=True)
    step: str = Field(exclude=True)

    def _run(self, **_: Any) -> str:
        return _short(getattr(self.workspace, self.step)())


def step_tool(run: Run, step: str, name: str, description: str) -> RunTool:
    return RunTool(workspace=run, step=step, name=name, description=description)


class _ReadArgs(BaseModel):
    artifact: str = Field(description="file name inside the run directory, e.g. eda/summary.json")


class ReadArtifactTool(BaseTool):
    """Read a JSON/Markdown artifact from the run directory (read-only, no path escape)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str = "read_artifact"
    description: str = ("Read an artifact produced earlier in this run, e.g. cleaning_log.json, "
                        "eda/summary.json, data_contract.json, validation_report.json, "
                        "metrics.json, run.json.")
    args_schema: type[BaseModel] = _ReadArgs
    workspace: Run = Field(exclude=True)

    def _run(self, artifact: str) -> str:
        path = (self.workspace.dir / artifact).resolve()
        if self.workspace.dir.resolve() not in path.parents or not path.is_file():
            return f"artifact not found: {artifact}"
        if path.suffix not in {".json", ".md"}:
            return "only .json and .md artifacts can be read"
        text = path.read_text(encoding="utf-8")
        return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + " …(truncated)"
