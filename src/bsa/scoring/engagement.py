"""Engagement score: code computes the overall score and confidence from per-factor LLM judgments."""

import statistics

from bsa.domain.enums import FACTORS
from bsa.domain.llm import FactorOut
from bsa.domain.report import EngagementReport, FactorScore


def overall_from(scores: dict[str, float], weights: dict[str, float]) -> float:
    """overall = 10 * sum(w_i * (s_i - 1) / 4), weights renormalized over the factors present."""
    present = {k: w for k, w in weights.items() if k in scores}
    total_w = sum(present.values()) or 1.0
    return round(10 * sum(w * (scores[k] - 1) / 4 for k, w in present.items()) / total_w, 1)


def aggregate(runs: list[list[FactorOut]], weights: dict[str, float]) -> EngagementReport:
    by_factor: dict[str, list[FactorOut]] = {f: [] for f in FACTORS}
    for run in runs:
        seen: set[str] = set()
        for f in run:
            if f.name in seen:
                continue
            seen.add(f.name)
            by_factor[f.name].append(f)
    factors: list[FactorScore] = []
    spreads: list[float] = []
    for name in FACTORS:
        items = by_factor[name]
        if not items:
            continue
        scores = [i.score for i in items]
        med = float(statistics.median(scores))
        rep = min(items, key=lambda i: abs(i.score - med))
        factors.append(
            FactorScore(
                name=name,
                evidence_line_ids=rep.evidence_line_ids,
                weakness=rep.weakness,
                rationale=rep.rationale,
                score=med,
                weight=weights.get(name, 0.0),
                run_scores=scores,
            )
        )
        spreads.append(max(scores) - min(scores))
    per_run = [overall_from({f.name: float(f.score) for f in run}, weights) for run in runs if run]
    report = EngagementReport(factors=factors, runs=len(runs), per_run_overall=per_run)
    if factors:
        report.overall = overall_from({f.name: f.score for f in factors}, weights)
        report.confidence = round(1 - statistics.mean(spreads) / 4, 2)
    missing = [f for f in FACTORS if not by_factor[f]]
    if missing:
        report.status = "partial"
        report.notes.append(f"factors missing from every run: {', '.join(missing)}")
    return report
