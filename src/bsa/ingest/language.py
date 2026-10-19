"""Script and language detection per element, Hinglish flagging and code-mix ratio."""

import re
from collections import Counter
from functools import lru_cache

from bsa.config import ROOT
from bsa.domain.enums import LangCode
from bsa.domain.ir import Element

BLOCKS: list[tuple[LangCode, int, int]] = [
    ("hi", 0x0900, 0x097F),  # Devanagari (Hindi or Marathi; story_map confirms)
    ("bn", 0x0980, 0x09FF),
    ("ta", 0x0B80, 0x0BFF),
    ("te", 0x0C00, 0x0C7F),
]
TOKEN_RE = re.compile(r"[A-Za-z']+|[ऀ-෿]+")
HINGLISH_THRESHOLD = 0.15


@lru_cache
def _lexicon(name: str) -> frozenset[str]:
    path = ROOT / "knowledge" / "lexicons" / name
    if not path.exists():
        return frozenset()
    words = (ln.split("\t")[-1].strip().lower() for ln in path.read_text(encoding="utf-8").splitlines())
    return frozenset(w for w in words if w and not w.startswith("#"))


def hinglish_markers() -> frozenset[str]:
    return _lexicon("hinglish_markers.txt")


def english_common() -> frozenset[str]:
    return _lexicon("english_common.txt")


def script_of(text: str) -> LangCode | None:
    counts: Counter[str] = Counter()
    for ch in text:
        o = ord(ch)
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            counts["latin"] += 1
            continue
        for code, lo, hi in BLOCKS:
            if lo <= o <= hi:
                counts[code] += 1
                break
    if not counts:
        return None
    top = counts.most_common(1)[0][0]
    return "en" if top == "latin" else top  # type: ignore[return-value]


def detect_lang(text: str) -> LangCode | None:
    lang = script_of(text)
    if lang != "en":
        return lang
    tokens = [t.lower() for t in TOKEN_RE.findall(text)]
    if not tokens:
        return "en"
    markers = hinglish_markers()
    share = sum(t in markers for t in tokens) / len(tokens)
    return "hi-Latn" if share >= HINGLISH_THRESHOLD else "en"


def tag_languages(elements: list[Element]) -> dict[str, float]:
    """Set Element.lang and return the share of characters per language (dialogue + action)."""
    chars: Counter[str] = Counter()
    for e in elements:
        e.lang = detect_lang(e.text)
        if e.kind in ("dialogue", "action") and e.lang:
            chars[e.lang] += len(e.text)
    # a short English line inside a Hinglish script is usually Hinglish too; keep the per-line tags
    total = sum(chars.values()) or 1
    return {k: round(v / total, 3) for k, v in sorted(chars.items(), key=lambda kv: -kv[1])}


def code_mix_ratio(elements: list[Element]) -> float | None:
    """Share of English tokens inside Hindi or Hinglish dialogue (estimate)."""
    eng = english_common()
    markers = hinglish_markers()
    english = total = 0
    for e in elements:
        if e.kind != "dialogue" or e.lang not in ("hi", "hi-Latn"):
            continue
        for tok in TOKEN_RE.findall(e.text):
            t = tok.lower()
            total += 1
            if e.lang == "hi":
                english += bool(re.match(r"[a-z]", t))
            else:
                english += t in eng and t not in markers
    return round(english / total, 3) if total else None
