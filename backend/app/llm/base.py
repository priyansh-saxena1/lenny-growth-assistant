from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderUnavailable(RuntimeError):
    """Raised when the provider can't be reached or isn't configured.

    Separate from a model error on purpose: the orchestrator falls back on this
    but surfaces a model error to the user, because retrying a bad prompt on a
    different model usually produces a second bad answer more slowly.
    """


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None


@dataclass
class ProviderHealth:
    name: str
    ok: bool
    model: str
    detail: str = ""
    latency_ms: int | None = None


class LLMProvider(Protocol):
    name: str
    model: str
    supports_tools: bool

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        tools: list[dict] | None = None,
    ) -> LLMResult: ...

    async def health(self) -> ProviderHealth: ...


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)
