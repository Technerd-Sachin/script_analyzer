"""Streamlit UI. Live mode calls the API; demo mode browses reports in examples/outputs/ with no key."""

import html
import io
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import charts  # noqa: E402
from bsa.config import get_config, get_secrets  # noqa: E402

st.set_page_config(page_title="Bullet Script Analyzer", layout="wide")
st.markdown(
    """<style>
    html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select { font-family: 'Trebuchet MS', sans-serif !important; }
    .line { padding: 2px 8px; border-left: 3px solid transparent; font-size: 0.95rem; }
    .line.hl { background: #fde3e7; border-left-color: #e81a3b; }
    .lid { color: #5b6e7f; font-family: monospace; margin-right: 8px; }
    .kind { color: #5b6e7f; font-size: 0.8rem; margin-right: 6px; }
    .spk { font-weight: bold; color: #333333; }
    .badge { display:inline-block; padding: 2px 10px; border-radius: 12px; background:#e7e7e7; color:#333; margin-right:6px; font-size:0.85rem; }
    .badge.red { background:#e81a3b; color:white; } .badge.green { background:#009966; color:white; } .badge.blue { background:#008fd2; color:white; }
    </style>""",
    unsafe_allow_html=True,
)

CFG = get_config()
API = f"http://{CFG.server.api_host}:{CFG.server.api_port}"
EXAMPLES = ROOT / CFG.paths.examples_dir
FEATURES = ["core", "analytics", "alternatives", "rating", "localization", "market"]
LANGS = ["hi", "ta", "te", "bn", "mr", "en"]


def headers() -> dict[str, str]:
    return {"X-API-Key": get_secrets().bsa_api_key}


def report() -> dict[str, Any] | None:
    return st.session_state.get("report")


def ids(xs: list[str]) -> str:
    return ", ".join(xs) if xs else "-"


def line_text(r: dict[str, Any], lid: str) -> str:
    for e in r.get("elements", []):
        if e["id"] == lid:
            return f"{e['speaker']}: {e['text']}" if e.get("speaker") else e["text"]
    return ""


def status_note(section: dict[str, Any]) -> None:
    if section.get("status") != "ok":
        st.caption(f"Section status: {section.get('status')}. " + "; ".join(section.get("notes", [])[:3]))


# ---------------------------------------------------------------------------------------------
def page_analyze() -> None:
    st.header("Analyze a script")
    demo = st.session_state.get("demo", False)
    if demo:
        files = sorted(EXAMPLES.glob("*.json"))
        if not files:
            st.info("No example reports in examples/outputs/ yet.")
            return
        names = {f"{json.loads(f.read_text())['title'] or f.stem} ({f.stem})": f for f in files}
        choice = st.selectbox("Example report", list(names))
        if st.button("Load example", type="primary"):
            st.session_state["report"] = json.loads(names[choice].read_text())
            st.success("Loaded. Open Overview in the sidebar.")
        return
    up = st.file_uploader(
        "Upload a script (txt, fountain, fdx, docx, pdf, png, jpg)",
        type=["txt", "fountain", "fdx", "docx", "pdf", "png", "jpg", "jpeg", "md"],
    )
    pasted = st.text_area(
        "...or paste the script",
        height=180,
        placeholder="Title: The Last Message\nRIYA: Why now?\nARJUN: Because today I learned the truth.",
    )
    c1, c2 = st.columns(2)
    feats = c1.multiselect("Features", FEATURES, default=FEATURES)
    targets = c2.multiselect("Localization targets (empty = default rule)", LANGS, default=[])
    if st.button("Analyze", type="primary", disabled=not (up or pasted.strip())):
        opts = {"features": feats, "localization_targets": targets or None}
        try:
            if up is not None:
                resp = httpx.post(
                    f"{API}/v1/jobs",
                    headers=headers(),
                    files={"file": (up.name, up.getvalue())},
                    data={"options": json.dumps(opts)},
                    timeout=60,
                )
            else:
                resp = httpx.post(
                    f"{API}/v1/jobs", headers=headers(), json={"text": pasted, "options": opts}, timeout=60
                )
        except httpx.HTTPError as exc:
            st.error(f"API not reachable at {API}: {type(exc).__name__}")
            return
        if resp.status_code >= 400:
            st.error(f"{resp.status_code}: {resp.json().get('detail')}")
            return
        body = resp.json()
        st.session_state["doc_id"] = body["doc_id"]
        if body.get("cached"):
            load_report(body["report_url"])
            st.success("Cached report loaded.")
            return
        stream_job(body["job_id"])


def stream_job(job_id: str) -> None:
    box = st.status(f"Job {job_id}: running on the local model", expanded=True)
    bar = st.progress(0.0)
    seen = 0
    with httpx.stream("GET", f"{API}/v1/jobs/{job_id}/events", headers=headers(), timeout=None) as resp:
        event = ""
        for raw in resp.iter_lines():
            if raw.startswith("event:"):
                event = raw[6:].strip()
            elif raw.startswith("data:"):
                data = json.loads(raw[5:])
                if event == "stage":
                    mark = {"started": "...", "done": "done", "failed": "FAILED"}.get(
                        data["status"], data["status"]
                    )
                    if data["status"] != "started":
                        box.write(f"{data['name']}: {mark} ({data['elapsed_ms'] / 1000:.1f}s)")
                        seen += 1
                        bar.progress(min(0.97, seen / 22))
                elif event == "done":
                    box.update(label="Analysis complete", state="complete")
                    bar.progress(1.0)
                    load_report(data["report_url"])
                    st.success("Done. Open Overview in the sidebar.")
                    return
                elif event == "error":
                    box.update(label=f"Failed: {data['message']}", state="error")
                    return


def load_report(url: str) -> None:
    r = httpx.get(f"{API}{url}", headers=headers(), timeout=60)
    r.raise_for_status()
    st.session_state["report"] = r.json()


# ---------------------------------------------------------------------------------------------
def page_overview(r: dict[str, Any]) -> None:
    st.header(r.get("title") or "Report")
    e, rt, m = r["engagement"], r["rating"], r["meta"]
    c = st.columns(4)
    c[0].metric(
        "Engagement",
        f"{e['overall']}/10" if e.get("overall") is not None else "n/a",
        help="Code-computed from rubric scores: 10 x sum(w x (s-1)/4)",
    )
    c[1].metric(
        "Confidence",
        f"{e['confidence']:.2f}" if e.get("confidence") is not None else "n/a",
        help="1 - mean run-to-run spread / 4",
    )
    c[2].metric("Age rating (estimate)", rt.get("rating") or "n/a")
    c[3].metric(
        "Latency",
        f"{m['total_latency_ms'] / 1000:.0f}s",
        help=f"{m['tokens'].get('calls', 0)} local model calls, cost $0.00",
    )
    st.subheader("Summary")
    st.write(r["summary"].get("text") or "_unavailable_")
    if rt.get("descriptors"):
        st.markdown(
            " ".join(f"<span class='badge'>{html.escape(d)}</span>" for d in rt["descriptors"]),
            unsafe_allow_html=True,
        )
    left, right = st.columns([3, 2])
    if e.get("factors"):
        left.plotly_chart(charts.factor_radar(e["factors"]))
    with right:
        cl = r["cliffhanger"]
        if cl.get("line_id"):
            st.subheader("Cliffhanger moment")
            st.markdown(f"> **{cl['line_id']}**: {html.escape(cl['quote'])}")
            st.caption(f"{cl['technique']}, strength {cl['strength']}/5")
            st.write(cl["why_it_works"])
    st.subheader("Engagement factors")
    if e.get("factors"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "factor": f["name"],
                        "weight": f["weight"],
                        "score": f["score"],
                        "runs": str(f["run_scores"]),
                        "evidence": ids(f["evidence_line_ids"]),
                        "rationale": f["rationale"],
                    }
                    for f in e["factors"]
                ]
            ),
            hide_index=True,
        )
    st.subheader("Top suggestions")
    for s in r["suggestions"].get("items", [])[:3]:
        with st.container(border=True):
            st.markdown(
                f"**{s['id']} [{s['impact']}] {s['category']}** at {ids(s['target_line_ids'])} (improves {s['linked_factor']})"
            )
            st.write(f"Issue: {s['issue']}")
            st.write(f"Fix: {s['fix']}")
            st.code(s["example_rewrite"], language=None)
    with st.expander("All suggestions"):
        for s in r["suggestions"].get("items", [])[3:]:
            st.markdown(
                f"**{s['id']} [{s['impact']}] {s['category']}** at {ids(s['target_line_ids'])}: {s['issue']} Fix: {s['fix']}"
            )
            st.code(s["example_rewrite"], language=None)
    status_note(r["summary"])


def page_story(r: dict[str, Any]) -> None:
    st.header("Story and emotion")
    sm, em = r["story_map"], r["emotion"]
    if sm.get("logline"):
        st.markdown(f"**Logline:** {sm['logline']}")
        if sm.get("central_conflict"):
            st.markdown(
                f"**Conflict:** {sm['central_conflict']['text']} ({ids(sm['central_conflict']['line_ids'])})"
            )
        if sm.get("stakes"):
            st.markdown(f"**Stakes:** {sm['stakes']['text']} ({ids(sm['stakes']['line_ids'])})")
        st.dataframe(pd.DataFrame(sm.get("characters", [])), hide_index=True)
    if em.get("arc"):
        st.markdown(f"**Arc shape:** {em.get('arc_shape')}. {em.get('narrative')}")
        c1, c2 = st.columns([3, 1])
        c1.plotly_chart(charts.valence_arc(em["arc"]))
        c2.plotly_chart(charts.dominant_bars(em["dominant"]))
    eps = r["episodes"].get("items", [])
    if eps:
        st.plotly_chart(charts.tension_line(eps))
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "episode": x["number"],
                        "summary": x["one_line_summary"],
                        "ending hook": x["ending_hook_strength"],
                        "ending lines": ids(x["ending_line_ids"]),
                        "why": x["ending_rationale"],
                    }
                    for x in eps
                ]
            ),
            hide_index=True,
        )
    a = r["analytics"]
    if a.get("dialogue_share"):
        st.subheader("Script analytics (rule-based estimates)")
        c = st.columns(3)
        c[0].metric("Runtime (word-based)", f"{a['runtime_s_total'].get('word_based', 0):.0f}s")
        c[1].metric("Runtime (page-based)", f"{a['runtime_s_total'].get('page_based', 0):.0f}s")
        c[2].metric(
            "Time to first conflict",
            f"{a['time_to_first_conflict_s']:.0f}s"
            if a.get("time_to_first_conflict_s") is not None
            else "n/a",
        )
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame(a["dialogue_share"]), hide_index=True)
        shares = {d["speaker"]: d["share"] for d in a["dialogue_share"]}
        c2.plotly_chart(charts.network(a["network_nodes"], a["network_edges"], shares))
    if r["continuity"].get("issues"):
        st.subheader("Continuity issues")
        st.dataframe(pd.DataFrame(r["continuity"]["issues"]), hide_index=True)


def findings_index(r: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cl = r["cliffhanger"]
    if cl.get("line_id"):
        out[f"Cliffhanger: {cl['technique']}"] = [cl["line_id"]]
    for f in r["engagement"].get("factors", []):
        out[f"Factor {f['name']} ({f['score']}/5)"] = f["evidence_line_ids"]
    for s in r["suggestions"].get("items", []):
        out[f"Suggestion {s['id']}: {s['category']}"] = s["target_line_ids"]
    for i, f in enumerate(r["rating"].get("findings", [])):
        out[f"Rating {i + 1}: {f['category']} {f['severity']}"] = f["line_ids"]
    for n in r["rating"].get("notices", []):
        out[f"Notice {n['rule_id']}"] = n["trigger_line_ids"]
    for t in r["localization"].get("targets", []):
        for i, iss in enumerate(t.get("issues", [])):
            out[f"Localization {t['lang']} {i + 1}: {iss['type']}"] = iss["line_ids"]
    for i, c in enumerate(r["continuity"].get("issues", [])):
        out[f"Continuity {i + 1}: {c['type']}"] = c["line_ids"]
    for t in r["market"].get("tropes", []):
        out[f"Trope {t['name']}"] = t["line_ids"]
    return out


def page_viewer(r: dict[str, Any]) -> None:
    st.header("Script viewer")
    idx = findings_index(r)
    choice = st.selectbox("Highlight a finding", ["(none)"] + list(idx))
    hl = set(idx.get(choice, []))
    elements = r.get("elements", [])
    pages = sorted({e["page"] for e in elements if e.get("page")})
    if pages and any(e.get("bbox") for e in elements):
        default = next((e["page"] for e in elements if e["id"] in hl and e.get("page")), pages[0])
        page = st.selectbox("Page", pages, index=pages.index(default))
        img = page_image(r["doc_id"], page)
        if img is not None:
            st.image(
                overlay(img, [e for e in elements if e.get("page") == page and e.get("bbox")], hl),
                caption=f"Page {page}: highlighted lines boxed",
            )
    rows: list[str] = []
    for e in elements:
        cls = "line hl" if e["id"] in hl else "line"
        body = (
            f"<span class='spk'>{html.escape(e['speaker'])}:</span> {html.escape(e['text'])}"
            if e.get("speaker") and e["kind"] == "dialogue"
            else f"<span class='kind'>{e['kind']}</span>{html.escape(e['text'])}"
        )
        rows.append(f"<div class='{cls}'><span class='lid'>{e['id']}</span>{body}</div>")
    st.markdown("\n".join(rows), unsafe_allow_html=True)


def page_image(doc_id: str, page: int) -> bytes | None:
    local = EXAMPLES / "pages" / f"{doc_id}_{page}.png"
    if local.exists():
        return local.read_bytes()
    if st.session_state.get("demo"):
        return None
    try:
        resp = httpx.get(f"{API}/v1/documents/{doc_id}/pages/{page}.png", headers=headers(), timeout=60)
        return resp.content if resp.status_code == 200 else None
    except httpx.HTTPError:
        return None


def overlay(png: bytes, elements: list[dict[str, Any]], hl: set[str]) -> bytes:
    from PIL import Image, ImageDraw

    from bsa.ingest.pdf import RENDER_SCALE

    img = Image.open(io.BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for e in elements:
        x0, y0, x1, y1 = (v * RENDER_SCALE for v in e["bbox"])
        hit = e["id"] in hl
        draw.rectangle(
            [x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline="#e81a3b" if hit else "#c9d1d8", width=4 if hit else 1
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def page_alternatives(r: dict[str, Any]) -> None:
    st.header("Alternative openings and endings")
    st.caption(
        "Judged blind by the same local model with swapped order; a win needs both orders. Same-family judging can favour model-written text, so A/B test with real viewers before production."
    )
    status_note(r["alternatives"])
    by_id = {e["id"]: e for e in r.get("elements", [])}
    for t in r["alternatives"].get("targets", []):
        st.subheader(f"{t['kind'].replace('_', ' ').title()} (episode {t['episode']}), factor {t['factor']}")
        orig = [by_id[i] for i in t["replaces_line_ids"] if i in by_id]
        if t.get("dropped"):
            st.caption("Dropped for breaking a hard constraint: " + "; ".join(t["dropped"]))
        for v in t["variants"]:
            badge = {"win": "green", "tie": "blue", "loss": ""}.get(v.get("pairwise") or "", "")
            delta = v.get("delta")
            st.markdown(
                f"<span class='badge {badge}'>{v.get('pairwise')}</span><span class='badge'>{v['strategy']}</span>"
                f"<span class='badge'>{t['factor']} {v.get('score_before')} to {v.get('score_after')} ({'+' if (delta or 0) >= 0 else ''}{delta})</span>"
                f"<span class='badge'>language {'ok' if v.get('language_preserved') else 'changed'}</span><span class='badge'>length {'ok' if v.get('length_ok') else 'off'}</span>",
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            c1.markdown("**Original**")
            c1.code(
                "\n".join(f"{e['speaker']}: {e['text']}" if e.get("speaker") else e["text"] for e in orig),
                language=None,
            )
            c2.markdown(f"**Variant {v['id']}**")
            c2.code(
                "\n".join(
                    f"{e['speaker']}: {e['text']}" if e.get("speaker") else e["text"] for e in v["elements"]
                ),
                language=None,
            )
            st.caption(f"Why: {v['rationale']}  Pays off: {ids(v.get('pays_off_line_ids', []))}")


def page_rating(r: dict[str, Any]) -> None:
    rt = r["rating"]
    st.header(f"Age rating estimate: {rt.get('rating') or 'n/a'}")
    st.warning(rt.get("disclaimer", ""))
    status_note(rt)
    if rt.get("descriptors"):
        st.markdown("**Descriptors:** " + ", ".join(rt["descriptors"]))
    if rt.get("access_controls"):
        st.markdown("**Access controls:** " + ", ".join(rt["access_controls"]))
    if rt.get("findings"):
        rows = [
            {
                "driver": i in rt.get("rating_drivers", []),
                **{k: f[k] for k in ("category", "severity", "mode", "treatment", "substance", "band")},
                "lines": ids(f["line_ids"]),
                "rationale": f["rationale"],
            }
            for i, f in enumerate(rt["findings"])
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    for n in rt.get("notices", []):
        with st.container(border=True):
            st.markdown(
                f"**Statutory notice: {n['rule_id']}** (scenes {ids(n['trigger_scenes'])}, lines {ids(n['trigger_line_ids'])})"
            )
            for t in n["required_text"]:
                st.markdown(f"> {html.escape(t)}")
            for q in n.get("requirements", []):
                st.markdown(f"- {q}")
            st.caption(f"Placement: {n['placement']}  Source: {n['source']}")
    if rt.get("legal_risk_flags"):
        st.subheader("Flags for legal review (not determinations)")
        st.dataframe(pd.DataFrame(rt["legal_risk_flags"]), hide_index=True)
    if rt.get("lower_rating_edits"):
        st.subheader(f"Edits that would lower the rating to {rt.get('lower_rating_band')}")
        for x in rt["lower_rating_edits"]:
            st.markdown(f"- **{x['driver']}** at {ids(x['line_ids'])}: {x['edit']}")
            st.code(x["rewrite"], language=None)


def page_localization(r: dict[str, Any]) -> None:
    lo = r["localization"]
    st.header("Localization fit")
    st.warning(lo.get("disclaimer", ""))
    st.caption(f"Source languages: {lo.get('source_languages')}; code-mix ratio: {lo.get('code_mix_ratio')}")
    targets = lo.get("targets", [])
    if not targets:
        status_note(lo)
        return
    cols = st.columns(len(targets))
    for c, t in zip(cols, targets, strict=False):
        c.metric(f"{t['lang']} fit", f"{t.get('fit_score')}/5" if t.get("fit_score") else "n/a")
        c.caption(t.get("fit_rationale", ""))
    for t in targets:
        st.subheader(f"{t['lang']}")
        if t.get("issues"):
            st.dataframe(
                pd.DataFrame([{**i, "line_ids": ids(i["line_ids"])} for i in t["issues"]]), hide_index=True
            )
        for x in t.get("transcreations", []):
            with st.container(border=True):
                st.markdown(f"**{x['line_id']}** {html.escape(x['source_text'])}")
                st.markdown(f"**{t['lang']}:** {html.escape(x['target_text'])}")
                st.caption(f"Back-translation: {x['back_translation']}. {x['notes']}")
                for fl in x.get("subtitle_flags", []):
                    st.caption(f"Subtitle: {fl}")


def page_market(r: dict[str, Any]) -> None:
    m = r["market"]
    st.header("Market")
    status_note(m)
    if m.get("originality_flag"):
        st.error(f"Originality flag: {m.get('originality_note')}")
    if m.get("tropes"):
        st.subheader("Tropes")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "trope": t["name"],
                        "momentum": t["momentum"] + (" (stale)" if t.get("stale") else ""),
                        "as of": t.get("as_of"),
                        "lines": ids(t["line_ids"]),
                        "why": t["rationale"],
                    }
                    for t in m["tropes"]
                ]
            ),
            hide_index=True,
        )
    if m.get("comps"):
        st.subheader("Similar titles (comps)")
        st.dataframe(pd.DataFrame(m["comps"]), hide_index=True)
        st.caption(
            "Plots from Wikipedia (CC BY-SA 4.0, linked). IMDb rating (non-commercial dataset, demo only)."
        )


def page_raw(r: dict[str, Any]) -> None:
    st.header("Raw report and meta")
    m = r["meta"]
    st.markdown(
        f"Knowledge version `{m['knowledge_version']}`; tokens {m['tokens']}; cost ${m['cost_usd']:.2f} (local model)"
    )
    st.dataframe(pd.DataFrame(m["calls"]), hide_index=True)
    st.json(m.get("prompt_versions", {}))
    st.download_button(
        "Download JSON",
        json.dumps(r, ensure_ascii=False, indent=2),
        file_name=f"{r.get('cache_key', 'report')}.json",
    )
    with st.expander("Full JSON"):
        st.json(r)


PAGES = {
    "Analyze": None,
    "Overview": page_overview,
    "Story and emotion": page_story,
    "Script viewer": page_viewer,
    "Alternatives": page_alternatives,
    "Rating and compliance": page_rating,
    "Localization": page_localization,
    "Market": page_market,
    "Raw": page_raw,
}

with st.sidebar:
    st.title("Script Analyzer")
    st.caption("Open-source models on the local GPU. Insights are editorial opinions grounded in line IDs.")
    st.session_state["demo"] = st.toggle(
        "Demo mode (no API needed)", value=st.session_state.get("demo", not get_secrets().bsa_api_key)
    )
    page = st.radio("Page", list(PAGES))
    if report():
        st.caption(f"Loaded: {report().get('title')}")  # type: ignore[union-attr]

if page == "Analyze":
    page_analyze()
elif report() is None:
    st.info("Analyze a script or load an example first (Analyze page).")
else:
    PAGES[page](report())  # type: ignore[misc]
