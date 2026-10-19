"""Rule-based script analytics: runtime, dialogue share, character network, scene stats."""

import re
from collections import Counter

from rapidfuzz.distance import Levenshtein

from bsa.domain.ir import Element, ScriptIR
from bsa.domain.report import Analytics, Edge, SpeakerShare

PAGE_SECONDS = 60
DIALOGUE_WPM = 150
ACTION_WPM = 300


def element_seconds(e: Element) -> float:
    words = len(e.text.split())
    if e.kind == "dialogue":
        return words / DIALOGUE_WPM * 60
    if e.kind == "action":
        return words / ACTION_WPM * 60
    return 0.0


def compute(ir: ScriptIR, first_conflict_line: str | None = None) -> Analytics:
    a = Analytics()
    total_words = sum(len(e.text.split()) for e in ir.elements) or 1
    pages = ir.pages or 1
    for ep in ir.episodes:
        els = ir.episode_elements(ep.number)
        words = sum(len(e.text.split()) for e in els)
        a.runtime_s_by_episode[str(ep.number)] = {
            "page_based": round(pages * PAGE_SECONDS * words / total_words, 1),
            "word_based": round(sum(element_seconds(e) for e in els), 1),
        }
    a.runtime_s_total = {
        "page_based": round(pages * PAGE_SECONDS, 1),
        "word_based": round(sum(element_seconds(e) for e in ir.elements), 1),
    }
    lines: Counter[str] = Counter()
    words_by: Counter[str] = Counter()
    for e in ir.elements:
        if e.kind == "dialogue" and e.speaker:
            lines[e.speaker] += 1
            words_by[e.speaker] += len(e.text.split())
    tw = sum(words_by.values()) or 1
    a.dialogue_share = [
        SpeakerShare(speaker=s, lines=lines[s], words=words_by[s], share=round(words_by[s] / tw, 3))
        for s, _ in words_by.most_common()
    ]
    edges: Counter[tuple[str, str]] = Counter()
    for sc in ir.scenes:
        speakers = [ir.by_id[i].speaker for i in sc.element_ids if ir.by_id[i].kind == "dialogue"]
        seq = [s for s in speakers if s]
        for x, y in zip(seq, seq[1:], strict=False):
            if x != y:
                edges[tuple(sorted((x, y)))] += 1  # type: ignore[index]
        present = sorted(set(seq))
        for i, x in enumerate(present):
            for y in present[i + 1 :]:
                edges[(x, y)] += 1
    a.network_nodes = [s.speaker for s in a.dialogue_share]
    a.network_edges = [Edge(a=x, b=y, weight=w) for (x, y), w in edges.most_common()]
    n_scenes = len(ir.scenes) or 1
    dlg = sum(1 for e in ir.elements if e.kind == "dialogue")
    act = sum(1 for e in ir.elements if e.kind == "action")
    a.scene_stats = {
        "count": float(len(ir.scenes)),
        "avg_lines": round(len(ir.elements) / n_scenes, 1),
        "dialogue_action_ratio": round(dlg / act, 2) if act else float(dlg),
    }
    if first_conflict_line and first_conflict_line in ir.by_id:
        idx = ir.index_of(first_conflict_line)
        a.time_to_first_conflict_s = round(sum(element_seconds(e) for e in ir.elements[:idx]), 1)
    return a


def name_variants(ir: ScriptIR) -> list[list[str]]:
    """Speaker names within edit distance 2 of each other (RIYA / RIA)."""
    names = sorted({e.speaker for e in ir.elements if e.speaker})
    groups: list[list[str]] = []
    for i, x in enumerate(names):
        for y in names[i + 1 :]:
            if Levenshtein.distance(x, y) <= max(1, min(2, min(len(x), len(y)) // 3)):
                groups.append([x, y])
    return groups


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "paanch": 5,
    "chhe": 6,
    "saat": 7,
    "aath": 8,
    "nau": 9,
    "das": 10,
    "बीस": 20,
    "पाँच": 5,
    "तीन": 3,
    "दस": 10,
}
COLOURS = {
    "red",
    "blue",
    "green",
    "yellow",
    "black",
    "white",
    "pink",
    "orange",
    "purple",
    "brown",
    "grey",
    "gray",
    "golden",
    "silver",
    "laal",
    "neela",
    "hara",
    "peela",
    "kaala",
    "safed",
}
_DUR = re.compile(
    r"\b(\d+|[a-z]+|[ऀ-ॿ]+)\s+(years?|months?|weeks?|days?|saal|mahine|din|साल|महीने|दिन)\b", re.IGNORECASE
)
_COLOUR_NOUN = re.compile(rf"\b({'|'.join(sorted(COLOURS))})\s+([a-z]{{3,}})\b", re.IGNORECASE)


def continuity_candidates(ir: ScriptIR) -> list[str]:
    """Concrete contradiction candidates for the model to verify: durations and object colours that disagree."""
    out: list[str] = []
    durations: dict[str, list[tuple[int, str, str]]] = {}
    colours: dict[str, list[tuple[str, str]]] = {}
    for e in ir.elements:
        for num, unit in _DUR.findall(e.text):
            n = int(num) if num.isdigit() else NUMBER_WORDS.get(num.lower())
            if n:
                durations.setdefault(unit.lower().rstrip("s"), []).append((n, e.id, f"{num} {unit}"))
        for colour, noun in _COLOUR_NOUN.findall(e.text):
            if colour.lower() in COLOURS:
                colours.setdefault(noun.lower(), []).append((colour.lower(), e.id))
    for unit, items in durations.items():
        if len({n for n, _, _ in items}) > 1:
            out.append(
                f"timeline: different {unit} durations: " + "; ".join(f"{i} '{t}'" for _, i, t in items[:6])
            )
    for noun, items in colours.items():
        if len({c for c, _ in items}) > 1:
            out.append(f"object: the {noun} changes colour: " + "; ".join(f"{i} {c}" for c, i in items[:6]))
    return out


def name_variant_lines(ir: ScriptIR, a: str, b: str) -> list[str]:
    first = {}
    for e in ir.elements:
        if e.speaker in (a, b) and e.speaker not in first:
            first[e.speaker] = e.id
    return [first[x] for x in (a, b) if x in first]
