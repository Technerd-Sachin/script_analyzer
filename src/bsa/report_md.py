"""Markdown rendering of an AnalysisReport (CLI and API ?format=md)."""

from bsa.domain.report import AnalysisReport


def _ids(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "-"


def to_markdown(r: AnalysisReport) -> str:
    out: list[str] = [f"# {r.title or 'Script'}: analysis", ""]
    if r.summary.text:
        out += ["## Summary", r.summary.text, f"_Lines: {_ids(r.summary.line_ids)}_", ""]
    e = r.engagement
    if e.overall is not None:
        out += [
            f"## Engagement: {e.overall}/10 (confidence {e.confidence}, {e.runs} runs: {e.per_run_overall})",
            "",
        ]
        out += ["| Factor | Weight | Score | Runs | Evidence | Rationale |", "|---|---|---|---|---|---|"]
        for f in e.factors:
            out.append(
                f"| {f.name} | {f.weight:.2f} | {f.score:g} | {f.run_scores} | {_ids(f.evidence_line_ids)} | {f.rationale} |"
            )
        out.append("")
    em = r.emotion
    if em.arc:
        dom = ", ".join(f"{d.emotion} {d.share:.0%}" for d in em.dominant)
        out += [f"## Emotion: {dom}; arc shape {em.arc_shape}", em.narrative, ""]
        out += ["| Beat | Lines | Emotion | Secondary | Valence | Intensity |", "|---|---|---|---|---|---|"]
        for a in em.arc:
            out.append(
                f"| {a.beat_id} | {a.line_ids[0]}..{a.line_ids[-1]} | {a.emotion} | {a.secondary or '-'} | {a.valence:+.2f} | {a.intensity:.2f} |"
            )
        out.append("")
    c = r.cliffhanger
    if c.line_id:
        out += [
            f"## Cliffhanger ({c.technique}, strength {c.strength}/5)",
            f"> {c.line_id}: {c.quote}",
            "",
            c.why_it_works,
            "",
        ]
    if r.suggestions.items:
        out += ["## Suggestions"]
        for s in r.suggestions.items:
            out += [
                f"### {s.id}. [{s.impact}] {s.category} ({s.linked_factor}) at {_ids(s.target_line_ids)}",
                f"- Issue: {s.issue}",
                f"- Fix: {s.fix}",
                f"- Example: `{s.example_rewrite}`",
                "",
            ]
    if r.episodes.items and len(r.episodes.items) > 1:
        out += ["## Episodes", "| # | Summary | Ending hook | Ending lines |", "|---|---|---|---|"]
        for ep in r.episodes.items:
            out.append(
                f"| {ep.number} | {ep.one_line_summary} | {ep.ending_hook_strength}/5 | {_ids(ep.ending_line_ids)} |"
            )
        out.append("")
    sm = r.story_map
    if sm.logline:
        out += ["## Story map", f"**Logline:** {sm.logline}", ""]
        if sm.central_conflict:
            out.append(f"**Conflict:** {sm.central_conflict.text} ({_ids(sm.central_conflict.line_ids)})")
        if sm.stakes:
            out.append(f"**Stakes:** {sm.stakes.text} ({_ids(sm.stakes.line_ids)})")
        for ch in sm.characters:
            out.append(f"- **{ch.name}**: wants {ch.want}; obstacle: {ch.obstacle}")
        out.append("")
    rt = r.rating
    if rt.rating:
        out += [
            f"## Age rating estimate: {rt.rating} ({', '.join(rt.descriptors) or 'no descriptors'})",
            f"_{rt.disclaimer}_",
            "",
        ]
        for f in rt.findings:
            out.append(
                f"- {f.category} / {f.severity} / {f.mode} / {f.treatment} -> {f.band} at {_ids(f.line_ids)}: {f.rationale}"
            )
        for n in rt.notices:
            out.append(
                f"- **Notice {n.rule_id}** at {_ids(n.trigger_line_ids)}: {' / '.join(n.required_text)}"
            )
        if rt.lower_rating_edits:
            out.append(f"- Lower-rating edits would reach {rt.lower_rating_band}:")
            out += [
                f"  - {x.driver} at {_ids(x.line_ids)}: {x.edit} -> `{x.rewrite}`"
                for x in rt.lower_rating_edits
            ]
        out.append("")
    if r.localization.targets:
        out += ["## Localization fit", f"_{r.localization.disclaimer}_", ""]
        for t in r.localization.targets:
            out.append(f"### {t.lang}: fit {t.fit_score}/5. {t.fit_rationale}")
            out += [
                f"- [{i.severity}] {i.type} at {_ids(i.line_ids)}: {i.explanation} -> {i.adaptation}"
                for i in t.issues
            ]
            out += [f"- {x.line_id}: {x.target_text} (back: {x.back_translation})" for x in t.transcreations]
            out.append("")
    if r.continuity.issues:
        out += (
            ["## Continuity"]
            + [
                f"- [{i.severity}] {i.type} at {_ids(i.line_ids)}: {i.explanation}"
                for i in r.continuity.issues
            ]
            + [""]
        )
    m = r.market
    if m.tropes or m.comps:
        out += ["## Market"]
        out += [f"- Trope {t.name} ({t.momentum}) at {_ids(t.line_ids)}: {t.rationale}" for t in m.tropes]
        out += [f"- Comp: {c.title} ({c.year}) rating {c.rating}: {c.why_similar}" for c in m.comps]
        if m.originality_flag:
            out.append(f"- **Originality flag:** {m.originality_note}")
        out.append("")
    for tg in r.alternatives.targets:
        out += [f"## Alternatives: {tg.kind} (replaces {_ids(tg.replaces_line_ids)})"]
        for v in tg.variants:
            out.append(
                f"### {v.id} {v.strategy}: {v.pairwise}, {tg.factor} {v.score_before} -> {v.score_after}"
            )
            out += [f"    {x.speaker + ': ' if x.speaker else ''}{x.text}" for x in v.elements]
        out.append("")
    meta = r.meta
    out += [
        "## Meta",
        f"- Model calls: {meta.tokens.get('calls')}, repairs: {meta.tokens.get('repairs')}, prompt tokens: "
        f"{meta.tokens.get('prompt')}, completion tokens: {meta.tokens.get('completion')}, cost: ${meta.cost_usd:.2f} (local)",
        f"- Total latency: {meta.total_latency_ms / 1000:.1f}s; knowledge {meta.knowledge_version}",
    ]
    out += [f"- Warning: {w}" for w in meta.warnings]
    return "\n".join(out) + "\n"
