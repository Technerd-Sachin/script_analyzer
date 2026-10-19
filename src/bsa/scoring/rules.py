"""Deterministic compliance and subtitle rules: lexicon prescan, age-rating matrix, statutory notices,
subtitle checks. The model classifies; this code decides."""

import re
import unicodedata
from typing import Any

from bsa.domain.enums import BANDS, RatingBand
from bsa.domain.ir import ScriptIR
from bsa.domain.report import Notice, RatingFinding
from bsa.knowledge import Knowledge

LEXICONS = {
    "profanity": "profanity.txt",
    "tobacco": "tobacco.txt",
    "alcohol": "alcohol.txt",
    "narcotics": "narcotics.txt",
    "weapons": "weapons.txt",
    "violence": "violence.txt",
    "sexual": "sexual.txt",
    "self_harm": "self_harm.txt",
    "slurs": "slurs.txt",
}


def _pattern(terms: list[str]) -> re.Pattern[str] | None:
    terms = sorted({unicodedata.normalize("NFC", t) for t in terms if t}, key=len, reverse=True)
    if not terms:
        return None
    alt = "|".join(re.escape(t) for t in terms)
    return re.compile(rf"(?<![\wऀ-෿])(?:{alt})(?![\wऀ-෿])", re.IGNORECASE)


def prescan(ir: ScriptIR, kb: Knowledge) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for cat, fname in LEXICONS.items():
        pat = _pattern([t for t, _ in kb.lexicon(fname)])
        if pat is None:
            continue
        ids = [e.id for e in ir.elements if pat.search(unicodedata.normalize("NFC", e.text))]
        if ids:
            hits[cat] = ids
    return hits


def depicted_hits(ir: ScriptIR, hits: dict[str, list[str]], category: str) -> list[str]:
    """Prescan hits in action lines: action describes what is shown on screen."""
    return [i for i in hits.get(category, []) if ir.by_id[i].kind == "action"]


DESCRIPTOR = {
    "violence": "Violence",
    "language": "Language",
    "sex": "Sex",
    "nudity": "Nudity",
    "substances": "Substance use",
    "imitable_behaviour": "Imitable behaviour",
    "discrimination": "Discrimination",
    "theme": "Theme",
}
SEVERITY_ORDER = ["none", "mild", "moderate", "strong", "explicit"]


def raise_band(band: RatingBand, steps: int = 1) -> RatingBand:
    return BANDS[min(len(BANDS) - 1, BANDS.index(band) + steps)]


def lower_band(band: RatingBand) -> RatingBand:
    return BANDS[max(0, BANDS.index(band) - 1)]


def band_for(
    f: RatingFinding,
    matrix: dict[str, dict[str, str]],
    raise_on: list[str],
    lower_on: list[str] | None = None,
) -> RatingBand:
    if f.severity == "none":
        return "U"
    raw = matrix.get(f.category, {}).get(f.severity, "U")
    band: RatingBand = raw.split(" +")[0].strip() if raw not in BANDS else raw  # type: ignore[assignment]
    if band not in BANDS:
        band = "A" if raw.startswith("A") else "U"
    if f.treatment in raise_on:
        band = raise_band(band)
    elif lower_on and f.mode in lower_on and f.severity != "explicit":
        band = lower_band(band)
    return band


def compute_rating(
    findings: list[RatingFinding],
    matrix: dict[str, dict[str, str]],
    raise_on: list[str],
    lower_on: list[str] | None = None,
) -> tuple[RatingBand, list[int], list[str], list[str], RatingBand]:
    """Return (band, driver indices, descriptors, access controls, band if drivers were addressed)."""
    for f in findings:
        f.band = band_for(f, matrix, raise_on, lower_on)
    if not findings:
        return "U", [], [], [], "U"
    top = max(BANDS.index(f.band or "U") for f in findings)
    band = BANDS[top]
    drivers = [i for i, f in enumerate(findings) if BANDS.index(f.band or "U") == top and top > 0]
    rest = [BANDS.index(f.band or "U") for i, f in enumerate(findings) if i not in drivers]
    lower = BANDS[max(rest)] if rest else "U"
    ranked = sorted(
        (f for f in findings if f.severity not in ("none",)),
        key=lambda f: (-SEVERITY_ORDER.index(f.severity), f.category),
    )
    descriptors: list[str] = []
    for f in ranked:
        d = DESCRIPTOR[f.category]
        if d not in descriptors:
            descriptors.append(d)
    return band, drivers, descriptors, access_controls(band), lower


def access_controls(band: RatingBand) -> list[str]:
    i = BANDS.index(band)
    out: list[str] = []
    if i >= BANDS.index("U/A 13+"):
        out.append("Parental lock")
    if band == "A":
        out.append("Reliable age verification")
    return out


RULES = {"tobacco": "cotpa_tobacco_2023", "narcotics": "mib_narcotics_2026"}


def build_notices(
    ir: ScriptIR, findings: list[RatingFinding], prescan_hits: dict[str, list[str]], kb: Knowledge
) -> list[Notice]:
    notices: list[Notice] = []
    for substance, rule_id in RULES.items():
        ids: list[str] = []
        for f in findings:
            if f.category == "substances" and f.substance == substance and f.mode == "depicted":
                ids.extend(f.line_ids)
        ids.extend(depicted_hits(ir, prescan_hits, substance))
        ids = sorted({i for i in ids if i in ir.by_id}, key=ir.index_of)
        if not ids:
            continue
        rule = kb.rule(rule_id)
        sources = (rule.get("sources") if rule else None) or []
        notices.append(
            Notice(
                rule_id=rule_id,
                source=str(sources[0]) if sources else "",
                required_text=list(rule.get("required_text") or []) if rule else [],
                requirements=list(rule.get("requirements") or []) if rule else [],
                placement=str(rule.get("placement", "")) if rule else "",
                trigger_line_ids=ids,
                trigger_scenes=sorted({ir.by_id[i].scene_id for i in ids}, key=lambda s: int(s[1:])),
            )
        )
    return notices


DIALOGUE_WPM = 150


def wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def duration_s(text: str) -> float:
    return max(0.5, len(text.split()) / DIALOGUE_WPM * 60)


def subtitle_check(text: str, rules: dict[str, Any], seconds: float | None = None) -> list[str]:
    flags: list[str] = []
    seconds = seconds or duration_s(text)
    lines = wrap(text, int(rules["max_chars_per_line"]))
    if len(lines) > int(rules["max_lines"]):
        flags.append(
            f"needs {len(lines)} lines of {rules['max_chars_per_line']} chars (max {rules['max_lines']})"
        )
    if seconds > float(rules["max_duration_s"]):
        flags.append(f"event {seconds:.1f}s exceeds {rules['max_duration_s']}s: split it")
    cps = len(text.replace(" ", "")) / seconds if seconds else 0
    if cps > float(rules["reading_speed_cps"]):
        flags.append(f"reading speed {cps:.0f} cps exceeds {rules['reading_speed_cps']} cps")
    return flags
