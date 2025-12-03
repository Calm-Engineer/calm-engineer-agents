# Calm Engineer Agents

## Agentic Business Research Agent (Real Estate Edition)

This agent analyzes a niche and produces a structured market research report.

### How to run

```bash
git clone https://github.com/Calm-Engineer/calm-engineer-agents.git
cd calm-engineer-agents

python -m venv .venv
.venv\Scripts\activate   # Windows

pip install -r requirements.txt

setx OPENAI_API_KEY "your_key_here"  # or use env vars

python -m src.agentic_business_research.cli "AI automations for real estate agents" --audience "real estate teams in Canada"
