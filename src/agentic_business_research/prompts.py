# prompts.py
from typing import Any, Dict, List, Optional

BASE_SYSTEM_PROMPT = """
You are the Calm Engineer Business Research Agent.

Your job:
- Take a niche or business idea.
- Analyze the target audience, their pain points, and demand signals.
- Identify at least 5–10 concrete problems worth solving.
- Suggest possible offers / services / products that a solo operator could deliver within 1–2 weeks.
- Focus on practical, low-bullshit insights that can be acted on immediately.

You will be given a set of live web search results as grounding context.
Ground your analysis in those results where they're relevant — cite specific
facts, current solutions, or signals they contain instead of relying purely
on prior knowledge. Do not invent sources: leave the "sources" field in your
JSON output as an empty array, it is filled in separately from the actual
search results.

Be concise, evidence-oriented, and structured.
"""


def build_user_prompt(
    niche: str,
    audience: str | None = None,
    geography: str | None = None,
    constraints: str | None = None,
    sources: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build the user-facing part of the prompt."""
    lines = [f"Niche or business idea: {niche}"]
    if audience:
        lines.append(f"Target audience: {audience}")
    if geography:
        lines.append(f"Primary geography: {geography}")
    if constraints:
        lines.append(f"Constraints: {constraints}")

    if sources:
        lines.append("\nWeb search results (grounding context — use these):")
        for i, s in enumerate(sources, start=1):
            title = (s.get("title") or "").strip()
            url = (s.get("url") or "").strip()
            snippet = (s.get("snippet") or "").strip()
            lines.append(f"{i}. {title} — {url}")
            if snippet:
                lines.append(f"   {snippet}")
    else:
        lines.append(
            "\nNo web search results were available for this query. "
            "Rely on general knowledge and say so in execution_notes."
        )

    lines.append(
        "\nReturn a structured analysis following the JSON schema I provided."
    )
    return "\n".join(lines)

