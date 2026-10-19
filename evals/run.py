"""Eval runner: `bsa eval run --suite core`. Writes evals/results/<timestamp>.json and .md (local model, no cost)."""

import json
import math
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from bsa.config import ROOT, get_config
from bsa.domain.options import AnalysisOptions
from bsa.ingest.detect import IngestError, ingest_path, ingest_text
from bsa.ingest.render import render_script
from bsa.knowledge import get_knowledge
from bsa.llm.client import OllamaClient
from bsa.pipeline.context import RunContext
from bsa.pipeline.nodes import core
from bsa.pipeline.run import analyze_ir
from evals import metrics as M

SUITE_FEATURES: dict[str, list[str]] = {
    "core": ["core", "analytics"],
    "rating": ["rating"],
    "localization": ["core", "localization"],
    "alternatives": ["core", "alternatives"],
    "market": ["core", "market"],
    "continuity": ["core", "analytics"],
    "injection": ["core"],
    "scanned": ["core", "rating"],
}
RESULTS = ROOT / "evals" / "results"


def labels() -> list[dict[str, Any]]:
    return yaml.safe_load((ROOT / "evals" / "labels.yaml").read_text(encoding="utf-8"))["scripts"]


async def engagement_only(text_or_path: Path | str, runs: int = 3) -> float | dict[str, float]:
    """Run just the engagement node (3 self-consistency runs) on a script. Used for metamorphic and stability tests."""
    cfg, kb = get_config(), get_knowledge()
    ir = ingest_path(text_or_path) if isinstance(text_or_path, Path) else ingest_text(text_or_path)
    text, mode = render_script(ir, cfg.limits.script_token_budget)
    ctx = RunContext(
        ir=ir,
        opts=AnalysisOptions(engagement_runs=runs),
        cfg=cfg,
        kb=kb,
        llm=OllamaClient(cfg.llm),
        script_text=text,
        render_mode=mode,
    )
    await core.engagement(ctx)
    rep = ctx.parts["engagement"]
    return {"overall": rep.overall or 0.0, **{f.name: f.score for f in rep.factors}}


def _drop_line(text: str, needle: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if needle not in ln)


def _flat_opening(text: str) -> str:
    lines = text.splitlines()
    head = [ln for ln in lines[:3] if ln.lower().startswith(("title:", "episode", "int.", "ext.", "scene"))]
    flat = [
        "The family eats breakfast. Sunlight on the table.",
        "MOTHER: Did you sleep well?",
        "FATHER: Yes, thank you. Pass the salt.",
        "MOTHER: The weather is nice today.",
    ]
    return "\n".join(head + flat + lines[len(head) :])


async def run_suite(suite: str, ids: list[str]) -> Path:
    items = [s for s in labels() if (suite == "all" or suite in s["suites"]) and (not ids or s["id"] in ids)]
    suites = list(SUITE_FEATURES) if suite == "all" else [suite]
    results: dict[str, Any] = {
        "suite": suite,
        "started": datetime.now().isoformat(timespec="seconds"),
        "model": get_config().llm.model,
        "scripts": {},
        "aggregate": {},
    }
    for s in items:
        for su in suites:
            if su not in s["suites"] or su == "scanned":
                continue
            key = f"{s['id']}:{su}"
            print(f"== {key}", flush=True)
            results["scripts"][key] = await run_one(s, su)
    if "scanned" in suites:
        for s in items:
            if "scanned" in s["suites"]:
                print(f"== {s['id']}:scanned", flush=True)
                results["scripts"][f"{s['id']}:scanned"] = await run_scanned(s)
    if suite in ("all", "core"):
        print("== metamorphic + stability", flush=True)
        results["metamorphic"] = await run_metamorphic()
    results["aggregate"] = aggregate(results)
    results["finished"] = datetime.now().isoformat(timespec="seconds")
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS / f"{stamp}-{suite}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown(results)
    (RESULTS / f"{stamp}-{suite}.md").write_text(md, encoding="utf-8")
    print(md)
    return out


async def run_one(s: dict[str, Any], suite: str) -> dict[str, Any]:
    exp = s.get("expect", {})
    opts = AnalysisOptions(features=SUITE_FEATURES[suite])  # type: ignore[arg-type]
    t0 = time.monotonic()
    try:
        ir = ingest_path(ROOT / s["file"])
        r = await analyze_ir(ir, opts, use_cache=False)
    except IngestError as exc:
        return {"error": f"{exc.code} {exc.message}"}
    out: dict[str, Any] = {
        "latency_s": round(time.monotonic() - t0, 1),
        "pages": r.ir_stats.get("pages"),
        "calls": r.meta.tokens.get("calls"),
        "repairs": r.meta.tokens.get("repairs"),
        "completion_tokens": r.meta.tokens.get("completion"),
        "grounding_errors": M.grounding_errors(r),
        "partial_sections": [
            n
            for n in (
                "summary",
                "emotion",
                "engagement",
                "cliffhanger",
                "suggestions",
                "rating",
                "localization",
                "alternatives",
                "market",
                "continuity",
            )
            if getattr(r, n).status == "partial"
        ],
        "report": r.cache_key,
    }
    if suite in ("core", "injection", "continuity", "alternatives", "localization", "market"):
        out["overall"] = r.engagement.overall
        out["confidence"] = r.engagement.confidence
        out["group"] = exp.get("group")
        if exp.get("cliffhanger_contains"):
            out["cliffhanger"] = M.cliffhanger_hit(r, exp["cliffhanger_contains"])
        out["factors"] = M.factor_checks(r, exp.get("factor_low", []), exp.get("factor_high", []))
        out["episodes_detected"] = len(r.episodes.items)
        out["episodes_expected"] = s.get("episodes")
    if suite == "rating":
        out["rating"] = M.rating_checks(r, exp)
    if suite == "continuity" and exp.get("continuity"):
        out["continuity"] = M.continuity_recall(r, exp["continuity"])
    if suite == "localization":
        out["localization"] = M.localization_checks(r, exp)
    if suite == "injection" and exp.get("injection_canary"):
        out["injection"] = M.injection_ok(r, exp["injection_canary"])
    if suite == "alternatives":
        out["alternatives"] = M.alternatives_checks(r)
        out["alternatives_win_expected"] = bool(exp.get("alternatives_win"))
    if suite == "market":
        out["originality_flag"] = r.market.originality_flag
        out["originality_expected"] = bool(exp.get("originality"))
        out["tropes"] = [t.trope_id for t in r.market.tropes]
        out["comps"] = [c.title for c in r.market.comps]
    return out


async def run_scanned(s: dict[str, Any]) -> dict[str, Any]:
    stem = Path(s["file"]).stem
    pdf = ROOT / "evals" / "scanned" / f"{stem}_scan.pdf"
    if not pdf.exists():
        return {"error": "scanned variant missing: run evals/augment.py"}
    try:
        scan_ir = ingest_path(pdf)
    except IngestError as exc:
        return {"error": f"{exc.code} {exc.message}"}
    text_ir = ingest_path(ROOT / s["file"])
    ref = " ".join(e.text for e in text_ir.elements)
    hyp = " ".join(e.text for e in scan_ir.elements)
    out: dict[str, Any] = {
        "cer": M.cer(ref, hyp),
        "elements_text": len(text_ir.elements),
        "elements_scan": len(scan_ir.elements),
        "episodes_scan": len(scan_ir.episodes),
        "ocr_conf": scan_ir.ocr_mean_conf,
    }
    opts = AnalysisOptions(features=SUITE_FEATURES["scanned"])  # type: ignore[arg-type]
    rs = await analyze_ir(scan_ir, opts, use_cache=False)
    rt = await analyze_ir(text_ir, opts, use_cache=False)
    out.update(
        {
            "overall_scan": rs.engagement.overall,
            "overall_text": rt.engagement.overall,
            "overall_within_0.7": rs.engagement.overall is not None
            and rt.engagement.overall is not None
            and abs(rs.engagement.overall - rt.engagement.overall) <= 0.7,
            "band_scan": rs.rating.rating,
            "band_text": rt.rating.rating,
            "same_band": rs.rating.rating == rt.rating.rating,
        }
    )
    return out


async def run_metamorphic() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sid in ("s01_last_message", "s02_strong_three_episodes"):
        s = next(x for x in labels() if x["id"] == sid)
        text = (ROOT / s["file"]).read_text(encoding="utf-8")
        base = await engagement_only(text)
        cut = await engagement_only(_drop_line(text, s["expect"]["cliffhanger_contains"]))
        flat = await engagement_only(_flat_opening(text))
        out[sid] = {
            "base": base,
            "cliffhanger_removed": cut,
            "flat_opening": flat,
            "cliffhanger_pull_drop>=1": base.get("cliffhanger_pull", 0) - cut.get("cliffhanger_pull", 0) >= 1,  # type: ignore[union-attr]
            "opening_hook_drop>=1": base.get("opening_hook", 0) - flat.get("opening_hook", 0) >= 1,  # type: ignore[union-attr]
        }
    s02 = ROOT / next(x for x in labels() if x["id"] == "s02_strong_three_episodes")["file"]
    overalls = [float((await engagement_only(s02))["overall"]) for _ in range(3)]  # type: ignore[index]
    out["stability_s02"] = {"overall": overalls, "std": round(statistics.pstdev(overalls), 2)}
    return out


def aggregate(res: dict[str, Any]) -> dict[str, Any]:
    rows = res["scripts"]
    agg: dict[str, Any] = {}
    core_rows = {k: v for k, v in rows.items() if "overall" in v and v.get("overall") is not None}
    strong = [v["overall"] for v in core_rows.values() if v.get("group") == "strong"]
    weak = [v["overall"] for v in core_rows.values() if v.get("group") == "weak"]
    if strong and weak:
        pairs = [(a, b) for a in strong for b in weak]
        agg["ranking_pairs_correct"] = f"{sum(a > b for a, b in pairs)}/{len(pairs)}"
    produced = [v for v in rows.values() if "error" not in v and "grounding_errors" in v]
    agg["schema_valid"] = f"{len(produced)}/{len([v for v in rows.values() if 'cer' not in v])}"
    agg["grounding_valid"] = f"{sum(v['grounding_errors'] == 0 for v in produced)}/{len(produced)}"
    cl = [v["cliffhanger"] for v in rows.values() if "cliffhanger" in v]
    if cl:
        agg["cliffhanger_strict"] = f"{sum(c['strict'] for c in cl)}/{len(cl)}"
        agg["cliffhanger_lenient"] = f"{sum(c['lenient'] for c in cl)}/{len(cl)}"
    rt = [v["rating"] for v in rows.values() if "rating" in v]
    if rt:
        agg["rating_band_within_1"] = f"{sum(bool(r.get('band_within_1')) for r in rt)}/{len(rt)}"
        ex = [r for r in rt if "band_exact" in r]
        agg["rating_band_exact"] = f"{sum(bool(r['band_exact']) for r in ex)}/{len(ex)}"
        nr = [r["notice_recall"] for r in rt if r.get("notice_recall") is not None]
        if nr:
            agg["notice_recall"] = round(sum(nr) / len(nr), 2)
    loc = [
        v["localization"]["planted_recall"]
        for v in rows.values()
        if v.get("localization", {}).get("planted_recall") is not None
    ]
    if loc:
        agg["localization_planted_recall"] = round(sum(loc) / len(loc), 2)
    alt = [v for v in rows.values() if "alternatives" in v and v["alternatives"].get("variants") is not None]
    if alt:
        agg["alternatives_hard_constraints"] = round(
            sum(v["alternatives"]["hard_constraints"] for v in alt) / len(alt), 2
        )
        agg["alternatives_win_where_expected"] = (
            f"{sum(v['alternatives']['wins'] > 0 for v in alt if v.get('alternatives_win_expected'))}/{sum(bool(v.get('alternatives_win_expected')) for v in alt)}"
        )
    cont = [
        v["continuity"]["recall"] for v in rows.values() if v.get("continuity", {}).get("recall") is not None
    ]
    if cont:
        agg["continuity_recall"] = round(sum(cont) / len(cont), 2)
    inj = [v["injection"] for v in rows.values() if "injection" in v]
    if inj:
        agg["injection_resistance"] = (
            f"{sum(i['canary_absent'] and i['overall_not_10'] for i in inj)}/{len(inj)}"
        )
    orig = [v for v in rows.values() if "originality_flag" in v]
    if orig:
        agg["originality_flag_correct"] = (
            f"{sum(v['originality_flag'] == v['originality_expected'] for v in orig)}/{len(orig)}"
        )
    scans = [v for v in rows.values() if "cer" in v]
    if scans:
        agg["ocr_cer"] = {k.split(":")[0]: v["cer"] for k, v in rows.items() if "cer" in v}
        agg["scanned_overall_within_0.7"] = (
            f"{sum(bool(v.get('overall_within_0.7')) for v in scans)}/{len(scans)}"
        )
        agg["scanned_same_band"] = f"{sum(bool(v.get('same_band')) for v in scans)}/{len(scans)}"
    lat = [v["latency_s"] for v in produced if "latency_s" in v]
    if lat:
        agg["latency_s_mean"] = round(statistics.mean(lat), 1)
        agg["latency_s_p95"] = round(sorted(lat)[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)], 1)
    agg["cost_usd"] = 0.0
    return agg


def to_markdown(res: dict[str, Any]) -> str:
    out = [
        f"# Eval results: suite `{res['suite']}`, model `{res['model']}`, {res['started']}",
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    out += [f"| {k} | {v} |" for k, v in res["aggregate"].items()]
    out += [
        "",
        "## Per script",
        "",
        "| Script:suite | Overall | Conf | Latency s | Calls | Grounding errors | Checks |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, v in res["scripts"].items():
        if "error" in v:
            out.append(f"| {k} | - | - | - | - | - | error: {v['error']} |")
            continue
        checks = {
            kk: vv
            for kk, vv in v.items()
            if kk
            in (
                "cliffhanger",
                "factors",
                "rating",
                "continuity",
                "localization",
                "injection",
                "alternatives",
                "originality_flag",
                "cer",
                "overall_within_0.7",
                "same_band",
                "episodes_detected",
            )
        }
        out.append(
            f"| {k} | {v.get('overall', v.get('overall_scan', '-'))} | {v.get('confidence', '-')} | {v.get('latency_s', '-')} | {v.get('calls', '-')} | {v.get('grounding_errors', '-')} | `{json.dumps(checks, ensure_ascii=False)}` |"
        )
    if "metamorphic" in res:
        out += [
            "",
            "## Metamorphic and stability",
            "",
            "```json",
            json.dumps(res["metamorphic"], indent=1),
            "```",
        ]
    return "\n".join(out) + "\n"
