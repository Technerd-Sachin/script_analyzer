"""Feature C: localization fit per target language, with transcreations and subtitle checks."""

from typing import Any

from bsa.domain.llm import LocalizationOut
from bsa.domain.report import Cliffhanger, LocalizationReport, LocIssue, TargetFit, Transcreation
from bsa.pipeline.context import RunContext
from bsa.pipeline.nodes.common import LANG_NAME, opening_line
from bsa.scoring.rules import duration_s, subtitle_check

BULLET_LANGS = ["ta", "te", "bn", "mr"]
SCRIPTS = {
    "hi": ("Devanagari", 0x0900, 0x097F),
    "mr": ("Devanagari", 0x0900, 0x097F),
    "bn": ("Bengali", 0x0980, 0x09FF),
    "ta": ("Tamil", 0x0B80, 0x0BFF),
    "te": ("Telugu", 0x0C00, 0x0C7F),
    "en": ("Latin", 0x0041, 0x007A),
}


def script_share(text: str, lang: str) -> float:
    """Share of letters in the target language's script (a transcreation must be in native script)."""
    _, lo, hi = SCRIPTS.get(lang, ("", 0, 0x10FFFF))
    letters = [ch for ch in text if ch.isalpha()]
    return sum(lo <= ord(ch) <= hi for ch in letters) / len(letters) if letters else 0.0


def default_targets(primary: str) -> list[str]:
    if primary in ("hi", "hi-Latn"):
        return ["ta", "te", "bn"]
    if primary == "en":
        return ["hi", "ta", "te"]
    return ["hi"] + [lang for lang in BULLET_LANGS if lang != primary][:2]


def localization_candidates(ctx: RunContext) -> list[str]:
    """Code-found lines to verify: culture-bound lexicon hits and on-screen text (phones, signs, chats)."""
    import re
    import unicodedata

    out: list[str] = []
    terms = ctx.kb.lexicon("culture_bound.txt")
    for e in ctx.ir.elements:
        text = unicodedata.normalize("NFC", e.text.lower())
        if e.kind == "action" and e.text.upper().startswith("ON SCREEN"):
            out.append(f"{e.id} on_screen_text: {e.text[:80]}")
            continue
        found = [
            f"{kind} '{term}'"
            for term, kind in terms
            if re.search(
                rf"(?<![\w\u0900-\u0dff]){re.escape(unicodedata.normalize('NFC', term))}(?![\w\u0900-\u0dff])",
                text,
            )
        ]
        if found:
            out.append(f"{e.id} " + "; ".join(dict.fromkeys(found)))
    return out[:30]


def _profile_text(ctx: RunContext, lang: str) -> str:
    d = ctx.kb.profile(lang)
    if d is None:
        return f"{LANG_NAME.get(lang, lang)}: no profile on file."
    markers = "; ".join(str(m) for m in d.get("culture_markers") or [])
    return (
        f"Script: {d.get('script')}. Honorifics: {d.get('honorifics')}. Register: {d.get('register_notes')}.\n"
        f"Culture markers: {markers}.\nDub notes: {d.get('dub_notes')}.\n{d.body}"
    )


async def localization(ctx: RunContext) -> None:
    ir = ctx.ir
    rules = ctx.kb.subtitle_rules
    r = LocalizationReport(source_languages=ir.languages, code_mix_ratio=ir.code_mix_ratio)
    for e in ir.elements:
        if e.kind == "dialogue":
            flags = subtitle_check(e.text, rules)
            if flags:
                r.source_subtitle_flags.append({"line_id": e.id, "flags": flags})
    cl: Cliffhanger | None = ctx.parts.get("cliffhanger")
    key_lines = [i for i in (opening_line(ir), cl.line_id if cl else None) if i]
    targets = ctx.opts.localization_targets or default_targets(ir.primary_lang)
    for lang in targets:
        script_name = SCRIPTS.get(lang, ("native", 0, 0))[0]

        def check(d: dict[str, Any], lang: str = lang, script_name: str = script_name) -> list[str]:
            bad = [
                t["line_id"]
                for t in d.get("transcreations", [])
                if script_share(t["target_text"], lang) < 0.6
            ]
            return (
                [f"transcreations {bad}: target_text must be written in {script_name} script"] if bad else []
            )

        out = await ctx.call(
            f"localization[{lang}]",
            "localization",
            LocalizationOut,
            vars={
                "target": lang,
                "target_name": LANG_NAME.get(lang, lang),
                "profile": _profile_text(ctx, lang),
                "source_langs": ", ".join(f"{k} {v:.0%}" for k, v in ir.languages.items()),
                "code_mix": ir.code_mix_ratio if ir.code_mix_ratio is not None else "n/a",
                "lines_to_transcreate": ", ".join(dict.fromkeys(key_lines)) or "the opening line",
                "target_script": script_name,
                "candidates": localization_candidates(ctx),
            },
            checks=[check],
            cfg_key="localization",
        )
        r.notes.extend(out.notes)
        if out.parsed is None:
            r.targets.append(TargetFit(lang=lang, status="unavailable"))
            r.status = "partial"
            continue
        p = out.parsed
        trans: list[Transcreation] = []
        for t in p.transcreations:
            src = ir.by_id.get(t.line_id)
            if src is None or script_share(t.target_text, lang) < 0.6:
                continue  # never show a "transcreation" that is not in the target script
            secs = duration_s(src.text)
            trans.append(
                Transcreation(
                    line_id=t.line_id,
                    source_text=src.text,
                    target_text=t.target_text,
                    back_translation=t.back_translation,
                    notes=t.notes,
                    subtitle_flags=subtitle_check(t.target_text, rules, secs),
                )
            )
        r.targets.append(
            TargetFit(
                lang=lang,
                status="partial" if out.partial else "ok",
                fit_score=p.fit_score,
                fit_rationale=p.fit_rationale,
                issues=[LocIssue(**i.model_dump()) for i in p.issues],
                transcreations=trans,
            )
        )
    ctx.parts["localization"] = r
