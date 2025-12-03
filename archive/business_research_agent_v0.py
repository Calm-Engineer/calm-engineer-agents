from typing import TypedDict, List

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END


# 1. Define the state
class BizResearchState(TypedDict, total=False):
    niche: str
    plan: List[str]
    raw_findings: List[str]
    final_report: str


# 2. Planner node - design research steps
def biz_planner_node(state: BizResearchState) -> BizResearchState:
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    prompt = f"""
    You are a research planner for AI & automation consulting.

    Given this target niche or business type:
    "{state['niche']}"

    Break the research into exactly 3-4 clear steps.
    Focus on:
    1) Market overview
    2) Pain points and bottlenecks
    3) Current tools and processes
    4) Opportunities for AI / automation or data workflows

    Return ONLY a numbered list of steps.
    """

    steps_text = model.invoke(prompt).content
    steps = [s.strip() for s in steps_text.split("\n") if s.strip()]

    return {"plan": steps}


# 3. Researcher node - execute steps
def biz_researcher_node(state: BizResearchState) -> BizResearchState:
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    findings: List[str] = []

    for step in state["plan"]:
        prompt = f"""
        You are a research agent helping an AI/automation consultant.

        Execute this research step for the niche:
        "{state['niche']}"

        Step: {step}

        Give a concise but detailed answer (10-15 bullet points max),
        focusing on specific pains, workflows, and tool usage.
        """

        answer = model.invoke(prompt).content
        findings.append(f"STEP: {step}\n\n{answer}\n")

    return {"raw_findings": findings}


# 4. Summarizer node - convert to actionable report
def biz_summary_node(state: BizResearchState) -> BizResearchState:
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    raw_text = "\n\n".join(state["raw_findings"])

    prompt = f"""
    You are an AI & automation consultant.

    Using the research below, create a structured, actionable report.

    Niche: {state['niche']}

    Research:
    {raw_text}

    The report MUST be in this structure:

    1. Market Overview
    - 3-5 bullets

    2. Top 5 Pain Points / Bottlenecks
    - Bullet list

    3. Current Tools & Processes
    - Bullet list (what they use now, how they operate)

    4. Opportunities for AI / Automation
    - 5-7 concrete opportunities
    - Focus on what can be automated or improved with LLMs, agents, or data workflows

    5. 3 Service Ideas Rodney Could Offer
    - Describe 3 specific services (what, how, outcome)
    """

    summary = model.invoke(prompt).content
    return {"final_report": summary}


# 5. Build the graph
builder = StateGraph(BizResearchState)

builder.add_node("planner", biz_planner_node)
builder.add_node("researcher", biz_researcher_node)
builder.add_node("summary", biz_summary_node)

builder.add_edge(START, "planner")
builder.add_edge("planner", "researcher")
builder.add_edge("researcher", "summary")
builder.add_edge("summary", END)

app = builder.compile()


# 6. CLI entrypoint
if __name__ == "__main__":
    niche_input = input(
        "Enter a niche or business type (e.g. 'local real estate agent in Toronto'): "
    ).strip()

    if not niche_input:
        print("Please enter a valid niche.")
        raise SystemExit(1)

    initial_state: BizResearchState = {"niche": niche_input}

    result = app.invoke(initial_state)

    print("\n===== BUSINESS RESEARCH REPORT =====\n")
    print(result["final_report"])

