# workflow.py
from __future__ import annotations

import json
from typing import Any, Dict

from .config import Settings, get_client
from .prompts import BASE_SYSTEM_PROMPT, build_user_prompt


BUSINESS_RESEARCH_SCHEMA: Dict[str, Any] = {
    "name": "business_research_report",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "niche": {"type": "string"},
            "audience_summary": {"type": "string"},
            "top_problems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "problem": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "current_solutions": {"type": "string"},
                    },
                    "required": [
                        "problem",
                        "why_it_matters",
                        "current_solutions",
                    ],
                },
            },
            "market_signals": {
                "type": "array",
                "items": {"type": "string"},
            },
            "offer_ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "offer_name": {"type": "string"},
                        "offer_type": {"type": "string"},
                        "deliverables": {"type": "string"},
                        "who_it_helps": {"type": "string"},
                        "difficulty": {"type": "string"},
                        "time_to_build_days": {"type": "integer"},
                    },
                    "required": [
                        "offer_name",
                        "offer_type",
                        "deliverables",
                        "who_it_helps",
                        "difficulty",
                        "time_to_build_days",
                    ],
                },
            },
            "execution_notes": {"type": "string"},
        },
        "required": [
            "niche",
            "audience_summary",
            "top_problems",
            "market_signals",
            "offer_ideas",
            "execution_notes",
        ],
    },
}


def run_business_research(
    niche: str,
    audience: str | None = None,
    geography: str | None = None,
    constraints: str | None = None,
) -> Dict[str, Any]:
    """
    Run the business research agent and return a Python dict
    matching BUSINESS_RESEARCH_SCHEMA.
    """
    settings = Settings()
    client = get_client()

    user_prompt = build_user_prompt(
        niche=niche,
        audience=audience,
        geography=geography,
        constraints=constraints,
    )

    response = client.chat.completions.create(
        model=settings.model,
        response_format={
            "type": "json_schema",
            "json_schema": BUSINESS_RESEARCH_SCHEMA,
        },
        messages=[
            {"role": "system", "content": BASE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=settings.max_output_tokens,
        temperature=0.3,
    )

    content = response.choices[0].message.content
    return json.loads(content)
