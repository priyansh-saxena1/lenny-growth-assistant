from __future__ import annotations

from ..config import get_settings
from ..logging_setup import get_logger
from .base import LLMProvider, ProviderUnavailable
from .cloud import AnthropicProvider, OpenAIProvider
from .echo import EchoProvider
from .ollama import OllamaProvider

log = get_logger(__name__)

BUILDERS = {
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "echo": EchoProvider,
}

_override: LLMProvider | None = None


def set_override(p: LLMProvider | None) -> None:
    """Used by tests and by the per-request `provider` field on /api/chat."""
    global _override
    _override = p


def build(name: str) -> LLMProvider:
    if name not in BUILDERS:
        raise ValueError(f"unknown provider '{name}' (have: {', '.join(BUILDERS)})")
    return BUILDERS[name]()


def get_provider(name: str | None = None) -> LLMProvider:
    if _override is not None:
        return _override
    return build(name or get_settings().llm_provider)


def get_fallback() -> LLMProvider | None:
    fb = get_settings().fallback_provider
    if fb in ("none", get_settings().llm_provider):
        return None
    try:
        return build(fb)
    except Exception as exc:
        log.warning("fallback.unbuildable", provider=fb, error=str(exc))
        return None


async def health_all() -> list[dict]:
    out = []
    for name in BUILDERS:
        try:
            h = await build(name).health()
            out.append({"provider": h.name, "ok": h.ok, "model": h.model,
                        "detail": h.detail, "latency_ms": h.latency_ms})
        except Exception as exc:
            out.append({"provider": name, "ok": False, "model": "?", "detail": str(exc)})
    return out


__all__ = ["get_provider", "get_fallback", "health_all", "set_override", "build",
           "ProviderUnavailable"]
