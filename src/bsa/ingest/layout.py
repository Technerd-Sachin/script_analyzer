"""Layout classifier: screenplay elements from line geometry first; LLM restructuring only as a fallback."""

import re
import statistics
from collections import Counter
from typing import TYPE_CHECKING

from bsa.ingest.text_formats import (
    BARE_SCENE_RE,
    CUE_EXT_RE,
    DIALOGUE_RE,
    EPISODE_RE,
    HEADING_LOCAL_RE,
    HEADING_RE,
    NOT_SPEAKERS,
    TRANSITION_RE,
    parse_num,
    speaker_name,
)
from bsa.ingest.types import PageLine, RawLine

if TYPE_CHECKING:
    from bsa.config import Config

PAGE_NO = re.compile(
    r"^\s*(?:page\s*)?\d{1,3}\s*\.?\s*$|^\s*\(?CONTINUED\)?:?\s*$|^\s*\(?MORE\)?\s*$", re.IGNORECASE
)
_LATIN = re.compile(r"[A-Za-z]")
_ALNUM = re.compile(r"[A-Za-z0-9\u0900-\u0dff]")
_CAPS_TOKEN = re.compile(r"(?<![A-Za-z])(?=[A-Za-z]*[A-Z]{2})[A-Z]*[ol][A-Z]+(?![a-z])")


def fix_caps(text: str) -> str:
    """OCR often reads O as o and I as l inside all-caps words (RATHoRE, EPISoDE)."""
    return _CAPS_TOKEN.sub(lambda m: m.group(0).replace("o", "O").replace("l", "I"), text)


def is_junk(ln: PageLine) -> bool:
    return not _ALNUM.search(ln.text) or ((ln.x1 - ln.x0) < 6 and (ln.bottom - ln.top) < 6)


_INDIC = re.compile(r"[ऀ-෿]")


def _is_caps_cue(text: str) -> bool:
    s = CUE_EXT_RE.sub("", text).strip()
    if not s or len(s) > 32 or len(s.split()) > 4 or s.endswith(":") or s.upper() in NOT_SPEAKERS:
        return False
    if _LATIN.search(s):
        return s == s.upper() and bool(re.fullmatch(r"[A-Z][A-Z .'\-]*", s))
    return bool(_INDIC.search(s))


def classify(lines: list[PageLine], widths: dict[int, float]) -> tuple[str | None, list[RawLine], float]:
    """Return (title, raw lines, share of lines matched by a confident rule)."""
    lines = [ln for ln in lines if ln.text.strip() and not PAGE_NO.match(ln.text) and not is_junk(ln)]
    for ln in lines:
        ln.text = fix_caps(ln.text.strip())
    if not lines:
        return None, [], 0.0
    margins: dict[int, float] = {}
    for p in {ln.page for ln in lines}:
        xs = sorted(ln.x0 for ln in lines if ln.page == p)
        margins[p] = xs[max(0, int(len(xs) * 0.05))]
    heights = [ln.bottom - ln.top for ln in lines if ln.bottom > ln.top]
    line_h = statistics.median(heights) if heights else 12.0
    cue_counts = Counter(
        ln.text.strip()
        for ln in lines
        if (ln.x0 - margins[ln.page]) / 72 >= 1.8 and len(ln.text.split()) <= 4
    )

    title: str | None = None
    first = lines[0]
    if (
        first.page == 1
        and first.text.isupper()
        and len(first.text.split()) <= 6
        and not HEADING_RE.match(first.text)
        and not EPISODE_RE.match(first.text)
    ):
        title = first.text.strip().title()
        lines = lines[1:]

    out: list[tuple[RawLine, PageLine]] = []
    matched = 0
    speaker: str | None = None
    for ln in lines:
        text = ln.text.strip()
        rel = (ln.x0 - margins[ln.page]) / 72  # inches from the page's text margin
        width = widths.get(ln.page, 612.0)
        ok = True
        m = EPISODE_RE.match(text)
        if m:
            raw = RawLine("episode_marker", text, episode_no=parse_num(m.group(1)))
            speaker = None
        elif HEADING_RE.match(text) or HEADING_LOCAL_RE.match(text) or BARE_SCENE_RE.match(text):
            raw = RawLine("scene_heading", text)
            speaker = None
        elif TRANSITION_RE.match(text) and text == text.upper() and (ln.x1 > 0.72 * width or rel > 3.5):
            raw = RawLine("transition", text)
            speaker = None
        elif rel >= 1.8 and (_is_caps_cue(text) or (cue_counts[text] >= 2 and len(text.split()) <= 3)):
            speaker = speaker_name(text)
            matched += 1
            continue  # the cue is merged into the following dialogue
        elif (
            text.startswith("(") and (text.endswith(")") or ")" not in text) and speaker and 0.6 <= rel < 2.6
        ):
            raw = RawLine("parenthetical", text, speaker=speaker)
        elif speaker and 0.6 <= rel < 2.6:
            raw = RawLine("dialogue", text, speaker=speaker)
        elif (
            (dm := DIALOGUE_RE.match(text))
            and speaker_name(dm.group(1)).upper() not in NOT_SPEAKERS
            and len(dm.group(1).split()) <= 4
        ):
            raw = RawLine("dialogue", dm.group(3).strip(), speaker=speaker_name(dm.group(1)))
            speaker = None
        else:
            ok = rel < 0.6  # action at the margin is confident; stray indents are not
            raw = RawLine("action", text)
            speaker = None
        matched += ok
        raw.page, raw.bbox, raw.ocr_conf = ln.page, ln.bbox, ln.conf
        out.append((raw, ln))
    return title, merge(out, line_h), matched / max(1, len(lines))


def merge(items: list[tuple[RawLine, PageLine]], line_h: float) -> list[RawLine]:
    """Join wrapped lines of the same element (same kind and speaker, small vertical gap)."""
    merged: list[RawLine] = []
    prev: PageLine | None = None
    for raw, ln in items:
        last = merged[-1] if merged else None
        joinable = (
            last is not None
            and prev is not None
            and last.kind == raw.kind
            and last.speaker == raw.speaker
            and last.page == raw.page
            and raw.kind in ("action", "dialogue", "parenthetical")
            and -0.7 * line_h
            <= ln.top - prev.bottom
            <= 0.5 * line_h  # skewed scans make wrapped lines overlap
            and not (raw.kind == "parenthetical" and last.text.endswith(")"))
            and not (raw.kind == "dialogue" and raw.text.startswith("("))
        )
        if joinable and last is not None and last.bbox and raw.bbox:
            last.text = f"{last.text} {raw.text}"
            last.bbox = (
                min(last.bbox[0], raw.bbox[0]),
                last.bbox[1],
                max(last.bbox[2], raw.bbox[2]),
                raw.bbox[3],
            )
            if raw.ocr_conf is not None and last.ocr_conf is not None:
                last.ocr_conf = min(last.ocr_conf, raw.ocr_conf)
        else:
            merged.append(raw)
        prev = ln
    return merged


def restructure_with_llm(lines: list[PageLine], cfg: "Config") -> list[RawLine] | None:
    """Fallback when the geometric rules match under 60% of lines: the LLM restructures each page.

    Accepted only if the concatenated element text matches the source with normalized similarity >= 0.98;
    otherwise the rule result is kept. Elements produced this way have no bbox.
    """
    import json

    import httpx
    from rapidfuzz import fuzz

    from bsa.domain.llm import LayoutOut
    from bsa.llm.client import ollama_schema, schema_hint
    from bsa.llm.prompts import load_prompt

    out: list[RawLine] = []
    node = cfg.llm.node("layout_fallback")
    for page in sorted({ln.page for ln in lines}):
        src = [ln.text for ln in lines if ln.page == page]
        task = (
            load_prompt("layout_fallback").render()
            + "\n\nReturn compact JSON on a single line matching this schema:\n"
            + schema_hint(LayoutOut)
        )
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": load_prompt("_preamble").render()},
                {"role": "user", "content": "<page>\n" + "\n".join(src) + "\n</page>"},
                {"role": "user", "content": task},
            ],
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "format": ollama_schema(LayoutOut),
            "options": {"temperature": 0.0, "num_predict": node.num_predict, "num_ctx": cfg.llm.num_ctx},
        }
        try:
            r = httpx.post(f"{cfg.llm.base_url}/api/chat", json=payload, timeout=cfg.llm.timeout_s)
            parsed = LayoutOut.model_validate(json.loads(r.json()["message"]["content"]))
        except Exception:  # noqa: BLE001 - fallback is best effort
            return None
        got = " ".join(f"{e.speaker} {e.text}" if e.speaker else e.text for e in parsed.elements)
        if fuzz.ratio(" ".join(" ".join(src).split()).lower(), " ".join(got.split()).lower()) < 98:
            return None
        for e in parsed.elements:
            m = EPISODE_RE.match(e.text)
            out.append(
                RawLine(
                    e.kind,
                    e.text,
                    speaker=e.speaker,
                    page=page,
                    episode_no=parse_num(m.group(1)) if m else None,
                )
            )
    return out
