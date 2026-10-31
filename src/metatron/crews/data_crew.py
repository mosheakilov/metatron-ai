"""Data Crew: Data Cleaner -> EDA Analyst -> Insights Writer -> Contract Author."""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task

from metatron.crews.tools import ReadArtifactTool, step_tool
from metatron.llm import get_llm
from metatron.pipeline import Run


def build_data_crew(run: Run) -> Crew:
    cfg = run.cfg
    smart, fast = get_llm(cfg, "smart"), get_llm(cfg, "fast")
    read = ReadArtifactTool(run=run)

    cleaner = Agent(
        role="Data Cleaner",
        goal="Turn the raw seller export into a clean, typed table without inventing data.",
        backstory="A careful data engineer at a real-estate brokerage. You only change data "
                  "through the cleaning tool and you report exactly what it changed.",
        tools=[step_tool(run, "clean", "clean_data",
                         "Run the deterministic cleaning pipeline (duplicates, text numbers, city "
                         "spelling, price typos, missing values). Returns the cleaning log.")],
        llm=fast, allow_delegation=False, verbose=False,
    )
    analyst = Agent(
        role="EDA Analyst",
        goal="Find which listing properties are associated with sellers agreeing to a meeting.",
        backstory="A statistician who reads distributions and correlations and never overstates "
                  "a weak signal.",
        tools=[step_tool(run, "eda", "run_eda",
                         "Compute statistics and charts on the clean data. Returns a summary.")],
        llm=fast, allow_delegation=False, verbose=False,
    )
    writer = Agent(
        role="Insights Writer",
        goal="Explain the findings to a solo real-estate broker in plain Hebrew.",
        backstory="A former broker turned analyst. You write short, practical insights and you "
                  "always state that the data is synthetic.",
        tools=[read], llm=smart, allow_delegation=False, verbose=False,
    )
    author = Agent(
        role="Contract Author",
        goal="Write the JSON data contract that every training input must satisfy.",
        backstory="A data-quality owner. Domain rules come first; a contract that only mirrors "
                  "the data proves nothing.",
        tools=[step_tool(run, "build_contract", "build_data_contract",
                         "Write data_contract.json from domain rules and the cleaned vocabulary."),
               read],
        llm=fast, allow_delegation=False, verbose=False,
    )

    t_clean = Task(
        description="Clean the uploaded seller file by calling clean_data exactly once. "
                    "Then summarize each cleaning step and how many rows it affected.",
        expected_output="A short list of cleaning steps with counts, rows in and rows out.",
        agent=cleaner,
    )
    t_eda = Task(
        description="Call run_eda once. Report the target rate, the 3 strongest positive and "
                    "negative signals, and anything surprising.",
        expected_output="A concise EDA summary with numbers.",
        agent=analyst, context=[t_clean],
    )
    t_insights = Task(
        description="Read eda/summary.json and cleaning_log.json with read_artifact. Write "
                    "insights for the broker in Hebrew Markdown: 5-7 bullet findings with "
                    "numbers, a section 'מה זה אומר למתווך', and a final note that the data is "
                    "synthetic.",
        expected_output="Hebrew Markdown document starting with '# תובנות מהנתונים'.",
        agent=writer, context=[t_clean, t_eda], output_file=str(run.p("insights.md")),
    )
    t_contract = Task(
        description="Call build_data_contract once, then read data_contract.json and confirm "
                    "it covers every column, the target, the primary key, min rows and the "
                    "target-rate range. Report any rule you think is missing.",
        expected_output="Confirmation that data_contract.json was written, with a short review.",
        agent=author, context=[t_clean, t_eda],
    )
    return Crew(agents=[cleaner, analyst, writer, author],
                tasks=[t_clean, t_eda, t_insights, t_contract],
                process=Process.sequential, verbose=False)
