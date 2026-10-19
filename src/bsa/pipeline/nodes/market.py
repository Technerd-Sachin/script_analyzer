"""Market slice: trope tags (LLM over the taxonomy), comps (Qdrant hybrid search) and trend lookup."""

from datetime import date

import structlog

from bsa.domain.llm import TropesOut
from bsa.domain.report import MarketReport, StoryMap, TropeTag
from bsa.pipeline.context import RunContext

log = structlog.get_logger()


async def market(ctx: RunContext) -> None:
    kb = ctx.kb
    r = MarketReport()
    taxonomy = "\n".join(f"- {t.id}: {t.description}" for t in kb.tropes)
    valid = {t.id: t for t in kb.tropes}

    def check(d: dict[str, object]) -> list[str]:
        items = d.get("tropes", [])
        bad = [t["trope_id"] for t in items if t["trope_id"] not in valid] if isinstance(items, list) else []  # type: ignore[index]
        return [f"tropes: unknown trope ids {bad}; use ids from the taxonomy"] if bad else []

    out = await ctx.call("tropes", "tropes", TropesOut, vars={"taxonomy": taxonomy}, checks=[check])
    r.notes.extend(out.notes)
    if out.parsed is not None:
        as_of_dates: list[str] = []
        for t in out.parsed.tropes:
            if t.trope_id not in valid:
                continue
            tag = TropeTag(
                trope_id=t.trope_id,
                name=valid[t.trope_id].name,
                line_ids=t.line_ids,
                rationale=t.rationale,
                confidence=t.confidence,
            )
            trend = kb.trend(t.trope_id)
            if trend is not None:
                tag.momentum = trend.get("momentum", "unknown")
                tag.as_of = str(trend.get("as_of", "")) or None
                stale = trend.get("stale_after")
                tag.stale = bool(stale) and str(stale) < date.today().isoformat()
                if tag.as_of:
                    as_of_dates.append(tag.as_of)
            r.tropes.append(tag)
        r.trend_snapshot_as_of = max(as_of_dates) if as_of_dates else None
    else:
        r.status = "partial"
    sm: StoryMap | None = ctx.parts.get("story_map")
    try:
        from bsa.market.comps import find_comps

        r.comps, r.originality_flag, r.originality_note = await find_comps(ctx, sm)
    except Exception as exc:  # noqa: BLE001 - comps are optional (corpus may not be built)
        log.warning("comps_unavailable", error=type(exc).__name__)
        r.notes.append(f"comps unavailable: {type(exc).__name__}")
        if r.status == "ok":
            r.status = "partial"
    ctx.parts["market"] = r
