# workflow.py
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

import requests

from .config import Settings, get_client
from .prompts import BASE_SYSTEM_PROMPT, build_user_prompt


PERPLEXITY_SEARCH_URL = "https://api.perplexity.ai/search"


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
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["url", "title"],
                },
            },
        },
        "required": [
            "niche",
            "audience_summary",
            "top_problems",
            "market_signals",
            "offer_ideas",
            "execution_notes",
            "sources",
        ],
    },
}


def perplexity_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Call Perplexity's Search API and return the raw result dicts
    (each with at least "title" and "url").
    Expects PERPLEXITY_API_KEY in the environment.
    """
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not set. Get a key at "
            "https://www.perplexity.ai/settings/api and export it."
        )

    response = requests.post(
        PERPLEXITY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"query": query, "max_results": max_results},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results", [])


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

    search_query = f"{niche} {audience}" if audience else niche
    try:
        raw_results = perplexity_search(search_query, max_results=5)
    except (RuntimeError, requests.RequestException) as exc:
        print(
            f"Warning: Perplexity search unavailable ({exc}); "
            "continuing without web grounding.",
            file=sys.stderr,
        )
        raw_results = []

    sources = [
        {"url": r["url"], "title": r.get("title", "")}
        for r in raw_results[:5]
        if r.get("url")
    ]

    user_prompt = build_user_prompt(
        niche=niche,
        audience=audience,
        geography=geography,
        constraints=constraints,
        sources=raw_results[:5],
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
    result = json.loads(content)
    # Overwrite whatever the model produced for "sources" with the actual
    # search results used, so this field can never contain invented links.
    result["sources"] = sources
    return result
