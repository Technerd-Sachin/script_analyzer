"""Deterministic script rendering for prompts: the same IR always gives the same bytes."""

import re

from bsa.domain.ir import Element, ScriptIR

KIND_TAG = {
    "action": "action",
    "scene_heading": "heading",
    "transition": "transition",
    "episode_marker": "marker",
    "parenthetical": "parenthetical",
    "other": "other",
}
_DEVA = re.compile(r"[ऀ-෿]")


def estimate_tokens(text: str) -> int:
    """Qwen tokenizer estimate: about 3.6 chars per token for Latin, 1.3 for Indic scripts."""
    indic = len(_DEVA.findall(text))
    return int((len(text) - indic) / 3.6 + indic / 1.3) + 1


def render_element(e: Element, max_action: int | None = None) -> str:
    if e.kind == "dialogue":
        return f"{e.id} {e.speaker or 'UNKNOWN'}: {e.text}"
    text = e.text
    if max_action and e.kind == "action" and len(text) > max_action:
        text = text[:max_action].rstrip() + "..."
    return f"{e.id} ({KIND_TAG.get(e.kind, e.kind)}) {text}"


def _header(ir: ScriptIR) -> str:
    langs = ",".join(f"{k}:{v:.2f}" for k, v in ir.languages.items())
    title = (ir.title or "").replace('"', "'")
    return (
        f'<script id="{ir.doc_id[:12]}" title="{title}" pages="{ir.pages}" '
        f'episodes="{len(ir.episodes)}" languages="{langs}">'
    )


def render_elements(ir: ScriptIR, elements: list[Element], max_action: int | None = None) -> str:
    out = [_header(ir)]
    ep = None
    scene = None
    for e in elements:
        if e.episode != ep:
            ep = e.episode
            out.append(f"## EPISODE {ep}")
        if e.scene_id != scene:
            scene = e.scene_id
            out.append(f"### {scene}")
        out.append(render_element(e, max_action))
    out.append("</script>")
    return "\n".join(out)


def render_script(ir: ScriptIR, budget: int | None = None) -> tuple[str, str]:
    """Return (text, mode). Mode is full, condensed (long action lines shortened) or truncated."""
    full = render_elements(ir, ir.elements)
    if budget is None or estimate_tokens(full) <= budget:
        return full, "full"
    condensed = render_elements(ir, ir.elements, max_action=90)
    if estimate_tokens(condensed) <= budget:
        return condensed, "condensed"
    # keep the opening and the ending (hook and cliffhanger live there); drop from the middle
    kept = [e for e in ir.elements if e.kind != "parenthetical"]
    while len(kept) > 20 and estimate_tokens(render_elements(ir, kept, max_action=60)) > budget:
        mid, cut = len(kept) // 2, max(1, len(kept) // 20)
        kept = kept[: mid - cut] + kept[mid + cut :]
    return render_elements(ir, kept, max_action=60), "truncated"
