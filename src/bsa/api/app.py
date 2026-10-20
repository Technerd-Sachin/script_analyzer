"""FastAPI service: jobs, SSE progress, reports, page images, health."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from bsa.config import get_config, get_secrets
from bsa.domain.options import AnalysisOptions
from bsa.ingest.detect import SUPPORTED, doc_hash
from bsa.jobs.store import Store
from bsa.jobs.worker import JobManager, QueueFull
from bsa.knowledge import get_knowledge
from bsa.pipeline.run import cache_key, is_complete, load_cached
from bsa.report_md import to_markdown

cfg = get_config()
DATA = cfg.path(cfg.paths.data_dir)
store = Store(DATA / "bsa.sqlite")
jobs = JobManager(store, cfg)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await jobs.start()
    cleaner = asyncio.create_task(_cleanup_loop())
    yield
    cleaner.cancel()
    await jobs.stop()


async def _cleanup_loop() -> None:
    while True:
        await jobs.cleanup()
        await asyncio.sleep(3600)


app = FastAPI(title="Bullet Script Analyzer", version="0.1.0", lifespan=lifespan)


def auth(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_secrets().bsa_api_key
    if not expected:
        raise HTTPException(503, "BSA_API_KEY is not configured on the server")
    if x_api_key != expected:
        raise HTTPException(401, "missing or invalid X-API-Key")


Auth = Annotated[None, Depends(auth)]


def _save_upload(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(415, f"unsupported file type {ext!r}")
    if len(data) > cfg.limits.max_bytes:
        raise HTTPException(413, f"file is {len(data):,} bytes; limit {cfg.limits.max_bytes:,}")
    doc_id = doc_hash(data)
    up = DATA / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    path = up / f"{doc_id}{ext}"
    path.write_bytes(data)
    store.add_document(doc_id, filename, len(data), str(path))
    return doc_id


@app.post("/v1/jobs", status_code=202)
async def create_job(
    request: Request,
    _: Auth,
    file: Annotated[UploadFile | None, File()] = None,
    options: Annotated[str | None, Form()] = None,
) -> Any:
    if file is not None:
        data = await file.read()
        filename = file.filename or "upload.txt"
        opts = AnalysisOptions.model_validate_json(options) if options else AnalysisOptions()
    else:
        body = await request.json()
        text = str(body.get("text", ""))
        if not text.strip():
            raise HTTPException(422, "provide a file or JSON {text}")
        title = body.get("title")
        if title and not text.lstrip().lower().startswith("title:"):
            text = f"Title: {title}\n{text}"
        if len(text) > cfg.limits.max_text_chars:
            raise HTTPException(413, f"text is {len(text):,} characters; limit {cfg.limits.max_text_chars:,}")
        data, filename = text.encode("utf-8"), "pasted.txt"
        opts = AnalysisOptions.model_validate(body.get("options") or {})
    doc_id = _save_upload(data, filename)
    cached = _cached_report(doc_id, filename, data, opts)
    if cached:
        return JSONResponse(
            {"job_id": None, "doc_id": doc_id, "report_url": f"/v1/reports/{cached}", "cached": True},
            status_code=200,
        )
    job_id = store.create_job(doc_id, opts.model_dump(mode="json"))
    try:
        jobs.submit(job_id)
    except QueueFull as exc:
        raise HTTPException(429, "job queue is full; retry later") from exc
    return {"job_id": job_id, "doc_id": doc_id}


def _cached_report(doc_id: str, filename: str, data: bytes, opts: AnalysisOptions) -> str | None:
    """Cache lookup needs the IR doc_id only, which is the hash of the bytes."""
    from bsa.domain.ir import ScriptIR

    probe = ScriptIR(doc_id=doc_id)
    key = cache_key(probe, opts, cfg, get_knowledge(), cfg.llm.model)
    report = load_cached(key, cfg)
    return key if report is not None and is_complete(report) else None


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, _: Auth) -> Any:
    job = store.job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job_id,
        "doc_id": job["doc_id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "error": job["error"],
        "report_url": f"/v1/reports/{job['report_key']}" if job["report_key"] else None,
    }


@app.get("/v1/jobs/{job_id}/events")
async def job_events(job_id: str, _: Auth) -> StreamingResponse:
    if store.job(job_id) is None:
        raise HTTPException(404, "job not found")

    async def stream() -> AsyncIterator[str]:
        seq = -1
        idle = 0
        while True:
            events = store.events_after(job_id, seq)
            for ev in events:
                seq = ev["seq"]
                yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'])}\n\n"
                if ev["type"] in ("done", "error"):
                    return
            idle = 0 if events else idle + 1
            if idle and idle % 30 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/v1/reports/{key}")
async def get_report(key: str, _: Auth, format: str = "json") -> Response:
    report = load_cached(key, cfg)
    if report is None:
        raise HTTPException(404, "report not found")
    if format == "md":
        return PlainTextResponse(to_markdown(report), media_type="text/markdown")
    return Response(report.model_dump_json(), media_type="application/json")


@app.get("/v1/documents/{doc_id}/pages/{n}.png")
async def page_image(doc_id: str, n: int, _: Auth) -> Response:
    doc = store.document(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    cache = DATA / "pages" / f"{doc_id}_{n}.png"
    if not cache.exists():
        from bsa.ingest.pdf import render_page_png

        path = Path(doc["path"])
        try:
            png = await asyncio.to_thread(render_page_png, path.read_bytes(), path.suffix.lower(), n)
        except (IndexError, ValueError) as exc:
            raise HTTPException(404, "page not found") from exc
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(png)
    return Response(cache.read_bytes(), media_type="image/png")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    checks: dict[str, Any] = {"api_key_configured": bool(get_secrets().bsa_api_key)}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in (
            ("ollama", f"{cfg.llm.base_url}/api/tags"),
            ("ocr_doc_qna", f"{cfg.ocr.doc_qna_url}/healthz"),
            ("qdrant", f"{cfg.market.qdrant_url}/collections"),
        ):
            try:
                r = await client.get(url)
                checks[name] = r.status_code == 200
                if name == "ollama" and r.status_code == 200:
                    checks["model_present"] = any(
                        m["name"] == cfg.llm.model for m in r.json().get("models", [])
                    )
            except httpx.HTTPError:
                checks[name] = False
    ready = (
        checks["api_key_configured"] and checks.get("ollama", False) and checks.get("model_present", False)
    )
    return JSONResponse(
        {"ready": ready, "checks": checks, "knowledge_version": get_knowledge().version},
        status_code=200 if ready else 503,
    )
