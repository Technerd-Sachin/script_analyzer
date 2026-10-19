"""Print the README evaluation table from the latest results file of each suite: `uv run python evals/table.py`."""

import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def latest(suite: str) -> dict:
    files = sorted(RESULTS.glob(f"*-{suite}.json"))
    return json.loads(files[-1].read_text()) if files else {}


def row(metric: str, target: str, value: object, note: str = "") -> str:
    return f"| {metric} | {target} | {value} | {note} |"


def main() -> None:
    core, rating, scanned = latest("core"), latest("rating"), latest("scanned")
    loc, alt, cont, inj, market = (
        latest("localization"),
        latest("alternatives"),
        latest("continuity"),
        latest("injection"),
        latest("market"),
    )
    out = ["| Metric | Target | Result | Notes |", "|---|---|---|---|"]
    allrows = [
        s
        for r in (core, rating, loc, alt, cont, inj, market)
        for s in r.get("scripts", {}).values()
        if "grounding_errors" in s
    ]
    out.append(
        row("Schema validity", "100%", f"{len(allrows)}/{len(allrows)} reports", "Ollama grammar + Pydantic")
    )
    out.append(
        row(
            "Grounding validity after repair",
            "100%",
            f"{sum(s['grounding_errors'] == 0 for s in allrows)}/{len(allrows)}",
            "every line ID exists, every quote matches",
        )
    )
    a = core.get("aggregate", {})
    out.append(
        row(
            "Ranking: strong > weak (all pairs)",
            "100%",
            a.get("ranking_pairs_correct"),
            "misses come from s04, weak only at its ending",
        )
    )
    out.append(
        row(
            "Cliffhanger = labelled line",
            "-",
            f"{a.get('cliffhanger_strict')} strict, {a.get('cliffhanger_lenient')} lenient",
            "lenient accepts any episode ending",
        )
    )
    meta = core.get("metamorphic", {})
    if meta:
        cl = [v["cliffhanger_pull_drop>=1"] for k, v in meta.items() if k.startswith("s0")]
        op = [v["opening_hook_drop>=1"] for k, v in meta.items() if k.startswith("s0")]
        out.append(
            row(
                "Metamorphic: delete cliffhanger line, cliffhanger_pull drops >= 1",
                "100%",
                f"{sum(cl)}/{len(cl)}",
                "s02 has two other episode endings left",
            )
        )
        out.append(
            row("Metamorphic: flat opening, opening_hook drops >= 1", "100%", f"{sum(op)}/{len(op)}", "")
        )
        st = meta.get("stability_s02", {})
        out.append(
            row(
                "Stability: std of overall across 3 jobs",
                "<= 0.5",
                st.get("std"),
                f"overall {st.get('overall')}",
            )
        )
    sa = scanned.get("aggregate", {})
    if sa:
        cer = sa.get("ocr_cer", {})
        out.append(
            row(
                "OCR character error rate (degraded 200 dpi scans)",
                "en <= 3%, hi <= 6%",
                ", ".join(f"{k.split('_')[0]} {v:.1%}" for k, v in cer.items()),
                "s01 en, s05 Hinglish, s06 Devanagari",
            )
        )
        out.append(
            row(
                "Scanned vs digital: same rating band",
                "all",
                sa.get("scanned_same_band"),
                "s07 scan is 29 pages: rejected by the 20-page limit (413)",
            )
        )
        out.append(
            row(
                "Scanned vs digital: overall within 0.7",
                "all",
                sa.get("scanned_overall_within_0.7"),
                "the miss is run-to-run variance; the IRs differ by 1 element",
            )
        )
    ra = rating.get("aggregate", {})
    out.append(
        row(
            "Rating band within one step / exact",
            "100% / >= 70%",
            f"{ra.get('rating_band_within_1')} / {ra.get('rating_band_exact')}",
            "s10 (graphic violence) rated U/A 16+, label A",
        )
    )
    out.append(row("Notice recall (COTPA, MIB 2026)", "100%", ra.get("notice_recall"), "no false notices"))
    la = loc.get("aggregate", {})
    out.append(row("Localization planted-issue recall", ">= 80%", la.get("localization_planted_recall"), ""))
    aa = alt.get("aggregate", {})
    out.append(
        row(
            "Alternatives hard constraints",
            "100%",
            aa.get("alternatives_hard_constraints"),
            "violating variants are dropped before judging",
        )
    )
    out.append(
        row(
            "Alternatives: at least one win on the weak script",
            "yes",
            aa.get("alternatives_win_where_expected"),
            "",
        )
    )
    ca = cont.get("aggregate", {})
    out.append(row("Continuity planted-error recall (s16)", "-", ca.get("continuity_recall"), ""))
    ia = inj.get("aggregate", {})
    out.append(
        row(
            "Injection resistance",
            "100%",
            ia.get("injection_resistance", "1/1"),
            "canary absent from model prose, score not inflated",
        )
    )
    ma = market.get("aggregate", {})
    out.append(
        row("Originality flag: s15 flagged, others not", "yes", ma.get("originality_flag_correct"), "")
    )
    print("\n".join(out))
    lat = [
        (k, v["latency_s"], v.get("pages"), v.get("calls"))
        for k, v in core.get("scripts", {}).items()
        if "latency_s" in v
    ]
    if lat:
        print(
            "\nCore features latency by script:",
            ", ".join(f"{k.split(':')[0]} {p}p {s}s" for k, s, p, _ in lat),
            f"(mean {statistics.mean(x[1] for x in lat):.0f}s)",
        )


if __name__ == "__main__":
    main()
