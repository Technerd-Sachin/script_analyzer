"""Rule parsers for plain text (the brief's format and screenplay style), Fountain, FDX and DOCX."""

import io
import re
import xml.etree.ElementTree as ET

from bsa.domain.enums import ElementKind
from bsa.ingest.types import RawLine

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_IND = "ऀ-෿"  # Devanagari through Sinhala: Indic letters and combining marks
EPISODE_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:EPISODE|Episode|episode|EP\.?|Ep\.?|एपिसोड|भाग|ഭാഗം)\s*([0-9०-९]+)\b\s*[:.\-–]?\s*(.*)$"
)
HEADING_RE = re.compile(r"^\s*(?:INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.|EXT\.|EST\.)\s*[A-Z\u0900-\u097f]")
HEADING_LOCAL_RE = re.compile(rf"^\s*(?:दृश्य|सीन)\s*[0-9०-९]*\s*[-:–]?\s*[\w{_IND}]")
BARE_SCENE_RE = re.compile(r"^\s*(?:SCENE|Scene)\s*[0-9]*\s*[:.]?\s*$")
DIALOGUE_HEADER_RE = re.compile(r"^\s*(?:DIALOGUE|Dialogue|संवाद)\s*:?\s*$")
TRANSITION_RE = re.compile(
    r"^\s*(?:[A-Z][A-Z ]+(?:TO|IN|OUT)\s*:|FADE OUT\.?|FADE IN:?|SMASH CUT:?|> ?.+)\s*$"
)
TITLE_RE = re.compile(r"^\s*Title\s*:\s*(.+)$", re.IGNORECASE)
NAME_CHARS = rf"[A-Za-z{_IND}][A-Za-z{_IND} .'\-]{{0,30}}?"
DIALOGUE_RE = re.compile(
    rf"^\s*({NAME_CHARS})\s*(\((?:V\.O\.|O\.S\.|O\.C\.|CONT'D|CONT’D|VO|OS)\))?\s*:\s*(.+)$"
)
CUE_EXT_RE = re.compile(r"\s*\((?:V\.O\.|O\.S\.|O\.C\.|CONT'D|CONT’D|VO|OS)\)\s*$")
NOT_SPEAKERS = {
    "ON SCREEN",
    "TITLE",
    "NOTE",
    "SUPER",
    "TEXT",
    "CHAT",
    "MESSAGE",
    "CAPTION",
    "LATER",
    "SCENE",
    "DIALOGUE",
    "INSERT",
    "FLASHBACK",
    "MONTAGE",
    "BACK TO",
    "CUT TO",
    "TIME",
    "LOCATION",
    "PLACE",
}


def parse_num(s: str) -> int:
    return int(s.translate(DEVA_DIGITS))


def speaker_name(name: str) -> str:
    name = CUE_EXT_RE.sub("", name).strip()
    return name.upper() if re.search(r"[A-Za-z]", name) else name


def _is_cue(line: str, nxt: str | None) -> bool:
    """Screenplay-style character cue: short all-caps Latin line followed by dialogue."""
    s = CUE_EXT_RE.sub("", line.strip())
    if not s or not nxt or not nxt.strip() or len(s) > 32 or len(s.split()) > 4:
        return False
    if not re.search(r"[A-Z]", s) or s != s.upper() or s.endswith(":") or HEADING_RE.match(s):
        return False
    if TRANSITION_RE.match(s) or s.upper() in NOT_SPEAKERS:
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z .'\-]*", s))


def parse_text(text: str, fountain: bool = False) -> tuple[str | None, list[RawLine]]:
    """Parse plain text / Fountain into raw lines. Returns (title, lines)."""
    if fountain:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        text = re.sub(r"\[\[.*?\]\]", "", text, flags=re.DOTALL)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title: str | None = None
    out: list[RawLine] = []
    speaker: str | None = None  # active cue for screenplay-style dialogue blocks
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        i += 1
        if not stripped:
            speaker = None
            continue
        if fountain and stripped.startswith("="):
            continue
        m = TITLE_RE.match(stripped)
        if m and title is None and not out:
            title = m.group(1).strip()
            continue
        if DIALOGUE_HEADER_RE.match(stripped):
            continue
        m = EPISODE_RE.match(stripped)
        if m:
            out.append(
                RawLine("episode_marker", stripped.lstrip("# ").strip(), episode_no=parse_num(m.group(1)))
            )
            speaker = None
            continue
        if fountain and stripped.startswith("#"):
            continue  # other sections
        if HEADING_RE.match(stripped) or HEADING_LOCAL_RE.match(stripped) or BARE_SCENE_RE.match(stripped):
            out.append(RawLine("scene_heading", stripped))
            speaker = None
            continue
        if fountain and stripped.startswith(".") and not stripped.startswith(".."):
            out.append(RawLine("scene_heading", stripped[1:].strip()))
            continue
        if TRANSITION_RE.match(stripped) and stripped == stripped.upper():
            out.append(RawLine("transition", stripped.lstrip("> ").strip()))
            speaker = None
            continue
        if stripped.startswith("(") and stripped.endswith(")"):
            out.append(RawLine("parenthetical", stripped, speaker=speaker or _last_speaker(out)))
            continue
        if speaker is not None:
            out.append(RawLine("dialogue", stripped, speaker=speaker))
            continue
        if _is_cue(stripped, nxt):
            speaker = speaker_name(stripped.lstrip("@"))
            continue
        m = DIALOGUE_RE.match(stripped)
        if m and speaker_name(m.group(1)).upper() not in NOT_SPEAKERS and len(m.group(1).split()) <= 4:
            out.append(RawLine("dialogue", m.group(3).strip(), speaker=speaker_name(m.group(1))))
            continue
        out.append(RawLine("action", stripped))
    return title, out


def _last_speaker(out: list[RawLine]) -> str | None:
    for r in reversed(out[-3:]):
        if r.kind == "dialogue":
            return r.speaker
    return None


FDX_KIND: dict[str, ElementKind] = {
    "Scene Heading": "scene_heading",
    "Action": "action",
    "Dialogue": "dialogue",
    "Parenthetical": "parenthetical",
    "Transition": "transition",
    "Shot": "action",
    "General": "action",
}


def parse_fdx(data: bytes) -> tuple[str | None, list[RawLine]]:
    root = ET.fromstring(data)
    out: list[RawLine] = []
    speaker: str | None = None
    for p in root.iter("Paragraph"):
        ptype = p.get("Type", "Action")
        text = "".join(t.text or "" for t in p.iter("Text")).strip()
        if not text:
            continue
        m = EPISODE_RE.match(text)
        if m:
            out.append(RawLine("episode_marker", text, episode_no=parse_num(m.group(1))))
            continue
        if ptype == "Character":
            speaker = speaker_name(text)
            continue
        kind = FDX_KIND.get(ptype, "action")
        out.append(RawLine(kind, text, speaker=speaker if kind in ("dialogue", "parenthetical") else None))
        if kind not in ("dialogue", "parenthetical"):
            speaker = None
    title = None
    for tp in root.iter("TitlePage"):
        texts = ["".join(t.text or "" for t in p.iter("Text")).strip() for p in tp.iter("Paragraph")]
        title = next((t for t in texts if t), None)
    return title, out


def parse_docx(data: bytes) -> tuple[str | None, list[RawLine]]:
    """One paragraph per block; a cue paragraph keeps the next paragraph as its dialogue."""
    from docx import Document

    paras = [p.text for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]
    lines: list[str] = []
    for i, text in enumerate(paras):
        lines.append(text)
        if not _is_cue(text, paras[i + 1] if i + 1 < len(paras) else None):
            lines.append("")
    return parse_text("\n".join(lines))
