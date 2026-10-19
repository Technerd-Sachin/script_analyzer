"""Grounding checks on LLM output: line IDs exist, quotes match, plus a cleaner that drops bad items."""

import re
from collections.abc import Callable
from typing import Any

from rapidfuzz import fuzz

LIST_ID_FIELDS = {
    "line_ids",
    "evidence_line_ids",
    "target_line_ids",
    "ending_line_ids",
    "pays_off_line_ids",
}
ONE_ID_FIELDS = {"line_id", "start_line", "end_line", "cliffhanger_candidate_line_id"}
_ID = re.compile(r"^[Ll]?\s*(\d+)$")
_RANGE = re.compile(r"^[Ll]?(\d+)\s*[-–to]+\s*[Ll]?(\d+)$")
_PUNCT = re.compile(r"[^\wऀ-෿ ]+")


def norm_id(raw: str) -> list[str]:
    s = str(raw).strip().strip("[]()'\"")
    m = _ID.match(s)
    if m:
        return [f"L{int(m.group(1))}"]
    m = _RANGE.match(s.replace(" ", ""))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < b - a <= 60:
            return [f"L{i}" for i in range(a, b + 1)]
    return [s]


def normalize(data: Any) -> Any:
    """Normalize ID spellings in place ("l12", "12", "L3-L5") before validation."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k in LIST_ID_FIELDS and isinstance(v, list):
                ids: list[str] = []
                for item in v:
                    for i in norm_id(str(item)):
                        if i not in ids:
                            ids.append(i)
                data[k] = ids
            elif k in ONE_ID_FIELDS and isinstance(v, str) and v:
                data[k] = norm_id(v)[0]
            else:
                normalize(v)
    elif isinstance(data, list):
        for v in data:
            normalize(v)
    return data


def norm_text(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", s.lower()).split())


def quote_matches(quote: str, text: str) -> bool:
    q, t = norm_text(quote), norm_text(text)
    if not q:
        return False
    return q in t or fuzz.partial_ratio(q, t) >= 90


def check_grounding(data: Any, valid_ids: set[str], texts: dict[str, str], path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{path}.{k}" if path else k
            if k in LIST_ID_FIELDS and isinstance(v, list):
                bad = [i for i in v if i not in valid_ids]
                if bad:
                    errors.append(f"{p}: unknown line IDs {bad[:5]}")
            elif k in ONE_ID_FIELDS and isinstance(v, str) and v and v not in valid_ids:
                errors.append(f"{p}: unknown line ID {v!r}")
            else:
                errors.extend(check_grounding(v, valid_ids, texts, p))
        if (
            "quote" in data
            and data.get("line_id") in texts
            and not quote_matches(str(data["quote"]), texts[data["line_id"]])
        ):
            errors.append(f"{path or 'root'}.quote: does not match the text of {data['line_id']} verbatim")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            errors.extend(check_grounding(v, valid_ids, texts, f"{path}[{i}]"))
    return errors


def clean(data: Any, valid_ids: set[str], texts: dict[str, str]) -> tuple[Any, int]:
    """Drop unknown IDs, and drop list items whose evidence becomes empty or invalid. Returns (data, dropped)."""
    dropped = 0
    if isinstance(data, dict):
        for k in list(data.keys()):
            v = data[k]
            if k in LIST_ID_FIELDS and isinstance(v, list):
                keep = [i for i in v if i in valid_ids]
                dropped += len(v) - len(keep)
                data[k] = keep
            elif isinstance(v, (dict, list)):
                data[k], n = clean(v, valid_ids, texts)
                dropped += n
        return data, dropped
    if isinstance(data, list):
        out: list[Any] = []
        for item in data:
            if isinstance(item, dict):
                had_ids = any(len(item[k]) > 0 for k in LIST_ID_FIELDS if isinstance(item.get(k), list))
                item, n = clean(item, valid_ids, texts)
                dropped += n
                if _unsupported(item, valid_ids, texts, had_ids):
                    dropped += 1
                    continue
            out.append(item)
        return out, dropped
    return data, dropped


def _unsupported(item: dict[str, Any], valid_ids: set[str], texts: dict[str, str], had_ids: bool) -> bool:
    """An item is dropped when all its evidence IDs were invalid, its single ID is invalid, or its quote is wrong."""
    lists = [item[k] for k in LIST_ID_FIELDS if k in item]
    if had_ids and lists and all(len(v) == 0 for v in lists):
        return True
    for k in ONE_ID_FIELDS & item.keys():
        if item[k] and item[k] not in valid_ids:
            return True
    return (
        "quote" in item
        and item.get("line_id") in texts
        and not quote_matches(str(item["quote"]), texts[item["line_id"]])
    )


Check = Callable[[Any], list[str]]
