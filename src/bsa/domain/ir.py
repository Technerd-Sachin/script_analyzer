"""Script intermediate representation: the single parsed form every input format becomes."""

from functools import cached_property

from pydantic import BaseModel, Field

from bsa.domain.enums import ElementKind, LangCode, PageSource, SourceKind


class Element(BaseModel):
    id: str  # "L1".."Ln", global, sequential, deterministic
    kind: ElementKind
    text: str  # verbatim from source (after OCR)
    speaker: str | None = None  # set for dialogue and parenthetical
    episode: int = 1
    scene_id: str = "S1"
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in PDF points, top-left origin
    ocr_conf: float | None = None
    lang: LangCode | None = None


class Scene(BaseModel):
    id: str
    episode: int
    heading: str | None = None
    element_ids: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    number: int
    title: str | None = None
    scene_ids: list[str] = Field(default_factory=list)
    boundary_source: str = "single"  # marker | llm | single


class ScriptIR(BaseModel):
    doc_id: str
    title: str | None = None
    source_kind: SourceKind = "text"
    pages: int | None = None
    languages: dict[str, float] = Field(default_factory=dict)  # LangCode -> share of characters
    episodes: list[Episode] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    page_sources: dict[int, PageSource] = Field(default_factory=dict)
    ocr_mean_conf: float | None = None
    code_mix_ratio: float | None = None
    warnings: list[str] = Field(default_factory=list)

    @cached_property
    def by_id(self) -> dict[str, Element]:
        return {e.id: e for e in self.elements}

    def episode_elements(self, number: int) -> list[Element]:
        return [e for e in self.elements if e.episode == number]

    def index_of(self, line_id: str) -> int:
        return next(i for i, e in enumerate(self.elements) if e.id == line_id)

    @property
    def primary_lang(self) -> str:
        return max(self.languages, key=lambda k: self.languages[k]) if self.languages else "en"
