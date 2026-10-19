"""Positioned text lines (digital or OCR) and parser output before IDs are assigned."""

from dataclasses import dataclass

from bsa.domain.enums import ElementKind


@dataclass
class PageLine:
    page: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    conf: float | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (round(self.x0, 1), round(self.top, 1), round(self.x1, 1), round(self.bottom, 1))


@dataclass
class RawLine:
    kind: ElementKind
    text: str
    speaker: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    ocr_conf: float | None = None
    episode_no: int | None = None  # set on episode_marker lines
