"""Shared agent infrastructure: model factory, LLM semaphore, run wrapper with events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from mito_harness.logging_events import EventBus
from setting import Settings, get_settings

logger = logging.getLogger(__name__)


def build_model(settings: Settings | None = None) -> Model:
    """OpenAI-compatible model pointed at the configured endpoint (local vLLM default)."""
    s = settings or get_settings()
    provider = OpenAIProvider(base_url=s.model.base_url, api_key=s.api_key)
    return OpenAIChatModel(s.model.name, provider=provider)


class LlmGate:
    """Global semaphore limiting concurrent agent runs against a single local GPU."""

    def __init__(self, concurrency: int) -> None:
        self._sem = asyncio.Semaphore(concurrency)

    async def run(self, coro: Any) -> Any:
        async with self._sem:
            return await coro


_gate: LlmGate | None = None


def llm_gate() -> LlmGate:
    global _gate
    if _gate is None:
        _gate = LlmGate(get_settings().limits.llm_concurrency)
    return _gate


async def run_agent_logged(
    agent: Agent[Any, Any],
    prompt: str,
    *,
    bus: EventBus,
    agent_name: str,
    step_id: str,
    correlation_id: str,
    usage_limit: Any | None = None,
) -> Any:
    """Run one agent call under the LLM gate, emitting delegation events."""
    bus.emit("task_delegated", agent=agent_name, step_id=step_id, correlation_id=correlation_id)
    try:
        result = await llm_gate().run(agent.run(prompt, usage_limits=usage_limit))
    except Exception as exc:
        bus.emit(
            "task_failed",
            agent=agent_name,
            step_id=step_id,
            correlation_id=correlation_id,
            payload={"error": str(exc)[:300]},
        )
        raise
    usage = getattr(result, "usage", None)
    bus.emit(
        "task_completed",
        agent=agent_name,
        step_id=step_id,
        correlation_id=correlation_id,
        duration_ms=None,
        payload={"requests": getattr(usage, "requests", None), "tokens": getattr(usage, "total_tokens", None)},
    )
    return result.output
