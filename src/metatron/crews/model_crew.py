"""Model Crew: Feature Engineer -> Model Trainer -> Evaluator -> Model Card Writer."""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from metatron.crews.tools import ReadArtifactTool, step_tool
from metatron.llm import get_llm
from metatron.pipeline import Run


def build_model_crew(run: Run) -> Crew:
    cfg = run.cfg
    smart, fast = get_llm(cfg, "smart"), get_llm(cfg, "fast")
    read = ReadArtifactTool(run=run)

    engineer = Agent(
        role="Feature Engineer",
        goal="Prepare model features and a reproducible stratified train/test split.",
        backstory="An ML engineer who prevents leakage: anything learned from data is learned "
                  "on the training split only.",
        tools=[step_tool(run, "build_features", "build_features",
                         "Build features (incl. ask_ratio vs. city median) and the seeded split.")],
        llm=fast, allow_delegation=False, verbose=False,
    )
    trainer = Agent(
        role="Model Trainer",
        goal="Train every model version defined in config.yaml with the fixed training code.",
        backstory="You never write training code. You run the approved training tool and report "
                  "what was trained.",
        tools=[step_tool(run, "train", "train_models",
                         "Train v1 (logistic regression) and v2 (gradient boosting).")],
        llm=fast, allow_delegation=False, verbose=False,
    )
    evaluator = Agent(
        role="Evaluator",
        goal="Compare the versions on held-out data and pick the one the broker should use.",
        backstory="A skeptical reviewer. You care about Precision@20% because the broker only "
                  "contacts the top of the list, and you prefer the simpler model on a tie.",
        tools=[step_tool(run, "evaluate", "evaluate_models",
                         "Compute ROC-AUC, PR-AUC, Precision@top, Brier, CV and calibration; "
                         "writes metrics.json and selects a version."), read],
        llm=smart, allow_delegation=False, verbose=False,
    )
    card_writer = Agent(
        role="Model Card Writer",
        goal="Document the model honestly: data, metrics, limitations and fair use.",
        backstory="A responsible-AI writer. You always state that the training data is "
                  "synthetic and how real labels will replace it.",
        tools=[read], llm=smart, allow_delegation=False, verbose=False,
    )

    t_feat = Task(description="Call build_features once and report the split sizes and features.",
                  expected_output="Split sizes and feature list.", agent=engineer)
    t_train = Task(description="Call train_models once and report which versions were trained.",
                   expected_output="List of trained versions.", agent=trainer, context=[t_feat])
    t_eval = Task(
        description="Call evaluate_models once. Compare v1 and v2 on every metric, explain the "
                    "selected version in 3-4 sentences, and flag overfitting if CV and test "
                    "disagree.",
        expected_output="A comparison table and the selected version with reasoning.",
        agent=evaluator, context=[t_train],
    )
    t_card = Task(
        description="Read metrics.json, run.json and data_contract.json. Write a Model Card in "
                    "English Markdown with sections: What it predicts, Data (state SYNTHETIC), "
                    "Versions (table), Limitations, Fair use, Path to real data, Reproduce "
                    "(`python -m metatron.train --config config.yaml`).",
        expected_output="Markdown starting with '# Model Card: Seller Lead Scoring'.",
        agent=card_writer, context=[t_eval], output_file=str(run.p("MODEL_CARD.md")),
    )
    return Crew(agents=[engineer, trainer, evaluator, card_writer],
                tasks=[t_feat, t_train, t_eval, t_card],
                process=Process.sequential, verbose=False)
