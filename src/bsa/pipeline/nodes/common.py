"""Helpers shared by nodes."""

from bsa.domain.ir import ScriptIR

LANG_LABEL = {
    "en": "English",
    "hi": "Hindi in Devanagari script",
    "hi-Latn": "Hinglish (romanized Hindi mixed with English)",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "mr": "Marathi",
}
LANG_NAME = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "bn": "Bengali", "mr": "Marathi"}


def lang_label(ir: ScriptIR) -> str:
    return LANG_LABEL.get(ir.primary_lang, ir.primary_lang)


def id_range(ir: ScriptIR, start: str, end: str) -> list[str]:
    ids = [e.id for e in ir.elements]
    if start not in ir.by_id or end not in ir.by_id:
        return [i for i in (start, end) if i in ir.by_id]
    a, b = ids.index(start), ids.index(end)
    if a > b:
        a, b = b, a
    return ids[a : b + 1]


def opening_line(ir: ScriptIR) -> str | None:
    for e in ir.elements:
        if e.kind in ("dialogue", "action"):
            return e.id
    return None
