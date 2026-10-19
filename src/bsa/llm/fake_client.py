"""Replays recorded LLM outputs from tests/fixtures/llm/<case>/<node>_<n>.json (no network)."""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bsa.llm.client import LLMResult, Message


class FakeLLM:
    model = "fake"

    def __init__(self, fixture_dir: Path | None = None, outputs: dict[str, list[str]] | None = None) -> None:
        self.outputs: dict[str, list[str]] = outputs or {}
        if fixture_dir is not None:
            for f in sorted(fixture_dir.glob("*.json"), key=lambda p: (p.stem.rsplit("_", 1)[0], _n(p))):
                self.outputs.setdefault(f.stem.rsplit("_", 1)[0], []).append(f.read_text(encoding="utf-8"))
        self.calls: list[tuple[str, list[Message]]] = []
        self._idx: dict[str, int] = {}

    async def structured[T: BaseModel](
        self, *, node: str, messages: list[Message], schema: type[T], temperature: float, num_predict: int
    ) -> LLMResult[T]:
        self.calls.append((node, messages))
        items = self.outputs.get(node)
        if not items:
            return LLMResult(None, "", "error", error=f"no fixture for {node}", model=self.model)
        i = self._idx.get(node, 0)
        self._idx[node] = i + 1
        raw = items[i % len(items)]
        try:
            return LLMResult(schema.model_validate(json.loads(raw)), raw, "stop", model=self.model)
        except (json.JSONDecodeError, ValidationError) as exc:
            return LLMResult(None, raw, "invalid_json", error=str(exc)[:300], model=self.model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 7), 1.0, 0.5] for t in texts]


def _n(p: Path) -> int:
    tail = p.stem.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0
