"""Feature B: age rating estimate and compliance notices."""

from bsa.domain.llm import RatingClassifyOut, RatingLowerOut
from bsa.domain.report import LegalFlag, LowerEdit, RatingFinding, RatingReport
from bsa.pipeline.context import RunContext
from bsa.scoring.rules import build_notices, compute_rating, prescan


async def rating(ctx: RunContext) -> None:
    kb, ir = ctx.kb, ctx.ir
    hits = prescan(ir, kb)
    r = RatingReport(prescan=hits)
    candidates = "\n".join(f"- {cat}: {', '.join(ids[:25])}" for cat, ids in hits.items()) or "- none found"
    guidance = "\n".join(
        f"- {cat}: " + "; ".join(f"{sev} = {g}" for sev, g in levels.items())
        for cat, levels in kb.rating_guidance.items()
    )
    flags = kb.legal_flags
    out = await ctx.call(
        "rating_classify",
        "rating_classify",
        RatingClassifyOut,
        vars={
            "candidates": candidates,
            "guidance": guidance,
            "flag_ids": ", ".join(str(f.get("id")) for f in flags),
        },
    )
    r.notes.extend(out.notes)
    if out.partial:
        r.status = "partial"
    findings: list[RatingFinding] = []
    if out.parsed is None:
        r.status = "partial"
        r.notes.append("LLM classification unavailable; rating from notices and prescan only")
    else:
        findings = [
            RatingFinding(**f.model_dump())
            for f in out.parsed.findings
            if f.severity != "none" and f.line_ids
        ]
        # a substance finding needs lexicon support in its own lines (stops "cake frosting" false positives)
        substance_ids = {i for cat in ("tobacco", "alcohol", "narcotics") for i in hits.get(cat, [])}
        unsupported = [
            f for f in findings if f.category == "substances" and not set(f.line_ids) & substance_ids
        ]
        if unsupported:
            findings = [f for f in findings if f not in unsupported]
            r.notes.append(
                f"{len(unsupported)} substance finding(s) dropped: no substance term in the cited lines"
            )
        by_id = {str(f.get("id")): f for f in flags}
        r.legal_risk_flags = [
            LegalFlag(
                flag_id=lf.flag_id,
                name=str(by_id[lf.flag_id].get("name", lf.flag_id)),
                severity=str(by_id[lf.flag_id].get("severity", "medium")),
                line_ids=lf.line_ids,
                rationale=lf.rationale,
            )
            for lf in out.parsed.legal_flags
            if lf.flag_id in by_id and lf.line_ids
        ]
    band, drivers, descriptors, access, lower = compute_rating(
        findings, kb.rating_matrix, kb.treatment_raise, kb.mode_lower
    )
    r.findings, r.rating, r.rating_drivers, r.descriptors, r.access_controls = (
        findings,
        band,
        drivers,
        descriptors,
        access,
    )
    r.lower_rating_band = lower
    r.notices = build_notices(ir, findings, hits, kb)
    if drivers and band != "U":
        drv = [findings[i] for i in drivers]
        low = await ctx.call(
            "rating_lower",
            "rating_lower",
            RatingLowerOut,
            vars={"band": band, "drivers": [d.model_dump() for d in drv]},
        )
        r.notes.extend(low.notes)
        if low.parsed is not None:
            r.lower_rating_edits = [
                LowerEdit(
                    driver=f"{drv[e.driver].category}/{drv[e.driver].severity}"
                    if 0 <= e.driver < len(drv)
                    else "unknown",
                    line_ids=e.line_ids,
                    edit=e.edit,
                    rewrite=e.rewrite,
                )
                for e in low.parsed.edits
            ]
    ctx.parts["rating"] = r
