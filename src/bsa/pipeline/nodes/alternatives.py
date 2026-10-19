"""Feature A: alternative openings and endings, blind position-swapped judging and re-scoring."""

import re
from dataclasses import dataclass
from typing import Any

from bsa.domain.enums import FactorName
from bsa.domain.ir import Element, ScriptIR
from bsa.domain.llm import AltGenerateOut, JudgeOut, SingleFactorOut, VariantOut
from bsa.domain.report import AltElement, AlternativesReport, AltTarget, AltVariant, EpisodesReport
from bsa.ingest.language import detect_lang
from bsa.pipeline.context import RunContext
from bsa.pipeline.nodes.common import LANG_LABEL

OPENING_STRATEGIES = [
    "in_medias_res",
    "mystery_question",
    "conflict_first_line",
    "shock_reveal",
    "flash_forward",
    "voiceover_hook",
]
ENDING_STRATEGIES = [
    "revelation",
    "reversal",
    "threat",
    "unanswered_question",
    "emotional_gut_punch",
    "arrival",
]
STRUCTURAL = ("scene_heading", "episode_marker", "transition")
_INDIC = re.compile(r"[\u0900-\u0dff]")


@dataclass
class Target:
    id: str
    kind: str  # opening | ending | mid_ending
    episode: int
    factor: FactorName
    span: list[Element]


def _dialogue_idx(els: list[Element]) -> list[int]:
    return [i for i, e in enumerate(els) if e.kind == "dialogue"]


def opening_span(els: list[Element], max_span: int) -> list[Element]:
    start = next((i for i, e in enumerate(els) if e.kind not in STRUCTURAL), 0)
    d = [i for i in _dialogue_idx(els) if i >= start]
    end = start + max_span - 1
    if d:
        first = d[0]
        reply = next((i for i in d if els[i].speaker != els[first].speaker), first)
        end = min(end, reply)
    return [e for e in els[start : end + 1] if e.kind not in ("episode_marker",)]


def ending_span(els: list[Element], max_span: int) -> list[Element]:
    d = _dialogue_idx(els)
    start = max(0, len(els) - max_span)
    if d:
        last = d[-1]
        prev = next((i for i in reversed(d) if els[i].speaker != els[last].speaker and i < last), last)
        start = max(start, prev)
    return [e for e in els[start:] if e.kind not in STRUCTURAL] or els[-1:]


def pick_targets(ir: ScriptIR, eps: EpisodesReport | None, max_span: int) -> list[Target]:
    first, last = ir.episodes[0].number, ir.episodes[-1].number
    targets = [
        Target("T1", "opening", first, "opening_hook", opening_span(ir.episode_elements(first), max_span)),
        Target("T2", "ending", last, "cliffhanger_pull", ending_span(ir.episode_elements(last), max_span)),
    ]
    if eps and len(ir.episodes) > 2:
        middle = [e for e in eps.items if e.number != last]
        if middle:
            weakest = min(middle, key=lambda e: (e.ending_hook_strength, e.number))
            targets.append(
                Target(
                    "T3",
                    "mid_ending",
                    weakest.number,
                    "cliffhanger_pull",
                    ending_span(ir.episode_elements(weakest.number), max_span),
                )
            )
    return [t for t in targets if t.span]


def _words(texts: list[str]) -> int:
    return sum(len(t.split()) for t in texts)


def _indic_share(texts: list[str]) -> float:
    joined = "".join(texts)
    letters = sum(ch.isalpha() for ch in joined) or 1
    return len(_INDIC.findall(joined)) / letters


def _line(kind: str, speaker: str | None, text: str) -> str:
    return (
        f"{speaker}: {text}"
        if kind == "dialogue" and speaker
        else f"({kind}) {text}"
        if kind != "action"
        else text
    )


def plain(els: list[AltElement]) -> str:
    return "\n".join(_line(e.kind, e.speaker, e.text) for e in els)


def neutral(els: list[AltElement]) -> tuple[str, dict[str, str]]:
    texts = {f"E{i + 1}": e.text for i, e in enumerate(els)}
    body = "\n".join(f"E{i + 1} {_line(e.kind, e.speaker, e.text)}" for i, e in enumerate(els))
    return f"<script>\n{body}\n</script>", texts


def _to_alt(e: Element) -> AltElement:
    return AltElement(id=e.id, kind=e.kind, speaker=e.speaker, text=e.text)


def excerpt(ir: ScriptIR, t: Target, n: int) -> list[AltElement]:
    els = ir.episode_elements(t.episode) if t.kind == "mid_ending" else ir.elements
    return [_to_alt(e) for e in (els[:n] if t.kind == "opening" else els[-n:])]


def replaced(base: list[AltElement], span_ids: list[str], new: list[AltElement]) -> list[AltElement]:
    idx = [i for i, e in enumerate(base) if e.id in span_ids]
    if not idx:
        return base
    return base[: idx[0]] + new + base[idx[-1] + 1 :]


async def alternatives(ctx: RunContext) -> None:
    ir, cfg = ctx.ir, ctx.cfg.pipeline.alternatives
    report = AlternativesReport()
    for t in pick_targets(ir, ctx.parts.get("episodes"), cfg.max_span):
        try:
            report.targets.append(await run_target(ctx, t))
        except Exception as exc:  # noqa: BLE001 - one failed target keeps the others
            report.status = "partial"
            report.notes.append(f"{t.id} {t.kind}: {type(exc).__name__}")
    ctx.parts["alternatives"] = report


async def run_target(ctx: RunContext, t: Target) -> AltTarget:
    ir, cfg, kb = ctx.ir, ctx.cfg.pipeline.alternatives, ctx.kb
    span_ids = [e.id for e in t.span]
    span_texts = [e.text for e in t.span]
    words = _words(span_texts)
    lo, hi = max(4, int(words * 0.7)), max(8, int(words * 1.3 + 0.999))
    is_ending = t.kind != "opening"
    pool = ENDING_STRATEGIES if is_ending else OPENING_STRATEGIES
    craft = {i.id: i for i in kb.craft_items("cliffhanger" if is_ending else "opening")}
    strategies = [
        {"id": s, "description": craft[s].description if s in craft else s} for s in pool[: cfg.variants]
    ]
    ep_els = ir.episode_elements(t.episode)
    pos = [i for i, e in enumerate(ep_els) if e.id in span_ids]
    before = ep_els[max(0, pos[0] - 4) : pos[0]] if pos else []
    after = ep_els[pos[-1] + 1 : pos[-1] + 5] if pos else []
    span_lang = detect_lang(" ".join(span_texts)) or ir.primary_lang
    speakers = {e.speaker for e in ir.elements if e.speaker}

    def check(d: dict[str, Any]) -> list[str]:
        errs: list[str] = []
        got = [v["strategy"] for v in d.get("variants", [])]
        if len(set(got)) < min(len(strategies), len(got)) or len(got) < len(strategies):
            errs.append(
                f"variants: write exactly {len(strategies)} variants, one per strategy {[s['id'] for s in strategies]}"
            )
        for i, v in enumerate(d.get("variants", [])):
            n = _words([el["text"] for el in v["elements"]])
            if not lo <= n <= hi:
                errs.append(f"variants[{i}]: {n} words; must be {lo} to {hi}")
            unknown = {
                el["speaker"]
                for el in v["elements"]
                if el["kind"] == "dialogue"
                and el["speaker"]
                and el["speaker"].upper() not in {s.upper() for s in speakers}
            }
            if unknown:
                errs.append(f"variants[{i}]: unknown speakers {sorted(unknown)}; keep established characters")
            if is_ending and not v["pays_off_line_ids"]:
                errs.append(f"variants[{i}].pays_off_line_ids: cite the setup lines this ending pays off")
        return errs

    label = {
        "opening": "opening of episode 1",
        "ending": "ending of the final episode",
        "mid_ending": f"ending of episode {t.episode}",
    }[t.kind]
    gen = await ctx.call(
        f"alternatives_generate[{t.id}]",
        "alternatives_generate",
        AltGenerateOut,
        vars={
            "n": len(strategies),
            "target_label": label,
            "strategies": strategies,
            "span_text": "\n".join(f"{e.id} {_line(e.kind, e.speaker, e.text)}" for e in t.span),
            "span_words": words,
            "before_text": "\n".join(f"{e.id} {_line(e.kind, e.speaker, e.text)}" for e in before),
            "after_text": "\n".join(f"{e.id} {_line(e.kind, e.speaker, e.text)}" for e in after),
            "language": LANG_LABEL.get(span_lang, span_lang),
            "min_words": lo,
            "max_words": hi,
            "max_elements": cfg.max_span,
            "is_ending": is_ending,
        },
        checks=[check],
        cfg_key="alternatives_generate",
    )
    target = AltTarget(id=t.id, kind=t.kind, episode=t.episode, factor=t.factor, replaces_line_ids=span_ids)  # type: ignore[arg-type]
    if gen.parsed is None:
        return target
    base = excerpt(ir, t, cfg.excerpt_elements)
    criterion = kb.rubric_text([t.factor], with_body=True)
    orig_text, orig_ids = neutral(base)
    before_score = await _rescore(ctx, t, orig_text, orig_ids, criterion)
    for vi, v in enumerate(gen.parsed.variants[: cfg.variants]):
        texts = [e.text for e in v.elements]
        checks = (
            ("length", lo <= _words(texts) <= hi),
            ("language", abs(_indic_share(texts) - _indic_share(span_texts)) <= 0.10),
            (
                "setup IDs",
                all(i in ir.by_id for i in v.pays_off_line_ids)
                and (not is_ending or bool(v.pays_off_line_ids)),
            ),
        )
        fails = [name for name, ok in checks if not ok]
        if fails:  # hard constraints: never judge or show a variant that breaks them
            target.dropped.append(f"{v.strategy} ({', '.join(fails)})")
            continue
        target.variants.append(
            await _judge_variant(
                ctx, t, vi, v, base, span_ids, span_texts, before_score, criterion, lo, hi, label
            )
        )
    target.variants.sort(
        key=lambda v: ({"win": 0, "tie": 1, "loss": 2}.get(v.pairwise or "loss", 3), -(v.delta or 0))
    )
    return target


async def _rescore(
    ctx: RunContext, t: Target, text: str, ids: dict[str, str], criterion: str
) -> float | None:
    scores: list[int] = []
    for i in range(max(1, ctx.cfg.pipeline.alternatives.rescore_runs)):
        out = await ctx.call(
            f"alternatives_rescore[{t.id}.{i}]",
            "alternatives_rescore",
            SingleFactorOut,
            vars={"factor": t.factor, "rubric": criterion},
            script_text=text,
            valid_ids=set(ids),
            texts=ids,
            cfg_key="alternatives_rescore",
        )
        if out.parsed:
            scores.append(out.parsed.score)
    return sum(scores) / len(scores) if scores else None


async def _judge_variant(
    ctx: RunContext,
    t: Target,
    vi: int,
    v: VariantOut,
    base: list[AltElement],
    span_ids: list[str],
    span_texts: list[str],
    before: float | None,
    criterion: str,
    lo: int,
    hi: int,
    label: str,
) -> AltVariant:
    vid = f"A{t.id[1:]}.{vi + 1}"
    new = [
        AltElement(id=f"{vid}.{n + 1}", kind=e.kind, speaker=e.speaker, text=e.text)
        for n, e in enumerate(v.elements)
    ]
    variant_excerpt = replaced(base, span_ids, new)
    votes: list[str] = []
    coherent: list[bool] = []
    reasons: list[str] = []
    for order in ("orig_first", "variant_first"):
        x, y = (base, variant_excerpt) if order == "orig_first" else (variant_excerpt, base)
        text = f"EXCERPT X:\n{plain(x)}\n\nEXCERPT Y:\n{plain(y)}"
        out = await ctx.call(
            f"alternatives_judge[{vid}.{order}]",
            "alternatives_judge",
            JudgeOut,
            vars={"target_label": label, "criterion": criterion},
            script_text=text,
            valid_ids=set(),
            texts={},
            cfg_key="alternatives_judge",
        )
        if out.parsed is None:
            votes.append("none")
            continue
        p = out.parsed
        variant_is_x = order == "variant_first"
        if p.winner == "tie":
            votes.append("tie")
        else:
            votes.append("variant" if (p.winner == "X") == variant_is_x else "original")
        coherent.append(p.x_coherent if variant_is_x else p.y_coherent)
        reasons.append(p.reasoning)
    pairwise = (
        "win" if votes == ["variant", "variant"] else "loss" if votes == ["original", "original"] else "tie"
    )
    vtext, vids = neutral(variant_excerpt)
    after = await _rescore(ctx, t, vtext, vids, criterion)
    new_texts = [e.text for e in new]
    n_words = _words(new_texts)
    return AltVariant(
        id=vid,
        strategy=v.strategy,
        elements=new,
        replaces_line_ids=span_ids,
        pays_off_line_ids=[i for i in v.pays_off_line_ids if i in ctx.ir.by_id],
        rationale=v.rationale,
        pairwise=pairwise,
        judge_votes=votes,
        score_before=before,
        score_after=after,
        delta=round(after - before, 2) if after is not None and before is not None else None,
        coherence_ok=all(coherent) if coherent else None,
        coherence_reason=" | ".join(reasons),
        language_preserved=abs(_indic_share(new_texts) - _indic_share(span_texts)) <= 0.10,
        length_ok=lo <= n_words <= hi,
        ids_ok=all(i in ctx.ir.by_id for i in v.pays_off_line_ids)
        and (t.kind == "opening" or bool(v.pays_off_line_ids)),
    )
