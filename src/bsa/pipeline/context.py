"""Per-job run context: the IR, options, knowledge, LLM port and the shared call/validate/repair loop."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

from bsa.config import Config
from bsa.domain.ir import ScriptIR
from bsa.domain.options import AnalysisOptions
from bsa.domain.report import NodeCall
from bsa.knowledge import Knowledge
from bsa.llm.client import LLMPort, Message, schema_hint
from bsa.llm.prompts import load_prompt
from bsa.pipeline.validate import Check, check_grounding, clean, normalize

log = structlog.get_logger()
Progress = Callable[[str, str, int], None]


@dataclass
class CallOutcome[T: BaseModel]:
    parsed: T | None
    notes: list[str] = field(default_factory=list)
    partial: bool = False


@dataclass
class RunContext:
    ir: ScriptIR
    opts: AnalysisOptions
    cfg: Config
    kb: Knowledge
    llm: LLMPort
    script_text: str
    render_mode: str
    progress: Progress | None = None
    parts: dict[str, Any] = field(default_factory=dict)
    calls: list[NodeCall] = field(default_factory=list)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    not_script: bool = False

    def emit(self, stage: str, status: str, elapsed_ms: int = 0) -> None:
        if self.progress:
            self.progress(stage, status, elapsed_ms)

    def preamble(self) -> str:
        p = load_prompt("_preamble")
        self.prompt_versions["_preamble"] = p.version
        return p.render()

    async def call[T: BaseModel](
        self,
        node: str,
        prompt: str,
        schema: type[T],
        *,
        vars: dict[str, Any] | None = None,
        checks: list[Check] | None = None,
        script_text: str | None = None,
        valid_ids: set[str] | None = None,
        texts: dict[str, str] | None = None,
        cfg_key: str | None = None,
        temperature: float | None = None,
    ) -> CallOutcome[T]:
        """One node call: render prompt, call the model, validate grounding, one repair round, then clean."""
        p = load_prompt(prompt)
        self.prompt_versions[prompt] = p.version
        node_cfg = self.cfg.llm.node(cfg_key or prompt)
        task = (
            p.render(**(vars or {}))
            + "\n\nReturn compact JSON on a single line (no indentation) matching this schema:\n"
            + schema_hint(schema)
        )
        messages = [
            Message("system", self.preamble()),
            Message("user", script_text if script_text is not None else self.script_text),
            Message("user", task),
        ]
        ids = valid_ids if valid_ids is not None else set(self.ir.by_id)
        txt = texts if texts is not None else {e.id: e.text for e in self.ir.elements}
        temp = temperature if temperature is not None else (node_cfg.temperature or 0.2)
        num_predict = node_cfg.num_predict

        res = await self.llm.structured(
            node=node, messages=messages, schema=schema, temperature=temp, num_predict=num_predict
        )
        self._record(node, res)
        if res.parsed is None and res.stop_reason in ("length", "invalid_json"):
            num_predict = min(int(num_predict * 1.6), 7000)
            res = await self.llm.structured(
                node=node, messages=messages, schema=schema, temperature=temp, num_predict=num_predict
            )
            self._record(node, res)
        if res.parsed is None:
            return CallOutcome(None, [f"{node}: no valid output ({res.stop_reason})"])

        data = normalize(res.parsed.model_dump())
        errors = check_grounding(data, ids, txt) + [e for c in (checks or []) for e in c(data)]
        if not errors:
            return CallOutcome(schema.model_validate(data))

        log.info("validation_failed", node=node, errors=len(errors))
        repair = messages + [
            Message("assistant", res.raw),
            Message(
                "user",
                "Your JSON has these problems:\n- "
                + "\n- ".join(errors[:15])
                + "\nUse only line IDs that appear in the script (like L12) and quote lines verbatim. "
                "Return the corrected complete JSON.",
            ),
        ]
        res2 = await self.llm.structured(
            node=node, messages=repair, schema=schema, temperature=temp, num_predict=num_predict
        )
        self._record(node, res2, repaired=True)
        best = data
        if res2.parsed is not None:
            data2 = normalize(res2.parsed.model_dump())
            errors2 = check_grounding(data2, ids, txt) + [e for c in (checks or []) for e in c(data2)]
            if not errors2:
                return CallOutcome(
                    schema.model_validate(data2), [f"{node}: repaired after {len(errors)} validation errors"]
                )
            best = data2 if len(errors2) <= len(errors) else data
        cleaned, dropped = clean(json.loads(json.dumps(best)), ids, txt)
        try:
            parsed = schema.model_validate(cleaned)
        except ValidationError:
            return CallOutcome(None, [f"{node}: output invalid after repair"], partial=True)
        return CallOutcome(
            parsed, [f"{node}: {dropped} invalid items dropped after one repair round"], partial=True
        )

    def _record(self, node: str, res: Any, repaired: bool = False) -> None:
        self.calls.append(
            NodeCall(
                node=node,
                model=res.model or self.llm.model,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
                latency_ms=res.latency_ms,
                prompt_eval_ms=res.prompt_eval_ms,
                repaired=repaired,
                stop_reason=res.stop_reason,
            )
        )


def timer() -> Callable[[], int]:
    t0 = time.monotonic()
    return lambda: int((time.monotonic() - t0) * 1000)
