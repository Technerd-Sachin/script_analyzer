"""Core analysis nodes: story map, episode map, summary, emotion, engagement, cliffhanger, suggestions."""

import asyncio
import re
from typing import Any

from bsa.domain.llm import (
    CliffhangerOut,
    EmotionOut,
    EngagementOut,
    EpisodeOut,
    StoryMapOut,
    SuggestionsOut,
    SummaryOut,
)
from bsa.domain.report import (
    Beat,
    Character,
    Cliffhanger,
    DominantEmotion,
    EmotionPoint,
    EmotionReport,
    EngagementReport,
    EpisodeReport,
    EpisodesReport,
    GroundedText,
    SceneTension,
    StoryMap,
    Suggestion,
    SuggestionsReport,
    Summary,
)
from bsa.pipeline.context import RunContext
from bsa.pipeline.nodes.common import id_range, lang_label
from bsa.scoring.engagement import aggregate


def _beat_hint(n: int) -> str:
    if n <= 12:
        return "2 to 5"
    if n <= 60:
        return "4 to 10"
    if n <= 200:
        return "8 to 20"
    return "15 to 40"


async def story_map(ctx: RunContext) -> None:
    ir = ctx.ir
    out = await ctx.call(
        "story_map",
        "story_map",
        StoryMapOut,
        vars={
            "n_lines": len(ir.elements),
            "first_id": ir.elements[0].id,
            "last_id": ir.elements[-1].id,
            "n_episodes": len(ir.episodes),
            "beat_hint": _beat_hint(len(ir.elements)),
        },
        checks=[lambda d: [] if d.get("beats") else ["beats: at least one beat is required"]],
    )
    sm = StoryMap(notes=out.notes, status="partial" if out.partial else "ok")
    if out.parsed is None:
        sm.status = "unavailable"
        sm.beats = _scene_beats(ctx)
        ctx.parts["story_map"] = sm
        return
    p = out.parsed
    sm.is_script = p.is_script
    sm.logline = p.logline
    sm.characters = [
        Character(name=c.name, want=c.want, obstacle=c.obstacle, line_ids=c.line_ids) for c in p.characters
    ]
    sm.central_conflict = GroundedText(text=p.central_conflict.text, line_ids=p.central_conflict.line_ids)
    sm.stakes = GroundedText(text=p.stakes.text, line_ids=p.stakes.line_ids)
    beats = [b for b in p.beats if b.start_line in ir.by_id and b.end_line in ir.by_id]
    beats.sort(key=lambda b: ir.index_of(b.start_line))
    sm.beats = [
        Beat(id=f"B{i + 1}", label=b.label, line_ids=id_range(ir, b.start_line, b.end_line))
        for i, b in enumerate(beats)
    ]
    if not sm.beats:
        sm.beats = _scene_beats(ctx)
    sm.premise_tags = p.premise_tags[:6]
    sm.devanagari_language = p.devanagari_language
    if p.devanagari_language == "mr" and "hi" in ir.languages:
        ir.languages = {("mr" if k == "hi" else k): v for k, v in ir.languages.items()}
    ctx.parts["story_map"] = sm
    if not p.is_script:
        ctx.not_script = True


def _scene_beats(ctx: RunContext) -> list[Beat]:
    return [
        Beat(id=f"B{i + 1}", label=sc.heading or sc.id, line_ids=sc.element_ids)
        for i, sc in enumerate(ctx.ir.scenes)
    ]


async def episode_map(ctx: RunContext, episode: int) -> None:
    ir = ctx.ir
    els = ir.episode_elements(episode)
    if not els:
        return
    ep_ids = {e.id for e in els}
    scene_ids = [s.id for s in ir.scenes if s.episode == episode]
    sm: StoryMap | None = ctx.parts.get("story_map")

    def check(d: dict[str, Any]) -> list[str]:
        errs = [
            f"ending_line_ids: {i} is outside episode {episode}"
            for i in d.get("ending_line_ids", [])
            if i not in ep_ids
        ]
        errs += [
            f"scene_tension: unknown scene {s['scene_id']}"
            for s in d.get("scene_tension", [])
            if s["scene_id"] not in scene_ids
        ]
        c = d.get("cliffhanger_candidate_line_id")
        if c and c not in ep_ids:
            errs.append(f"cliffhanger_candidate_line_id: {c} is outside episode {episode}")
        return errs

    out = await ctx.call(
        f"episode_map[{episode}]",
        "episode_map",
        EpisodeOut,
        vars={
            "episode": episode,
            "first_id": els[0].id,
            "last_id": els[-1].id,
            "scene_ids": ", ".join(scene_ids),
            "logline": sm.logline if sm else "",
        },
        checks=[check],
        cfg_key="episode_map",
    )
    eps: EpisodesReport = ctx.parts.setdefault("episodes", EpisodesReport())
    eps.notes.extend(out.notes)
    if out.parsed is None:
        eps.status = "partial"
        return
    p = out.parsed
    tension = [
        SceneTension(scene_id=s.scene_id, tension=s.tension)
        for s in p.scene_tension
        if s.scene_id in scene_ids
    ]
    eps.items.append(
        EpisodeReport(
            number=episode,
            one_line_summary=p.one_line_summary,
            scene_tension=tension,
            ending_line_ids=[i for i in p.ending_line_ids if i in ep_ids] or [els[-1].id],
            ending_hook_strength=p.ending_hook_strength,
            ending_rationale=p.ending_rationale,
            cliffhanger_candidate_line_id=p.cliffhanger_candidate_line_id
            if p.cliffhanger_candidate_line_id in ep_ids
            else None,
        )
    )
    eps.items.sort(key=lambda e: e.number)
    if out.partial:
        eps.status = "partial"


def _summary_check(d: dict[str, Any]) -> list[str]:
    text = str(d.get("text", ""))
    words = len(text.split())
    sentences = len([s for s in re.split(r"(?<=[.!?।])\s+", text.strip()) if s])
    errs: list[str] = []
    if words > 100:
        errs.append(f"text: {words} words; the maximum is 90")
    if not 2 <= sentences <= 5:
        errs.append(f"text: {sentences} sentences; write 3 to 4")
    return errs


async def summary(ctx: RunContext) -> None:
    sm: StoryMap | None = ctx.parts.get("story_map")
    out = await ctx.call(
        "summary", "summary", SummaryOut, vars={"logline": sm.logline if sm else ""}, checks=[_summary_check]
    )
    s = Summary(notes=out.notes, status="partial" if out.partial else "ok")
    if out.parsed is None:
        s.status = "unavailable"
    else:
        s.text, s.line_ids = out.parsed.text, out.parsed.line_ids
    ctx.parts["summary"] = s


async def emotion(ctx: RunContext) -> None:
    sm: StoryMap = ctx.parts.get("story_map") or StoryMap(beats=_scene_beats(ctx))
    beats = sm.beats[:60]
    beat_ids = {b.id: b for b in beats}

    def check(d: dict[str, Any]) -> list[str]:
        got = {a["beat_id"] for a in d.get("arc", [])}
        unknown = sorted(got - beat_ids.keys())
        missing = [b for b in beat_ids if b not in got]
        errs = [f"arc: unknown beat IDs {unknown[:5]}"] if unknown else []
        if len(missing) > max(1, len(beat_ids) // 4):
            errs.append(f"arc: missing beats {missing[:8]}")
        return errs

    out = await ctx.call(
        "emotion",
        "emotion",
        EmotionOut,
        vars={"taxonomy": ctx.kb.emotion_text(), "beats": [b.model_dump() for b in beats]},
        checks=[check],
    )
    r = EmotionReport(notes=out.notes, status="partial" if out.partial else "ok")
    if out.parsed is None:
        r.status = "unavailable"
    else:
        p = out.parsed
        r.arc = [
            EmotionPoint(
                beat_id=a.beat_id,
                line_ids=beat_ids[a.beat_id].line_ids,
                emotion=a.emotion,
                secondary=None if a.secondary == "none" else a.secondary,
                valence=a.valence,
                intensity=a.intensity,
            )
            for a in p.arc
            if a.beat_id in beat_ids
        ]
        r.arc.sort(key=lambda a: int(a.beat_id[1:]))
        total = sum(d.share for d in p.dominant) or 1.0
        r.dominant = [DominantEmotion(emotion=d.emotion, share=round(d.share / total, 2)) for d in p.dominant]
        r.arc_shape, r.narrative = p.arc_shape, p.narrative
    ctx.parts["emotion"] = r


def _episodes_info(ctx: RunContext) -> str:
    eps: EpisodesReport | None = ctx.parts.get("episodes")
    if not eps or len(ctx.ir.episodes) < 2:
        return ""
    return "\n".join(
        f"- Episode {e.number} ends at {', '.join(e.ending_line_ids)} (hook strength {e.ending_hook_strength}/5)"
        for e in eps.items
    )


async def engagement(ctx: RunContext) -> None:
    def check(d: dict[str, Any]) -> list[str]:
        names = [f["name"] for f in d.get("factors", [])]
        missing = [f for f in ctx.kb.weights if f not in names]
        return [f"factors: missing {missing}; return all 8"] if missing else []

    runs = max(1, ctx.opts.engagement_runs)
    vars = {
        "rubric": ctx.kb.rubric_text(),
        "calibration": ctx.kb.calibration_text(),
        "episodes_info": _episodes_info(ctx),
    }
    outs = await asyncio.gather(
        *[
            ctx.call(
                f"engagement[{i}]",
                "engagement",
                EngagementOut,
                vars=vars,
                checks=[check],
                cfg_key="engagement",
            )
            for i in range(runs)
        ]
    )
    good = [o.parsed.factors for o in outs if o.parsed is not None]
    r = aggregate(good, ctx.kb.weights) if good else EngagementReport(status="unavailable")
    r.notes.extend(n for o in outs for n in o.notes)
    if len(good) < runs and r.status == "ok":
        r.status = "partial"
        r.notes.append(f"{runs - len(good)} of {runs} engagement runs failed")
    ctx.parts["engagement"] = r


async def cliffhanger(ctx: RunContext) -> None:
    eps: EpisodesReport | None = ctx.parts.get("episodes")
    cands = ", ".join(
        f"episode {e.number}: {e.cliffhanger_candidate_line_id}"
        for e in (eps.items if eps else [])
        if e.cliffhanger_candidate_line_id
    )
    out = await ctx.call("cliffhanger", "cliffhanger", CliffhangerOut, vars={"candidates": cands})
    c = Cliffhanger(notes=out.notes, status="partial" if out.partial else "ok")
    if out.parsed is None:
        c.status = "unavailable"
    else:
        p = out.parsed
        c.line_id, c.technique, c.why_it_works, c.strength = (
            p.line_id,
            p.technique,
            p.why_it_works,
            p.strength,
        )
        c.quote = (
            ctx.ir.by_id[p.line_id].text if p.line_id in ctx.ir.by_id else p.quote
        )  # verbatim from the IR
    ctx.parts["cliffhanger"] = c


async def suggestions(ctx: RunContext) -> None:
    eng: EngagementReport | None = ctx.parts.get("engagement")
    cl: Cliffhanger | None = ctx.parts.get("cliffhanger")
    factors = sorted(eng.factors, key=lambda f: f.score) if eng else []
    weak = [f for f in factors if f.score <= 3] or factors[:3]
    lines = [
        f"- {f.name}: {f.score:g}/5. {f.rationale} (evidence {', '.join(f.evidence_line_ids)})" for f in weak
    ]
    if cl and cl.strength is not None and cl.strength <= 3:
        lines.append(f"- cliffhanger strength {cl.strength}/5 at {cl.line_id}: {cl.why_it_works}")
    n_min, n_max = ctx.cfg.pipeline.suggestions_min, ctx.cfg.pipeline.suggestions_max

    def check(d: dict[str, Any]) -> list[str]:
        n = len(d.get("suggestions", []))
        return [f"suggestions: {n} given; give at least {n_min}"] if n < n_min else []

    out = await ctx.call(
        "suggestions",
        "suggestions",
        SuggestionsOut,
        vars={
            "weak": "\n".join(lines) or "- none below 4; improve the lowest factors",
            "n_min": n_min,
            "n_max": n_max,
            "language": lang_label(ctx.ir),
        },
        checks=[check],
    )
    r = SuggestionsReport(notes=out.notes, status="partial" if out.partial else "ok")
    if out.parsed is None:
        r.status = "unavailable"
    else:
        order = {"high": 0, "medium": 1, "low": 2}
        items = sorted(out.parsed.suggestions, key=lambda s: order[s.impact])[:n_max]
        r.items = []
        for i, s in enumerate(items):
            s.example_rewrite = re.sub(
                r"(?m)^\s*L\d+\s*[:.]\s*", "", s.example_rewrite
            )  # no IDs inside rewrites
            r.items.append(Suggestion(id=f"G{i + 1}", **s.model_dump()))
    ctx.parts["suggestions"] = r
