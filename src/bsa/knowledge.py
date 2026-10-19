"""Loads the OKF knowledge bundle (Markdown + YAML front matter) and renders prompt snippets."""

import hashlib
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bsa.config import ROOT
from bsa.domain.enums import FACTORS


class Doc(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    path: str = ""
    body: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


class RubricFactor(BaseModel):
    factor: str
    weight: float
    anchors: dict[str, str]
    body: str = ""


class CraftItem(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    example: str = ""


class Trope(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    cues: list[str] = Field(default_factory=list)


def parse_okf(path: Path) -> Doc:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    return Doc.model_validate({**meta, "body": body.strip()})


class Knowledge:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.docs: dict[str, Doc] = {}
        files = sorted(p for p in root.rglob("*") if p.is_file())
        digest = hashlib.sha256()
        for p in files:
            rel = p.relative_to(root).as_posix()
            digest.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
            if p.suffix == ".md":
                doc = parse_okf(p)
                doc.path = rel
                self.docs[rel] = doc
        self.version = digest.hexdigest()[:16]

    def by_type(self, type_: str) -> list[Doc]:
        return [d for d in self.docs.values() if d.type == type_]

    def doc(self, rel: str) -> Doc | None:
        return self.docs.get(rel)

    # ---- rubric -----------------------------------------------------------------------------
    @cached_property
    def rubric(self) -> dict[str, RubricFactor]:
        out: dict[str, RubricFactor] = {}
        for d in self.by_type("rubric_factor"):
            anchors = {str(k): str(v) for k, v in (d.get("anchors") or {}).items()}
            out[str(d.get("factor"))] = RubricFactor(
                factor=str(d.get("factor")), weight=float(d.get("weight", 0)), anchors=anchors, body=d.body
            )
        return {f: out[f] for f in FACTORS if f in out}

    @property
    def weights(self) -> dict[str, float]:
        return {k: v.weight for k, v in self.rubric.items()}

    def rubric_text(self, factors: list[str] | None = None, with_body: bool = True) -> str:
        lines: list[str] = []
        for name, f in self.rubric.items():
            if factors and name not in factors:
                continue
            lines.append(f"### {name} (weight {f.weight:.2f})")
            for k in sorted(f.anchors):
                lines.append(f"- {k}: {f.anchors[k]}")
            if with_body and f.body:
                lines.append(f.body)
        return "\n".join(lines)

    def calibration_text(self) -> str:
        docs = self.by_type("calibration")
        if not docs:
            return ""
        parts: list[str] = []
        for ex in docs[0].get("examples") or []:
            gold = ", ".join(f"{k}={v}" for k, v in (ex.get("gold") or {}).items())
            parts.append(f"Example {ex.get('id')}:\n{str(ex.get('script', '')).strip()}\nGold scores: {gold}")
        return "\n\n".join(parts)

    # ---- craft ------------------------------------------------------------------------------
    def craft_items(self, kind: str) -> list[CraftItem]:
        for d in self.by_type("craft_reference"):
            if d.get("kind") == kind:
                return [CraftItem.model_validate(i) for i in d.get("items") or []]
        return []

    def craft_body(self, kind: str) -> str:
        for d in self.by_type("craft_reference"):
            if d.get("kind") == kind:
                return d.body
        return ""

    def emotion_text(self) -> str:
        docs = self.by_type("emotion_taxonomy")
        if not docs:
            return ""
        d = docs[0]
        emo = "; ".join(
            f"{e.get('id')} ({e.get('valence')}): {e.get('description')}" for e in d.get("emotions") or []
        )
        arcs = "; ".join(f"{a.get('id')}: {a.get('description')}" for a in d.get("arc_shapes") or [])
        return f"Emotions (Plutchik): {emo}\nArc shapes: {arcs}"

    # ---- tropes -----------------------------------------------------------------------------
    @cached_property
    def tropes(self) -> list[Trope]:
        docs = self.by_type("trope_taxonomy")
        return [Trope.model_validate(t) for t in (docs[0].get("tropes") or [])] if docs else []

    # ---- compliance -------------------------------------------------------------------------
    def rule(self, rule_id: str) -> Doc | None:
        return next((d for d in self.by_type("compliance_rule") if d.get("rule_id") == rule_id), None)

    @cached_property
    def rating_matrix(self) -> dict[str, dict[str, str]]:
        docs = self.by_type("rating_matrix")
        return (
            {str(k): {str(s): str(b) for s, b in v.items()} for k, v in (docs[0].get("matrix") or {}).items()}
            if docs
            else {}
        )

    @cached_property
    def rating_guidance(self) -> dict[str, dict[str, str]]:
        docs = self.by_type("rating_matrix")
        return docs[0].get("guidance") or {} if docs else {}

    @cached_property
    def treatment_raise(self) -> list[str]:
        docs = self.by_type("rating_matrix")
        return (
            list(docs[0].get("treatment_raise") or ["glorified", "instructional"])
            if docs
            else ["glorified", "instructional"]
        )

    @cached_property
    def mode_lower(self) -> list[str]:
        docs = self.by_type("rating_matrix")
        return list(docs[0].get("mode_lower") or []) if docs else []

    @cached_property
    def legal_flags(self) -> list[dict[str, Any]]:
        docs = self.by_type("legal_risk_flags")
        return list(docs[0].get("flags") or []) if docs else []

    # ---- localization -----------------------------------------------------------------------
    @cached_property
    def subtitle_rules(self) -> dict[str, Any]:
        docs = self.by_type("subtitle_rules")
        base: dict[str, Any] = {
            "max_chars_per_line": 42,
            "max_lines": 2,
            "min_duration_s": 0.833,
            "max_duration_s": 7.0,
            "reading_speed_cps": 17,
        }
        if docs:
            base.update({k: v for k, v in (docs[0].model_extra or {}).items() if k in base})
        return base

    def profile(self, lang: str) -> Doc | None:
        return next((d for d in self.by_type("localization_profile") if d.get("lang") == lang), None)

    def trend(self, trope_id: str) -> Doc | None:
        return self.docs.get(f"trends/{trope_id}.md")

    def lexicon(self, name: str) -> list[tuple[str, str]]:
        """Return (term, severity) pairs; severity is '' when the file has none."""
        path = self.root / "lexicons" / name
        if not path.exists():
            return []
        out: list[tuple[str, str]] = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            sev, _, term = ln.rpartition("\t")
            out.append((term.strip().lower(), sev.strip()))
        return out


@lru_cache
def get_knowledge(root: str | None = None) -> Knowledge:
    return Knowledge(Path(root) if root else ROOT / "knowledge")
