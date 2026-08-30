# Calm Engineer Agents

This repo contains AI agents built by Rodney ("Calm Engineer") for business research and automation.

## Agent 1: Agentic Business Research Agent

This agent takes a niche or audience and returns a structured **Business Research Summary**. It first runs a live web search via the Perplexity Search API to ground the analysis in real sources, then passes those results to the OpenAI API for analysis — the report includes the actual sources used.

### 1. Setup

Clone the repo and enter the folder:

```bash
git clone https://github.com/Calm-Engineer/calm-engineer-agents.git
cd calm-engineer-agents
```

Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

Set your OpenAI and Perplexity API keys:

```bash
export OPENAI_API_KEY=sk-...            # macOS/Linux
export PERPLEXITY_API_KEY=pplx-...      # macOS/Linux
setx OPENAI_API_KEY "sk-..."            # Windows (new terminal sessions only)
setx PERPLEXITY_API_KEY "pplx-..."      # Windows (new terminal sessions only)
```

`PERPLEXITY_API_KEY` is optional but strongly recommended — it powers the web
search grounding step. If it's missing or the search call fails, the agent
falls back to an ungrounded analysis (no citations, `sources` will be empty)
rather than failing outright. Get a key at
[perplexity.ai/settings/api](https://www.perplexity.ai/settings/api).

Optional environment variables:

- `OPENAI_MODEL` — model to use (default: `gpt-4.1-mini`)
- `MAX_OUTPUT_TOKENS` — max tokens for the response (default: `2000`)

### 2. Run

```bash
python -m src.agentic_business_research.cli "AI for dentists" --audience "solo dentists in North America"
```

Optional flags:

- `--geo` — primary geography, e.g. `"US"`, `"Canada"`, `"Global"`
- `--constraints` — budget/time/skills constraints
- `--out` — path to save the full JSON report, e.g. `--out reports/dentists.json`

See [`docs/examples.md`](docs/examples.md) for more example commands. Generated JSON reports are written to `reports/` and are git-ignored.
