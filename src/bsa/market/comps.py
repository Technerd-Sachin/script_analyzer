"""Comps: Qdrant hybrid index (dense bge-m3 via Ollama + sparse BM25 via fastembed; only `bsa_` collections)
and search at analysis time with LLM rerank and the originality flag."""

import math
import uuid
from functools import lru_cache
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from bsa.config import get_config
from bsa.domain.llm import CompsExplainOut
from bsa.domain.report import Comp, StoryMap
from bsa.llm.client import OllamaClient
from bsa.pipeline.context import RunContext

DENSE, SPARSE = "dense", "bm25"


@lru_cache
def _sparse_model() -> Any:
    from fastembed import SparseTextEmbedding

    return SparseTextEmbedding(get_config().market.sparse_model)


def sparse_vectors(texts: list[str]) -> list[models.SparseVector]:
    return [
        models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
        for e in _sparse_model().embed(texts)
    ]


def client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=get_config().market.qdrant_url, timeout=60)


async def index_rows(rows: list[dict[str, Any]]) -> int:
    cfg = get_config()
    name = cfg.market.collection
    assert name.startswith("bsa_"), "only bsa_ collections may be touched"
    llm = OllamaClient(cfg.llm)
    q = client()
    if await q.collection_exists(name):
        await q.delete_collection(name)
    await q.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=1024, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    total = 0
    for i in range(0, len(rows), 16):
        batch = rows[i : i + 16]
        texts = [f"{r['title']}. {r['plot'][:1500]}" for r in batch]
        dense = await llm.embed(texts)
        sparse = sparse_vectors(texts)
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, r.get("url") or r["title"])),
                vector={DENSE: d, SPARSE: s},
                payload={
                    k: r.get(k) for k in ("title", "year", "language", "url", "imdb_id", "rating", "votes")
                }
                | {"plot": r["plot"][:1200]},
            )
            for r, d, s in zip(batch, dense, sparse, strict=True)
        ]
        await q.upsert(name, points=points)
        total += len(points)
    await q.close()
    return total


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def find_comps(ctx: RunContext, sm: StoryMap | None) -> tuple[list[Comp], bool, str]:
    mc = ctx.cfg.market
    summary = ctx.parts.get("summary")
    parts = [sm.logline if sm else "", " ".join(sm.premise_tags) if sm else ""]
    if sm and sm.central_conflict:
        parts.append(sm.central_conflict.text)
    if summary is not None and getattr(summary, "text", ""):
        parts.append(summary.text)
    query = " ".join(p for p in parts if p).strip() or (ctx.ir.title or "")
    q = client()
    try:
        if not await q.collection_exists(mc.collection):
            raise LookupError("corpus not built (run `bsa corpus build`)")
        dense = (await ctx.llm.embed([query]))[0]
        sparse = sparse_vectors([query])[0]
        res = await q.query_points(
            mc.collection,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, limit=50),
                models.Prefetch(query=sparse, using=SPARSE, limit=50),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=mc.top_k,
            with_payload=True,
            with_vectors=[DENSE],
        )
    finally:
        await q.close()
    hits = res.points
    if not hits:
        return [], False, ""
    cands = []
    for h in hits:
        p = h.payload or {}
        vec = h.vector.get(DENSE) if isinstance(h.vector, dict) else None
        flat = [float(x) for x in vec if not isinstance(x, list)] if isinstance(vec, list) else []
        cands.append({**p, "plot": str(p.get("plot", ""))[:450], "cos": _cos(dense, flat)})
    out = await ctx.call(
        "comps_explain",
        "comps_explain",
        CompsExplainOut,
        vars={"logline": sm.logline if sm else query, "candidates": cands},
        valid_ids=set(),
        texts={},
    )
    comps: list[Comp] = []
    flagged: list[str] = []
    picks = out.parsed.comps if out.parsed else []
    for pk in picks:
        if not 0 <= pk.candidate < len(cands):
            continue
        c = cands[pk.candidate]
        comp = Comp(
            title=str(c.get("title")),
            year=c.get("year"),
            language=c.get("language"),
            rating=c.get("rating"),
            votes=c.get("votes"),
            similarity=round(float(c["cos"]), 3),
            why_similar=pk.why_similar,
            differentiator=pk.differentiator,
            near_identical=pk.near_identical,
            source_url=str(c.get("url") or ""),
        )
        comps.append(comp)
        if pk.near_identical and comp.similarity >= mc.originality_tau:
            flagged.append(f"{comp.title} ({comp.year}, cosine {comp.similarity:.2f})")
    if not comps:  # fall back to retrieval order when the rerank fails
        comps = [
            Comp(
                title=str(c.get("title")),
                year=c.get("year"),
                language=c.get("language"),
                rating=c.get("rating"),
                votes=c.get("votes"),
                similarity=round(float(c["cos"]), 3),
                source_url=str(c.get("url") or ""),
            )
            for c in cands[:5]
        ]
    note = (
        f"Premise closely matches {', '.join(flagged)}. Check originality before greenlighting."
        if flagged
        else ""
    )
    return comps[:5], bool(flagged), note
