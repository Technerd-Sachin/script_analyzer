"""Command line interface: `bsa analyze`, `bsa ingest`, `bsa serve`, `bsa eval`, `bsa corpus`, `bsa trends`."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from bsa.config import get_config

app = typer.Typer(no_args_is_help=True, add_completion=False)
eval_app = typer.Typer(no_args_is_help=True)
corpus_app = typer.Typer(no_args_is_help=True)
trends_app = typer.Typer(no_args_is_help=True)
app.add_typer(eval_app, name="eval", help="Evaluation suite")
app.add_typer(corpus_app, name="corpus", help="Comps corpus (Wikipedia + Wikidata + IMDb)")
app.add_typer(trends_app, name="trends", help="Trend snapshot from open APIs")


@app.command()
def ingest(file: Path, show_ir: Annotated[bool, typer.Option("--show-ir")] = False) -> None:
    """Parse a script and print its structure (no LLM calls)."""
    from bsa.ingest.detect import IngestError, ingest_path
    from bsa.ingest.render import estimate_tokens, render_script

    try:
        ir = ingest_path(file)
    except IngestError as exc:
        typer.echo(f"error {exc.code}: {exc.message}", err=True)
        raise typer.Exit(1) from exc
    text, mode = render_script(ir, get_config().limits.script_token_budget)
    typer.echo(
        f"doc_id={ir.doc_id[:12]} title={ir.title!r} kind={ir.source_kind} pages={ir.pages} "
        f"episodes={len(ir.episodes)} scenes={len(ir.scenes)} elements={len(ir.elements)} "
        f"languages={ir.languages} code_mix={ir.code_mix_ratio} est_tokens={estimate_tokens(text)} render={mode}"
    )
    for w in ir.warnings:
        typer.echo(f"warning: {w}")
    if show_ir:
        typer.echo(text)


@app.command()
def analyze(
    file: Path,
    features: Annotated[
        str, typer.Option(help="Comma list: core,analytics,alternatives,rating,localization,market")
    ] = "",
    targets: Annotated[str, typer.Option(help="Localization targets, e.g. ta,te")] = "",
    out: Annotated[Path | None, typer.Option(help="Write the JSON report here")] = None,
    md: Annotated[Path | None, typer.Option(help="Write a Markdown report here")] = None,
    record: Annotated[Path | None, typer.Option(help="Record raw LLM outputs as test fixtures")] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
) -> None:
    """Run the full analysis pipeline in-process."""
    from bsa.domain.options import AnalysisOptions
    from bsa.ingest.detect import IngestError, ingest_path
    from bsa.pipeline.run import analyze_ir
    from bsa.report_md import to_markdown

    opts = AnalysisOptions()
    if features:
        opts.features = [f.strip() for f in features.split(",") if f.strip()]  # type: ignore[misc]
    if targets:
        opts.localization_targets = [t.strip() for t in targets.split(",") if t.strip()]  # type: ignore[misc]
    try:
        ir = ingest_path(file)
    except IngestError as exc:
        typer.echo(f"error {exc.code}: {exc.message}", err=True)
        raise typer.Exit(1) from exc

    def progress(stage: str, status: str, elapsed_ms: int) -> None:
        typer.echo(f"  [{status:>7}] {stage} ({elapsed_ms / 1000:.1f}s)", err=True)

    report = asyncio.run(analyze_ir(ir, opts, progress=progress, record_dir=record, use_cache=not no_cache))
    data = report.model_dump(mode="json")
    if out:
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if md:
        md.write_text(to_markdown(report), encoding="utf-8")
    eng = report.engagement
    typer.echo(
        f"overall={eng.overall} confidence={eng.confidence} rating={report.rating.rating} "
        f"llm_calls={len(report.meta.calls)} tokens={report.meta.tokens} cost_usd={report.meta.cost_usd} "
        f"latency_s={report.meta.total_latency_ms / 1000:.1f}"
    )
    if not out and not md:
        typer.echo(to_markdown(report))


@app.command()
def serve() -> None:
    """Run the API (FastAPI) on the configured host and port."""
    import uvicorn

    cfg = get_config()
    uvicorn.run("bsa.api.app:app", host=cfg.server.api_host, port=cfg.server.api_port, log_level="info")


@eval_app.command("run")
def eval_run(
    suite: Annotated[
        str,
        typer.Option(help="all|core|scanned|rating|localization|alternatives|market|continuity|injection"),
    ] = "core",
    ids: Annotated[str, typer.Option(help="Comma list of script ids to restrict to")] = "",
) -> None:
    """Run the eval suite against the local model and write evals/results/."""
    import sys

    from bsa.config import ROOT

    sys.path.insert(0, str(ROOT))
    from evals.run import run_suite

    asyncio.run(run_suite(suite, [i for i in ids.split(",") if i]))


@corpus_app.command("build")
def corpus_build(limit: Annotated[int, typer.Option()] = 0) -> None:
    """Build the comps corpus and index it in Qdrant (bsa_comps)."""
    from bsa.market.corpus import build_corpus

    asyncio.run(build_corpus(limit or get_config().market.corpus_limit))


@trends_app.command("refresh")
def trends_refresh() -> None:
    """Refresh knowledge/trends/*.md from Wikimedia pageviews of comps titles per trope."""
    from bsa.market.trends import refresh_trends

    asyncio.run(refresh_trends())


@trends_app.command("youtube")
def trends_youtube() -> None:
    """Optional: YouTube Data API view velocity per trope (needs YOUTUBE_API_KEY)."""
    from bsa.market.trends import youtube_trends

    asyncio.run(youtube_trends())


if __name__ == "__main__":
    app()
