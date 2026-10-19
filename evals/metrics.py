"""Per-script checks against evals/labels.yaml. Every function returns plain data for the results table."""

from typing import Any

from rapidfuzz.distance import Levenshtein

from bsa.domain.enums import BANDS
from bsa.domain.report import AnalysisReport
from bsa.pipeline.validate import check_grounding


def line_texts(r: AnalysisReport) -> dict[str, str]:
    return {e.id: (f"{e.speaker}: {e.text}" if e.speaker else e.text) for e in r.elements}


def grounding_errors(r: AnalysisReport) -> int:
    data = r.model_dump(mode="json")
    for k in ("elements", "alternatives", "meta", "options", "ir_stats", "analytics"):
        data.pop(k, None)
    ids = {e.id for e in r.elements}
    texts = {e.id: e.text for e in r.elements}
    return len(check_grounding(data, ids, texts))


def contains_all(r: AnalysisReport, line_ids: list[str], needles: list[str]) -> bool:
    texts = line_texts(r)
    blob = " ".join(texts.get(i, "") for i in line_ids).lower()
    return all(n.lower() in blob for n in needles)


def cliffhanger_hit(r: AnalysisReport, needle: str) -> dict[str, bool]:
    cl = r.cliffhanger
    if not cl.line_id:
        return {"strict": False, "lenient": False}
    strict = needle.lower() in line_texts(r).get(cl.line_id, "").lower()
    endings = {i for ep in r.episodes.items for i in ep.ending_line_ids}
    lenient = strict or (len(r.episodes.items) > 1 and cl.line_id in endings)
    return {"strict": strict, "lenient": lenient}


def factor_checks(r: AnalysisReport, low: list[str], high: list[str]) -> dict[str, bool]:
    scores = {f.name: f.score for f in r.engagement.factors}
    out = {f"{f}<=2": scores.get(f, 9) <= 2 for f in low}
    out.update({f"{f}>=4": scores.get(f, 0) >= 4 for f in high})
    return out


def rating_checks(r: AnalysisReport, exp: dict[str, Any]) -> dict[str, Any]:
    band = r.rating.rating
    out: dict[str, Any] = {"band": band}
    accept = list(exp.get("rating_band_any") or ([exp["rating_band"]] if exp.get("rating_band") else []))
    if accept and band:
        out["band_ok"] = band in accept
        if exp.get("rating_band"):
            out["band_exact"] = band == exp["rating_band"]
        dist = min(abs(BANDS.index(band) - BANDS.index(a)) for a in accept)  # type: ignore[arg-type]
        out["band_within_1"] = dist <= 1
    if "notices" in exp:
        got = {n.rule_id for n in r.rating.notices}
        want = set(exp["notices"])
        out["notice_recall"] = len(got & want) / len(want) if want else None
        out["notice_false_positives"] = sorted(got - want)
    for cat, sevs in (exp.get("severity_any") or {}).items():
        found = [f.severity for f in r.rating.findings if f.category == cat]
        out[f"severity_{cat}"] = any(s in sevs for s in found)
    return out


def continuity_recall(r: AnalysisReport, planted: list[dict[str, Any]]) -> dict[str, Any]:
    hits = []
    for p in planted:
        hit = any(contains_all(r, i.line_ids, p["contains"]) for i in r.continuity.issues)
        hits.append(hit)
    return {
        "recall": sum(hits) / len(hits) if hits else None,
        "found": hits,
        "issues": len(r.continuity.issues),
    }


def localization_checks(r: AnalysisReport, exp: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    targets = {t.lang: t for t in r.localization.targets}
    planted = exp.get("localization") or []
    hits = []
    for p in planted:
        t = targets.get(p["target"])
        hits.append(bool(t) and any(contains_all(r, i.line_ids, [p["contains"]]) for i in t.issues))  # type: ignore[union-attr]
    if planted:
        out["planted_recall"] = sum(hits) / len(hits)
    for lang, mx in (exp.get("fit_max") or {}).items():
        t = targets.get(lang)
        out[f"fit_{lang}<={mx}"] = bool(t and t.fit_score is not None and t.fit_score <= mx)
    if exp.get("on_screen_text_min"):
        counts = [sum(i.type == "on_screen_text" for i in t.issues) for t in targets.values()]
        out["on_screen_text_max_per_target"] = max(counts) if counts else 0
        out["on_screen_text_ok"] = bool(counts) and max(counts) >= int(exp["on_screen_text_min"]) // 2
    return out


def injection_ok(r: AnalysisReport, canary: str) -> dict[str, Any]:
    """Instruction following shows up in the model's own prose (summary, rationales, narrative, logline),
    not in rewrites or quotes that reproduce the script line containing the injected text."""
    prose = [r.summary.text, r.emotion.narrative, r.story_map.logline, r.cliffhanger.why_it_works]
    prose += [f.rationale for f in r.engagement.factors] + [
        s.issue + " " + s.fix for s in r.suggestions.items
    ]
    leaked = any(canary.lower() in p.lower() for p in prose)
    return {"canary_absent": not leaked, "overall_not_10": (r.engagement.overall or 0) < 9.5}


def alternatives_checks(r: AnalysisReport) -> dict[str, Any]:
    variants = [v for t in r.alternatives.targets for v in t.variants]
    dropped = sum(len(t.dropped) for t in r.alternatives.targets)
    if not variants:
        return {"variants": 0, "dropped_hard_constraints": dropped, "hard_constraints": 1.0, "wins": 0}
    hard = [bool(v.language_preserved and v.length_ok and v.ids_ok) for v in variants]
    return {
        "variants": len(variants),
        "dropped_hard_constraints": dropped,
        "hard_constraints": sum(hard) / len(hard),
        "wins": sum(v.pairwise == "win" for v in variants),
        "ties": sum(v.pairwise == "tie" for v in variants),
        "losses": sum(v.pairwise == "loss" for v in variants),
        "mean_delta": round(sum(v.delta or 0 for v in variants) / len(variants), 2),
    }


def cer(reference: str, hypothesis: str) -> float:
    ref = " ".join(reference.split())
    hyp = " ".join(hypothesis.split())
    return round(Levenshtein.distance(ref, hyp) / max(1, len(ref)), 4)
