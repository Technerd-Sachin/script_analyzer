"""Rule-based analytics node and the continuity node."""

from typing import Any

from bsa.domain.llm import ContinuityOut
from bsa.domain.report import ContinuityIssue, ContinuityReport, StoryMap
from bsa.pipeline.context import RunContext
from bsa.scoring.analytics import compute, continuity_candidates, name_variant_lines, name_variants


async def analytics(ctx: RunContext) -> None:
    sm: StoryMap | None = ctx.parts.get("story_map")
    first = (
        sm.central_conflict.line_ids[0]
        if sm and sm.central_conflict and sm.central_conflict.line_ids
        else None
    )
    ctx.parts["analytics"] = compute(ctx.ir, first)


async def continuity(ctx: RunContext) -> None:
    cands = name_variants(ctx.ir)

    def check(d: dict[str, Any]) -> list[str]:
        return [
            f"issues[{i}]: needs at least 2 line IDs"
            for i, it in enumerate(d.get("issues", []))
            if len(it.get("line_ids", [])) < 2
        ]

    out = await ctx.call(
        "continuity",
        "continuity",
        ContinuityOut,
        vars={
            "name_candidates": "; ".join(" / ".join(g) for g in cands),
            "candidates": continuity_candidates(ctx.ir),
        },
        checks=[check],
    )
    r = ContinuityReport(
        notes=out.notes, status="partial" if out.partial else "ok", name_variant_candidates=cands
    )
    if out.parsed is None:
        r.status = "unavailable"
    else:
        r.issues = [ContinuityIssue(**i.model_dump()) for i in out.parsed.issues if len(set(i.line_ids)) >= 2]
    # speaker-name variants found by edit distance are reported even when the model misses them
    reported = {i for issue in r.issues if issue.type == "name" for i in issue.line_ids}
    for a, b in cands:
        ids = name_variant_lines(ctx.ir, a, b)
        if len(ids) == 2 and not set(ids) & reported:
            r.issues.append(
                ContinuityIssue(
                    type="name",
                    line_ids=ids,
                    explanation=f"Speaker spelled both {a} and {b} (detected by name matching).",
                    severity="medium",
                )
            )
    ctx.parts["continuity"] = r
