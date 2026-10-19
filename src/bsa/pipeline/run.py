"""Entry point: IR + options -> AnalysisReport (with report cache)."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from bsa.config import ROOT, Config, get_config
from bsa.domain.enums import Feature
from bsa.domain.ir import ScriptIR
from bsa.domain.llm import EpisodeBoundariesOut
from bsa.domain.options import AnalysisOptions
from bsa.domain.report import AnalysisReport, Meta
from bsa.ingest.detect import IngestError
from bsa.ingest.episodes import apply_boundaries, heuristic_boundaries, needs_split
from bsa.ingest.render import estimate_tokens, render_script
from bsa.knowledge import Knowledge, get_knowledge
from bsa.llm.client import LLMPort, OllamaClient
from bsa.llm.prompts import split_front_matter
from bsa.pipeline.context import Progress, RunContext, timer
from bsa.pipeline.graph import build_graph

log = structlog.get_logger()
SECTIONS = (
    "story_map",
    "summary",
    "episodes",
    "emotion",
    "engagement",
    "cliffhanger",
    "suggestions",
    "analytics",
    "continuity",
    "alternatives",
    "rating",
    "localization",
    "market",
)
SECTION_FEATURE: dict[str, Feature] = {
    "analytics": "analytics",
    "continuity": "analytics",
    "alternatives": "alternatives",
    "rating": "rating",
    "localization": "localization",
    "market": "market",
}


def prompt_versions(cfg: Config) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(cfg.path(cfg.paths.prompts_dir).glob("*.md.j2")):
        meta, _ = split_front_matter(p.read_text(encoding="utf-8"))
        out[p.name.removesuffix(".md.j2")] = str(meta.get("version", "0"))
    return out


def cache_key(ir: ScriptIR, opts: AnalysisOptions, cfg: Config, kb: Knowledge, model: str) -> str:
    blob = json.dumps(
        {
            "doc": ir.doc_id,
            "opts": opts.cache_dict(),
            "prompts": prompt_versions(cfg),
            "kb": kb.version,
            "model": model,
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def reports_dir(cfg: Config) -> Path:
    d = cfg.path(cfg.paths.data_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_cached(key: str, cfg: Config | None = None) -> AnalysisReport | None:
    cfg = cfg or get_config()
    for d in (reports_dir(cfg), ROOT / cfg.paths.examples_dir):
        p = d / f"{key}.json"
        if p.exists():
            return AnalysisReport.model_validate_json(p.read_text(encoding="utf-8"))
    return None


async def split_episodes(ir: ScriptIR, ctx: RunContext) -> None:
    if not needs_split(ir):
        return
    scenes = ", ".join(
        f"{s.id} ({sum(len(ir.by_id[i].text.split()) for i in s.element_ids)} words)" for s in ir.scenes
    )
    out = await ctx.call(
        "episode_boundaries",
        "episode_boundaries",
        EpisodeBoundariesOut,
        vars={"scenes": scenes, "first_scene": ir.scenes[0].id},
    )
    if out.parsed and len(out.parsed.episode_start_scene_ids) > 1:
        apply_boundaries(ir, out.parsed.episode_start_scene_ids, "llm")
    else:
        apply_boundaries(ir, heuristic_boundaries(ir), "llm")
        ir.warnings.append("episode boundaries: LLM proposal unusable, used a word-count heuristic")


async def analyze_ir(
    ir: ScriptIR,
    opts: AnalysisOptions,
    *,
    progress: Progress | None = None,
    record_dir: Path | None = None,
    use_cache: bool = True,
    llm: LLMPort | None = None,
    cfg: Config | None = None,
    kb: Knowledge | None = None,
) -> AnalysisReport:
    cfg = cfg or get_config()
    kb = kb or get_knowledge()
    llm = llm or OllamaClient(cfg.llm, record_dir)
    key = cache_key(ir, opts, cfg, kb, llm.model)
    if use_cache and (cached := load_cached(key, cfg)) is not None:
        if progress:
            progress("cache", "hit", 0)
        return cached
    elapsed = timer()
    text, mode = render_script(ir, cfg.limits.script_token_budget)
    ctx = RunContext(
        ir=ir, opts=opts, cfg=cfg, kb=kb, llm=llm, script_text=text, render_mode=mode, progress=progress
    )
    await split_episodes(ir, ctx)
    ctx.script_text, ctx.render_mode = render_script(ir, cfg.limits.script_token_budget)
    if ctx.render_mode != "full":
        ir.warnings.append(
            f"script rendered in {ctx.render_mode} mode to fit the {cfg.llm.num_ctx}-token context"
        )
    await build_graph(ctx).ainvoke({"done": []})
    if ctx.not_script:
        raise IngestError(422, "The text does not look like a script (story map)")
    report = sanitize(assemble(ctx, key, elapsed()))
    if llm.model != "fake":
        (reports_dir(cfg) / f"{key}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


KEEP_VERBATIM = {"quote", "source_text", "text_verbatim"}


def _clean_dashes(node: object, key: str = "") -> object:
    if isinstance(node, str) and key not in KEEP_VERBATIM:
        return node.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ")
    if isinstance(node, dict):
        return {k: _clean_dashes(v, str(k)) for k, v in node.items()}  # type: ignore[union-attr]
    if isinstance(node, list):
        return [_clean_dashes(v, key) for v in node]  # type: ignore[union-attr]
    return node


def sanitize(report: AnalysisReport) -> AnalysisReport:
    """Replace em dashes in model-written prose (house style); verbatim quotes are untouched."""
    return AnalysisReport.model_validate(_clean_dashes(report.model_dump(mode="json")))


def assemble(ctx: RunContext, key: str, total_ms: int) -> AnalysisReport:
    ir = ctx.ir
    report = AnalysisReport(
        doc_id=ir.doc_id,
        cache_key=key,
        title=ir.title,
        options=ctx.opts,
        elements=ir.elements,
        ir_stats={
            "source_kind": ir.source_kind,
            "pages": ir.pages,
            "episodes": len(ir.episodes),
            "scenes": len(ir.scenes),
            "elements": len(ir.elements),
            "words": sum(len(e.text.split()) for e in ir.elements),
            "languages": ir.languages,
            "code_mix_ratio": ir.code_mix_ratio,
            "render_mode": ctx.render_mode,
            "script_tokens_est": estimate_tokens(ctx.script_text),
            "ocr_mean_conf": ir.ocr_mean_conf,
            "page_sources": {str(k): v for k, v in ir.page_sources.items()},
            "episode_boundaries": ir.episodes[0].boundary_source if ir.episodes else "single",
        },
    )
    for name in SECTIONS:
        if name in ctx.parts:
            setattr(report, name, ctx.parts[name])
        else:
            section = getattr(report, name)
            section.status = "unavailable"
            feature = SECTION_FEATURE.get(name, "core")
            section.notes.append(
                "feature disabled" if not ctx.opts.has(feature) else "node produced no output"
            )  # type: ignore[arg-type]
    for failed in ctx.parts.get("failed", []):
        report.meta.warnings.append(f"node failed: {failed}")
    by_node: dict[str, int] = {}
    for c in ctx.calls:
        base = c.node.split("[")[0]
        by_node[base] = by_node.get(base, 0) + c.latency_ms
    report.meta = Meta(
        models_by_node={c.node.split("[")[0]: c.model for c in ctx.calls},
        prompt_versions=dict(sorted(ctx.prompt_versions.items())),
        knowledge_version=ctx.kb.version,
        tokens={
            "prompt": sum(c.prompt_tokens for c in ctx.calls),
            "completion": sum(c.completion_tokens for c in ctx.calls),
            "calls": len(ctx.calls),
            "repairs": sum(c.repaired for c in ctx.calls),
        },
        cost_usd=0.0,
        latency_ms_by_node=by_node,
        total_latency_ms=total_ms,
        calls=ctx.calls,
        warnings=ir.warnings + ctx.warnings + report.meta.warnings,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    return report
