# config.py
from dataclasses import dataclass
import os
from openai import OpenAI


@dataclass
class Settings:
    """Configuration for the business research agent."""
    model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    max_output_tokens: int = int(os.getenv("MAX_OUTPUT_TOKENS", "2000"))


def get_client() -> OpenAI:
    """
    Returns an OpenAI client.
    Expects OPENAI_API_KEY in the environment.
    """
    return OpenAI()  # SDK reads OPENAI_API_KEY automatically

