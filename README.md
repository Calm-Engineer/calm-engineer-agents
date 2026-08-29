# Calm Engineer Agents

This repo contains AI agents built by Rodney ("Calm Engineer") for business research and automation.

## Agent 1: Agentic Business Research Agent

This agent takes a niche or audience and returns a structured **Business Research Summary** using the OpenAI API.

### 1. Setup

Clone the repo and enter the folder:

```bash
git clone https://github.com/Calm-Engineer/calm-engineer-agents.git
cd calm-engineer-agents
```

Install dependencies (a virtual environment is recommended):

```bash
pip install -r requirements.txt
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-...        # macOS/Linux
setx OPENAI_API_KEY "sk-..."        # Windows (new terminal sessions only)
```

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
