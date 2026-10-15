"""Offline smoke test: no API key, no network."""

from agentic_business_research.prompts import build_user_prompt


def test_build_user_prompt_without_sources(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    prompt = build_user_prompt("AI for dentists")
    assert "AI for dentists" in prompt
    assert "No web search results were available" in prompt


def test_build_user_prompt_with_sources():
    sources = [{"title": "Example", "url": "https://example.com", "snippet": "A snippet"}]
    prompt = build_user_prompt("AI for dentists", audience="clinics", sources=sources)
    assert "Target audience: clinics" in prompt
    assert "https://example.com" in prompt
    assert "A snippet" in prompt
