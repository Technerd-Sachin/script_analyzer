"""Comps corpus: Wikipedia film lists and plots (MediaWiki Action API), Wikidata IMDb IDs, IMDb ratings.

Run once with `bsa corpus build`. Results are cached in data/corpus/ and indexed in Qdrant `bsa_comps`.
Wikipedia text is CC BY-SA 4.0 (attribution and links are kept). IMDb data is non-commercial (demo only).
"""

import asyncio
import gzip
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from bsa.config import get_config, get_secrets

log = structlog.get_logger()
WIKI = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
IMDB_RATINGS = "https://datasets.imdbws.com/title.ratings.tsv.gz"
LANGUAGES = ["Hindi", "Tamil", "Telugu", "Bengali", "Marathi"]
YEARS = range(2026, 2009, -1)
TITLE_RE = re.compile(r"''\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]''")
PLOT_RE = re.compile(r"^==\s*(Plot|Synopsis|Premise|Storyline)\s*==\s*$", re.MULTILINE | re.IGNORECASE)


def corpus_dir() -> Path:
    cfg = get_config()
    d = cfg.path(cfg.paths.data_dir) / "corpus"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_agent() -> str:
    contact = get_secrets().bsa_contact or "set BSA_CONTACT in .env"
    return f"BulletScriptAnalyzer/0.1 (take-home demo; {contact}) httpx"


class Polite:
    """At most one request per `interval` seconds to a host."""

    def __init__(self, client: httpx.Client, interval: float = 1.0) -> None:
        self.client, self.interval, self._last = client, interval, 0.0

    def get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        wait = self.interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        for attempt in range(3):
            r = self.client.get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise httpx.HTTPError(f"retries exhausted for {url}")


def list_titles(api: Polite) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for lang in LANGUAGES:
        for year in YEARS:
            page = f"List of {lang} films of {year}"
            try:
                data = api.get(
                    WIKI,
                    {
                        "action": "parse",
                        "page": page,
                        "prop": "wikitext",
                        "format": "json",
                        "formatversion": 2,
                        "redirects": 1,
                    },
                )
            except httpx.HTTPError:
                continue
            text = str(data.get("parse", {}).get("wikitext", ""))
            for t in TITLE_RE.findall(text):
                t = t.strip()
                if t and t not in seen and not t.lower().startswith(("list of", "category:", "file:")):
                    seen.add(t)
                    out.append((t, year, lang))
            log.info("list_page", page=page, titles=len(out))
    return out


def strip_wikitext(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    for _ in range(5):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def fetch_plots(api: Polite, titles: list[str]) -> dict[str, dict[str, Any]]:
    """Up to 50 titles per request: latest wikitext, Wikidata item and URL. Returns {requested title: row}."""
    data = api.get(
        WIKI,
        {
            "action": "query",
            "prop": "revisions|pageprops|info",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(titles),
            "redirects": 1,
            "ppprop": "wikibase_item",
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
        },
    )
    q = data.get("query", {})
    back: dict[str, str] = {t: t for t in titles}
    for key in ("normalized", "redirects"):
        for m in q.get(key, []):
            for orig, cur in list(back.items()):
                if cur == m["from"]:
                    back[orig] = m["to"]
    by_title = {p["title"]: p for p in q.get("pages", []) if "missing" not in p}
    out: dict[str, dict[str, Any]] = {}
    for orig, cur in back.items():
        p = by_title.get(cur)
        if not p or not p.get("revisions"):
            continue
        wikitext = str(p["revisions"][0].get("slots", {}).get("main", {}).get("content", ""))
        m = PLOT_RE.search(wikitext)
        if not m:
            continue
        rest = wikitext[m.end() :]
        nxt = re.search(r"^==[^=].*==\s*$", rest, re.MULTILINE)
        plot = strip_wikitext(rest[: nxt.start() if nxt else len(rest)])
        if len(plot) >= 300:
            out[orig] = {
                "title": p["title"],
                "plot": plot[:2500],
                "url": p.get("fullurl", ""),
                "qid": p.get("pageprops", {}).get("wikibase_item"),
            }
    return out


def wikidata_ids(api: Polite, qids: list[str]) -> dict[str, str]:
    """IMDb IDs (P345) for Wikidata items via the Wikidata Query Service, 200 items per query."""
    out: dict[str, str] = {}
    for i in range(0, len(qids), 200):
        values = " ".join(f"wd:{q}" for q in qids[i : i + 200] if re.fullmatch(r"Q\d+", q))
        query = f"SELECT ?item ?imdb WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P345 ?imdb }}"
        try:
            data = api.get(WIKIDATA_SPARQL, {"query": query, "format": "json"})
        except httpx.HTTPError:
            log.warning("wikidata_batch_failed", start=i)
            continue
        for b in data.get("results", {}).get("bindings", []):
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            imdb = b["imdb"]["value"]
            if imdb.startswith("tt"):
                out.setdefault(qid, imdb)
    return out


def imdb_ratings(client: httpx.Client, wanted: set[str]) -> dict[str, tuple[float, int]]:
    path = corpus_dir() / "title.ratings.tsv.gz"
    if not path.exists():
        with client.stream("GET", IMDB_RATINGS) as r:
            r.raise_for_status()
            with path.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    out: dict[str, tuple[float, int]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            tconst, rating, votes = line.rstrip("\n").split("\t")
            if tconst in wanted:
                out[tconst] = (float(rating), int(votes))
    return out


def _fetch(limit: int) -> list[dict[str, Any]]:
    store = corpus_dir() / "corpus.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["list_title"]] = row
    with httpx.Client(headers={"User-Agent": user_agent()}, timeout=30, follow_redirects=True) as client:
        api = Polite(client, 1.0)
        titles_path = corpus_dir() / "titles.json"
        if titles_path.exists():
            titles = [tuple(t) for t in json.loads(titles_path.read_text())]
        else:
            titles = list_titles(api)
            titles_path.write_text(json.dumps(titles))
        todo = [t for t in titles[:limit] if t[0] not in done]
        with store.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), 50):
                chunk = todo[i : i + 50]
                try:
                    found = fetch_plots(api, [str(t[0]) for t in chunk])
                except httpx.HTTPError:
                    found = {}
                for title, year, lang in chunk:
                    rec = {
                        "list_title": title,
                        "year": year,
                        "language": lang,
                        **found.get(str(title), {"plot": ""}),
                    }
                    done[str(title)] = rec
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log.info("plots", done=i + len(chunk), kept=sum(1 for r in done.values() if r.get("plot")))
        rows = [r for r in done.values() if r.get("plot")]
        need = [r["qid"] for r in rows if r.get("qid") and "imdb_id" not in r]
        ids = wikidata_ids(Polite(client, 1.0), need) if need else {}
        for r in rows:
            r.setdefault("imdb_id", ids.get(r.get("qid") or ""))
        ratings = imdb_ratings(client, {r["imdb_id"] for r in rows if r.get("imdb_id")})
        for r in rows:
            if r.get("imdb_id") in ratings:
                r["rating"], r["votes"] = ratings[r["imdb_id"]]
    (corpus_dir() / "corpus_final.json").write_text(json.dumps(rows, ensure_ascii=False))
    return rows


async def build_corpus(limit: int) -> None:
    from bsa.market.comps import index_rows

    rows = await asyncio.to_thread(_fetch, limit)
    log.info("corpus_rows", rows=len(rows))
    n = await index_rows(rows)
    print(f"indexed {n} titles with plots into Qdrant collection {get_config().market.collection}")
