"""Anthropic and OpenAI over plain HTTP.

No vendor SDKs here on purpose — two providers, one code path, and the Messages
/ Chat Completions shapes are stable enough that the SDK buys us little beyond
another dependency to pin. The Claude Agent SDK is a different question and is
handled in agent/sdk_runner.py.
"""

from __future__ import annotations

import json
import time

import httpx

from ..config import get_settings
from .base import LLMResult, ProviderHealth, ProviderUnavailable, ToolCall


class AnthropicProvider:
    name = "anthropic"
    supports_tools = True

    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.anthropic_api_key
        self.model = model or s.anthropic_model

    async def complete(self, messages, system=None, max_tokens=2048, temperature=0.2, tools=None):
        if not self.api_key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t["function"]["name"],
                 "description": t["function"]["description"],
                 "input_schema": t["function"]["parameters"]}
                for t in tools
            ]

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key,
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"anthropic unreachable: {exc}") from exc
        if r.status_code == 401:
            raise ProviderUnavailable("anthropic rejected the API key (401)")
        if r.status_code == 429:
            raise ProviderUnavailable("anthropic rate limit (429)")
        if r.status_code >= 400:
            raise ProviderUnavailable(f"anthropic {r.status_code}: {r.text[:200]}")

        data = r.json()
        text, calls = "", []
        for block in data.get("content", []):
            if block["type"] == "text":
                text += block["text"]
            elif block["type"] == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block.get("input", {})))
        u = data.get("usage", {})
        return LLMResult(text, self.model, self.name,
                         int((time.perf_counter() - t0) * 1000),
                         u.get("input_tokens"), u.get("output_tokens"),
                         calls, data.get("stop_reason"))

    async def health(self):
        if not self.api_key:
            return ProviderHealth(self.name, False, self.model, "no API key configured")
        return ProviderHealth(self.name, True, self.model, "key present (not verified)")


class OpenAIProvider:
    name = "openai"
    supports_tools = True

    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.openai_api_key
        self.model = model or s.openai_model
        self.base_url = s.openai_base_url.rstrip("/")

    async def complete(self, messages, system=None, max_tokens=2048, temperature=0.2, tools=None):
        if not self.api_key:
            raise ProviderUnavailable("OPENAI_API_KEY is not set")
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
        }
        if tools:
            body["tools"] = tools

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(f"{self.base_url}/chat/completions",
                                 headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"openai unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise ProviderUnavailable(f"openai {r.status_code}: {r.text[:200]}")

        data = r.json()
        ch = data["choices"][0]["message"]
        calls = [
            ToolCall(tc["id"], tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
            for tc in ch.get("tool_calls") or []
        ]
        u = data.get("usage", {})
        return LLMResult(ch.get("content") or "", self.model, self.name,
                         int((time.perf_counter() - t0) * 1000),
                         u.get("prompt_tokens"), u.get("completion_tokens"),
                         calls, data["choices"][0].get("finish_reason"))

    async def health(self):
        if not self.api_key:
            return ProviderHealth(self.name, False, self.model, "no API key configured")
        return ProviderHealth(self.name, True, self.model, "key present (not verified)")
