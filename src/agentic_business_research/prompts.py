# prompts.py

BASE_SYSTEM_PROMPT = """
You are the Calm Engineer Business Research Agent.

Your job:
- Take a niche or business idea.
- Analyze the target audience, their pain points, and demand signals.
- Identify at least 5–10 concrete problems worth solving.
- Suggest possible offers / services / products that a solo operator could deliver within 1–2 weeks.
- Focus on practical, low-bullshit insights that can be acted on immediately.

Be concise, evidence-oriented, and structured.
"""


def build_user_prompt(
    niche: str,
    audience: str | None = None,
    geography: str | None = None,
    constraints: str | None = None,
) -> str:
    """Build the user-facing part of the prompt."""
    lines = [f"Niche or business idea: {niche}"]
    if audience:
        lines.append(f"Target audience: {audience}")
    if geography:
        lines.append(f"Primary geography: {geography}")
    if constraints:
        lines.append(f"Constraints: {constraints}")
    lines.append(
        "\nReturn a structured analysis following the JSON schema I provided."
    )
    return "\n".join(lines)

