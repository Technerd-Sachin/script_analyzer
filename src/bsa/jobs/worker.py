"""In-process job queue (asyncio) with SQLite job state. Dev-grade stand-in for a Redis-backed queue."""

import asyncio
import time
from pathlib import Path

import structlog

from bsa.config import Config
from bsa.domain.options import AnalysisOptions
from bsa.ingest.detect import IngestError, ingest_bytes
from bsa.jobs.store import Store
from bsa.pipeline.run import analyze_ir

log = structlog.get_logger()
NODES_TOTAL_HINT = 14


class QueueFull(Exception):
    pass


class JobManager:
    def __init__(self, store: Store, cfg: Config) -> None:
        self.store = store
        self.cfg = cfg
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=cfg.server.queue_max)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.cfg.server.queue_max)  # bound to the running loop
        # jobs survive a restart: anything queued or interrupted mid-run is queued again
        for job in self.store.jobs_in(("queued", "running")):
            self.store.update_job(job["id"], status="queued", stage="requeued after restart")
            self.queue.put_nowait(job["id"])
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def submit(self, job_id: str) -> None:
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull as exc:
            self.store.update_job(job_id, status="failed", error="queue full")
            raise QueueFull from exc

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._process(job_id)
            except Exception as exc:  # noqa: BLE001 - a crashed job must not stop the worker
                log.exception("job_crashed", job_id=job_id, error=type(exc).__name__)
                self.store.update_job(job_id, status="failed", error=type(exc).__name__)
                self.store.add_event(job_id, "error", {"code": 500, "message": type(exc).__name__})
            finally:
                self.queue.task_done()

    async def _process(self, job_id: str) -> None:
        job = self.store.job(job_id)
        if job is None:
            return
        doc = self.store.document(job["doc_id"])
        if doc is None:
            raise FileNotFoundError(job["doc_id"])
        opts = AnalysisOptions.model_validate_json(job["options"])
        self.store.update_job(job_id, status="running", stage="ingest", progress=0.02)
        self.store.add_event(job_id, "stage", {"name": "ingest", "status": "started", "elapsed_ms": 0})
        t0 = time.monotonic()
        try:
            ir = await asyncio.to_thread(
                ingest_bytes, Path(doc["path"]).read_bytes(), doc["filename"], self.cfg
            )
        except IngestError as exc:
            self.store.update_job(job_id, status="failed", error=exc.message)
            self.store.add_event(job_id, "error", {"code": exc.code, "message": exc.message})
            return
        self.store.add_event(
            job_id,
            "stage",
            {"name": "ingest", "status": "done", "elapsed_ms": int((time.monotonic() - t0) * 1000)},
        )
        done = 0

        def progress(stage: str, status: str, elapsed_ms: int) -> None:
            nonlocal done
            if status in ("done", "failed"):
                done += 1
            pct = min(0.97, 0.05 + 0.92 * done / (NODES_TOTAL_HINT + len(ir.episodes)))
            self.store.update_job(job_id, stage=stage, progress=round(pct, 3))
            self.store.add_event(job_id, "stage", {"name": stage, "status": status, "elapsed_ms": elapsed_ms})

        try:
            report = await analyze_ir(ir, opts, progress=progress)
        except IngestError as exc:
            self.store.update_job(job_id, status="failed", error=exc.message)
            self.store.add_event(job_id, "error", {"code": exc.code, "message": exc.message})
            return
        for name in (
            "summary",
            "emotion",
            "engagement",
            "cliffhanger",
            "suggestions",
            "rating",
            "localization",
            "alternatives",
            "market",
        ):
            self.store.add_event(job_id, "section", {"name": name, "status": getattr(report, name).status})
        self.store.update_job(job_id, status="done", stage="done", progress=1.0, report_key=report.cache_key)
        self.store.add_event(job_id, "done", {"report_url": f"/v1/reports/{report.cache_key}"})

    async def cleanup(self) -> int:
        cutoff = time.time() - self.cfg.server.retention_days * 86400
        n = 0
        for doc in self.store.old_documents(cutoff):
            Path(doc["path"]).unlink(missing_ok=True)
            self.store.delete_document(doc["doc_id"])
            n += 1
        return n
