"""LLM port, the Ollama client (JSON-schema constrained chat on the shared runner, embeddings) and
the schema flattening Ollama's grammar converter needs."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from bsa.config import LLMConfig


@dataclass
class LLMResult[T: BaseModel]:
    parsed: T | None
    raw: str
    stop_reason: str  # stop | length | error | invalid_json
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    prompt_eval_ms: int = 0
    error: str = ""
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


class LLMUnavailable(Exception):
    """The model server is down or the configured model is not pulled; raised before any work starts."""


class LLMPort(Protocol):
    model: str

    async def preflight(self) -> str | None: ...

    async def structured[T: BaseModel](
        self,
        *,
        node: str,
        messages: list[Message],
        schema: type[T],
        temperature: float,
        num_predict: int,
    ) -> LLMResult[T]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = str(node["$ref"]).split("/")[-1]
            return _inline(defs[name], defs)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("title", "$defs", "default", "description"):
                continue
            out[k] = _inline(v, defs)
        return out
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def ollama_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    schema = _inline(raw, raw.get("$defs", {}))
    _require_all(schema)
    return schema


def _require_all(node: Any) -> None:
    """Every property required, so the grammar never lets the model skip a field."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
        for v in node.values():
            _require_all(v)
    elif isinstance(node, list):
        for v in node:
            _require_all(v)


def schema_hint(model: type[BaseModel]) -> str:
    """Compact schema text appended to the task so the model sees field names and enums."""
    return json.dumps(ollama_schema(model), ensure_ascii=False, separators=(",", ":"))


log = structlog.get_logger()


class OllamaClient:
    def __init__(self, cfg: LLMConfig, record_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.model = cfg.model
        self._sem = asyncio.Semaphore(cfg.concurrency)
        self._record_dir = record_dir
        self._record_counts: dict[str, int] = {}

    async def preflight(self) -> str | None:
        """Return a readable problem when Ollama is unreachable or the model is not pulled, else None."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.cfg.base_url}/api/tags")
                resp.raise_for_status()
                names = {str(m.get("name")) for m in resp.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            return (
                f"Ollama is not reachable at {self.cfg.base_url} ({type(exc).__name__}). "
                "Install it from https://ollama.com and make sure it is running."
            )
        if self.model not in names and f"{self.model}:latest" not in names:
            return f"Model '{self.model}' is not available in Ollama. Run: ollama pull {self.model}"
        return None

    async def structured[T: BaseModel](
        self,
        *,
        node: str,
        messages: list[Message],
        schema: type[T],
        temperature: float,
        num_predict: int,
    ) -> LLMResult[T]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "think": False,
            "keep_alive": -1,  # same as DOC_QnA: never un-pin the shared runner
            "format": ollama_schema(schema),
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": self.cfg.num_ctx},
        }
        t0 = time.monotonic()
        async with self._sem:
            try:
                async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
                    resp = await client.post(f"{self.cfg.base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data: dict[str, Any] = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("llm_http_error", node=node, error=type(exc).__name__)
                return LLMResult(None, "", "error", error=f"{type(exc).__name__}: {exc}", model=self.model)
        latency = int((time.monotonic() - t0) * 1000)
        raw = str(data.get("message", {}).get("content", ""))
        result: LLMResult[T] = LLMResult(
            parsed=None,
            raw=raw,
            stop_reason=str(data.get("done_reason", "stop")),
            prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
            completion_tokens=int(data.get("eval_count", 0) or 0),
            latency_ms=latency,
            prompt_eval_ms=int((data.get("prompt_eval_duration", 0) or 0) / 1e6),
            model=self.model,
        )
        try:
            result.parsed = schema.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            result.stop_reason = "length" if result.stop_reason == "length" else "invalid_json"
            result.error = str(exc)[:500]
        log.info(
            "llm_call",
            node=node,
            model=self.model,
            latency_ms=latency,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            prompt_eval_ms=result.prompt_eval_ms,
            stop=result.stop_reason,
        )
        if self._record_dir is not None and result.parsed is not None:
            n = self._record_counts.get(node, 0)
            self._record_counts[node] = n + 1
            self._record_dir.mkdir(parents=True, exist_ok=True)
            (self._record_dir / f"{node}_{n}.json").write_text(raw, encoding="utf-8")
        return result

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
            resp = await client.post(
                f"{self.cfg.base_url}/api/embed",
                json={"model": self.cfg.embed_model, "input": texts, "keep_alive": self.cfg.embed_keep_alive},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]
