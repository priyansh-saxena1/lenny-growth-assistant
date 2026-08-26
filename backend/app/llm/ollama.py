from __future__ import annotations

import json
import time

import httpx

from ..config import get_settings
from ..logging_setup import get_logger
from .base import LLMResult, ProviderHealth, ProviderUnavailable, ToolCall, approx_tokens

log = get_logger(__name__)


class OllamaProvider:
    name = "ollama"
    supports_tools = True  # qwen2.5 / llama3.1 expose the tools field

    def __init__(self, host: str | None = None, model: str | None = None):
        s = get_settings()
        self.host = (host or s.ollama_host).rstrip("/")
        self.model = model or s.ollama_model
        self.timeout = s.ollama_timeout_s

    async def complete(self, messages, system=None, max_tokens=2048, temperature=0.2, tools=None):
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.host}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"ollama unreachable at {self.host}: {exc}") from exc

        if r.status_code == 404:
            # Distinctive enough to be worth its own message — this is the
            # "you forgot to `ollama pull`" case and it burns a lot of setup time.
            raise ProviderUnavailable(
                f"model '{self.model}' not pulled. Run: ollama pull {self.model}"
            )
        if r.status_code >= 400:
            raise ProviderUnavailable(f"ollama {r.status_code}: {r.text[:200]}")

        data = r.json()
        msg = data.get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=fn.get("name", "call"), name=fn.get("name", ""), arguments=args or {}))

        return LLMResult(
            text=msg.get("content", "") or "",
            model=self.model,
            provider=self.name,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            tool_calls=calls,
            stop_reason="tool_use" if calls else data.get("done_reason"),
        )

    async def health(self):
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.host}/api/tags")
                r.raise_for_status()
                names = {m["name"] for m in r.json().get("models", [])}
        except Exception as exc:
            return ProviderHealth(self.name, False, self.model, f"unreachable: {exc}")

        latency = int((time.perf_counter() - t0) * 1000)
        # Ollama reports "qwen2.5:7b-instruct"; users often configure "qwen2.5".
        pulled = self.model in names or any(n.split(":")[0] == self.model for n in names)
        if not pulled:
            return ProviderHealth(
                self.name, False, self.model,
                f"model not pulled (have: {', '.join(sorted(names)) or 'none'})", latency,
            )
        return ProviderHealth(self.name, True, self.model, "ready", latency)
