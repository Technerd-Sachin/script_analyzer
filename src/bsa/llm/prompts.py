"""Versioned Jinja2 prompt files in prompts/ with YAML front matter."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from bsa.config import ROOT

_env = Environment(
    undefined=StrictUndefined, keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True
)


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    meta: dict[str, Any]
    body: str

    def render(self, **kwargs: Any) -> str:
        return _env.from_string(self.body).render(**kwargs).strip()


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.lstrip("\n")
    return {}, text


@lru_cache
def load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt:
    path = (prompts_dir or ROOT / "prompts") / f"{name}.md.j2"
    meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    return Prompt(id=str(meta.get("id", name)), version=str(meta.get("version", "0")), meta=meta, body=body)
