"""Assign line IDs, scenes and episodes to parsed lines."""

from bsa.domain.enums import SourceKind
from bsa.domain.ir import Element, Episode, Scene, ScriptIR
from bsa.ingest.types import RawLine

WORDS_PER_PAGE = 180
SINGLE_MAX_PAGES = 3
SINGLE_MAX_WORDS = 2500
HEURISTIC_EPISODE_WORDS = 300  # about 1.5 pages per episode when no markers and no LLM


def count_words(lines: list[RawLine]) -> int:
    return sum(len(r.text.split()) for r in lines)


def build_ir(
    raw: list[RawLine],
    *,
    doc_id: str,
    title: str | None,
    source_kind: SourceKind,
    pages: int | None,
) -> ScriptIR:
    elements: list[Element] = []
    scenes: list[Scene] = []
    episodes: list[Episode] = []
    has_markers = any(r.kind == "episode_marker" for r in raw)
    ep_no = 1
    if has_markers:
        first = next(r for r in raw if r.kind == "episode_marker")
        ep_no = first.episode_no or 1
    episodes.append(Episode(number=ep_no, boundary_source="marker" if has_markers else "single"))
    scene: Scene | None = None
    seen_marker = False

    def new_scene(heading: str | None) -> Scene:
        s = Scene(id=f"S{len(scenes) + 1}", episode=episodes[-1].number, heading=heading)
        scenes.append(s)
        episodes[-1].scene_ids.append(s.id)
        return s

    for r in raw:
        if r.kind == "episode_marker":
            if seen_marker:
                n = r.episode_no or episodes[-1].number + 1
                if n <= episodes[-1].number:
                    n = episodes[-1].number + 1
                episodes.append(Episode(number=n, boundary_source="marker"))
            seen_marker = True  # the first marker keeps any preamble in its episode
            scene = None
        if r.kind == "scene_heading" or scene is None:
            scene = new_scene(r.text if r.kind == "scene_heading" else None)
        el = Element(
            id=f"L{len(elements) + 1}",
            kind=r.kind,
            text=r.text,
            speaker=r.speaker,
            episode=episodes[-1].number,
            scene_id=scene.id,
            page=r.page,
            bbox=r.bbox,
            ocr_conf=r.ocr_conf,
        )
        elements.append(el)
        scene.element_ids.append(el.id)
    words = count_words(raw)
    if pages is None:
        pages = max(1, round(words / WORDS_PER_PAGE))
    return ScriptIR(
        doc_id=doc_id,
        title=title,
        source_kind=source_kind,
        pages=pages,  # type: ignore[arg-type]
        episodes=episodes,
        scenes=scenes,
        elements=elements,
    )


def needs_split(ir: ScriptIR) -> bool:
    words = sum(len(e.text.split()) for e in ir.elements)
    single = len(ir.episodes) == 1 and ir.episodes[0].boundary_source == "single"
    return single and (ir.pages or 0) > SINGLE_MAX_PAGES and words > SINGLE_MAX_WORDS


def apply_boundaries(ir: ScriptIR, start_scene_ids: list[str], source: str) -> ScriptIR:
    """Re-number episodes so each listed scene starts a new episode."""
    starts = {s for s in start_scene_ids if any(sc.id == s for sc in ir.scenes)}
    starts.add(ir.scenes[0].id)
    ep = 0
    episodes: list[Episode] = []
    for sc in ir.scenes:
        if sc.id in starts:
            ep += 1
            episodes.append(Episode(number=ep, boundary_source=source))
        sc.episode = ep
        episodes[-1].scene_ids.append(sc.id)
    scene_ep = {sc.id: sc.episode for sc in ir.scenes}
    for e in ir.elements:
        e.episode = scene_ep[e.scene_id]
    ir.episodes = episodes
    return ir


def heuristic_boundaries(ir: ScriptIR) -> list[str]:
    starts: list[str] = []
    acc = 0
    for sc in ir.scenes:
        if not starts or acc >= HEURISTIC_EPISODE_WORDS:
            starts.append(sc.id)
            acc = 0
        acc += sum(len(ir.by_id[i].text.split()) for i in sc.element_ids)
    return starts
