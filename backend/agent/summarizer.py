"""
summarizer.py
--------------
Final step of the agent loop: takes the original query plus all
collected tool outputs and asks Qwen 2.5 Instruct (via Ollama) to
produce a friendly, accurate, non-hallucinated explanation.
"""

from __future__ import annotations

import json
import logging

from backend.ai.ollama_client import OllamaError, ollama_client
from backend.ai.prompts import SUMMARIZER_SYSTEM_PROMPT

logger = logging.getLogger("linuxpilot.agent.summarizer")


async def summarize(query: str, step_results: list[dict]) -> str:
    """
    step_results: list of {"step", "tool", "description", "output"} dicts
    collected by the orchestrator during plan execution.
    """
    context_blob = json.dumps(step_results, indent=2, default=str)
    prompt = (
        f"User question: {query}\n\n"
        f"Tool results collected so far (JSON):\n{context_blob}\n\n"
        f"Write the final answer for the user now."
    )
    try:
        return await ollama_client.generate(prompt=prompt, system=SUMMARIZER_SYSTEM_PROMPT, temperature=0.3)
    except OllamaError as exc:
        logger.warning("Summarization LLM call failed, returning raw-data fallback: %s", exc)
        return (
            "I gathered the diagnostic data below, but couldn't reach the summarization "
            f"model to explain it in plain language ({exc}). Raw results:\n{context_blob}"
        )
