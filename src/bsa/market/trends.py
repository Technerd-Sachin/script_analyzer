"""Trend snapshot from official open APIs only (no scraping, no invented numbers).

`bsa trends refresh`: for each trope, the comps corpus titles whose plots match the trope's cues (2023 onward)
are looked up in the Wikimedia Pageviews API. Momentum compares the last 90 days of views with the 90 before.
It is an audience-attention proxy, labelled as such. Fewer than 3 matching titles means `unknown`.
"""

import asyncio
import json
import re
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from bsa.config import ROOT, get_secrets
from bsa.knowledge import get_knowledge
from bsa.market.corpus import corpus_dir, user_agent

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{title}/daily/{start}/{end}"


def _views(client: httpx.Client, title: str, start: date, end: date) -> int | None:
    url = PAGEVIEWS.format(
        title=quote(title.replace(" ", "_"), safe=""),
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
    )
    r = client.get(url)
    if r.status_code != 200:
        return None
    return sum(int(i["views"]) for i in r.json().get("items", []))


def _refresh() -> int:
    kb = get_knowledge()
    rows: list[dict[str, Any]] = json.loads((corpus_dir() / "corpus_final.json").read_text(encoding="utf-8"))
    recent = [r for r in rows if int(r.get("year") or 0) >= 2023]
    today = date.today()
    mid, start = today - timedelta(days=90), today - timedelta(days=180)
    out_dir = ROOT / "knowledge" / "trends"
    out_dir.mkdir(exist_ok=True)
    written = 0
    with httpx.Client(headers={"User-Agent": user_agent()}, timeout=30) as client:
        for t in kb.tropes:
            cues = [c.lower() for c in t.cues if len(c) > 3]
            pats = [re.compile(rf"\b{re.escape(c)}\b") for c in cues]
            matched = [r for r in recent if sum(bool(p.search(r["plot"].lower())) for p in pats) >= 1][:12]
            evidence: list[str] = []
            prev_total = last_total = 0
            used = 0
            for r in matched:
                last = _views(client, r["title"], mid, today)
                time.sleep(0.2)
                prev = _views(client, r["title"], start, mid - timedelta(days=1))
                time.sleep(0.2)
                if last is None or prev is None:
                    continue
                used += 1
                prev_total += prev
                last_total += last
                evidence.append(
                    f"{r['title']} ({r.get('year')}): {prev} views then {last} views; {r.get('url', '')}"
                )
            if used < 3 or prev_total == 0:
                momentum = "unknown"
            else:
                change = (last_total - prev_total) / prev_total
                momentum = "rising" if change > 0.2 else "declining" if change < -0.2 else "stable"
            body = (
                f"Audience-attention proxy for the trope `{t.id}`: Wikipedia pageviews of {used} recent Indian titles whose plots "
                f"match its cues, last 90 days against the previous 90 days.\n\n"
                + (
                    "\n".join(f"- {e}" for e in evidence)
                    if evidence
                    else "- No cited evidence: momentum unknown."
                )
            )
            meta = {
                "type": "trend",
                "trope": t.id,
                "momentum": momentum,
                "as_of": today.isoformat(),
                "stale_after": (today + timedelta(days=30)).isoformat(),
                "generated": True,
                "verified": False,
                "method": "wikimedia_pageviews_proxy",
                "titles_used": used,
                "views_prev_90d": prev_total,
                "views_last_90d": last_total,
                "sources": ["https://wikimedia.org/api/rest_v1/ (Wikimedia Pageviews API)"],
            }
            import yaml

            (out_dir / f"{t.id}.md").write_text(
                f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n{body}\n", encoding="utf-8"
            )
            written += 1
    return written


async def refresh_trends() -> None:
    n = await asyncio.to_thread(_refresh)
    print(f"wrote {n} trend files to knowledge/trends/")


async def youtube_trends() -> None:
    if not get_secrets().youtube_api_key:
        print("YOUTUBE_API_KEY is not set in .env; skipping (optional).")
        return
    print("YouTube trend velocity is optional and not enabled in this build.")
