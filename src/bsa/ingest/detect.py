"""Format detection, size limits and the single entry point from bytes to ScriptIR."""

import hashlib
from pathlib import Path

from bsa.config import Config, get_config
from bsa.domain.enums import PageSource, SourceKind
from bsa.domain.ir import ScriptIR
from bsa.ingest.episodes import build_ir
from bsa.ingest.language import code_mix_ratio, tag_languages
from bsa.ingest.text_formats import parse_docx, parse_fdx, parse_text
from bsa.ingest.types import RawLine

TEXT_EXT = {".txt", ".md", ".text", ""}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED = TEXT_EXT | PDF_EXT | IMAGE_EXT | {".fountain", ".fdx", ".docx"}


class IngestError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code  # HTTP-style: 413 too large, 415 unsupported, 422 unreadable
        self.message = message


def doc_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def ingest_bytes(data: bytes, filename: str, cfg: Config | None = None) -> ScriptIR:
    cfg = cfg or get_config()
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise IngestError(
            415, f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED - {''}))}"
        )
    if len(data) > cfg.limits.max_bytes:
        raise IngestError(413, f"File is {len(data):,} bytes; the limit is {cfg.limits.max_bytes:,} bytes")
    doc_id = doc_hash(data)
    title: str | None = None
    pages: int | None = None
    page_sources: dict[int, PageSource] = {}
    ocr_conf: float | None = None
    warnings: list[str] = []
    raw: list[RawLine]
    kind: SourceKind
    if ext in TEXT_EXT or ext == ".fountain":
        text = _decode(data)
        if len(text) > cfg.limits.max_text_chars:
            raise IngestError(
                413, f"Text is {len(text):,} characters; the limit is {cfg.limits.max_text_chars:,}"
            )
        title, raw = parse_text(text, fountain=ext == ".fountain")
        kind = "fountain" if ext == ".fountain" else "text"
    elif ext == ".fdx":
        title, raw = parse_fdx(data)
        kind = "fdx"
    elif ext == ".docx":
        title, raw = parse_docx(data)
        kind = "docx"
    else:
        from bsa.ingest.pdf import ingest_visual  # PDF and images (digital text or OCR)

        res = ingest_visual(data, ext, cfg)
        title, raw, pages, kind = res.title, res.lines, res.pages, res.source_kind
        page_sources, ocr_conf, warnings = res.page_sources, res.ocr_mean_conf, res.warnings
        if ocr_conf is not None and ocr_conf < cfg.ocr.unreadable_conf:
            raise IngestError(422, f"OCR mean confidence {ocr_conf:.2f} is below {cfg.ocr.unreadable_conf}")
    if not raw:
        raise IngestError(422, "No script text found in the document")
    ir = build_ir(raw, doc_id=doc_id, title=title or Path(filename).stem, source_kind=kind, pages=pages)
    ir.page_sources = page_sources
    ir.ocr_mean_conf = ocr_conf
    ir.warnings.extend(warnings)
    ir.languages = tag_languages(ir.elements)
    ir.code_mix_ratio = code_mix_ratio(ir.elements)
    return ir


def ingest_path(path: Path, cfg: Config | None = None) -> ScriptIR:
    return ingest_bytes(path.read_bytes(), path.name, cfg)


def ingest_text(text: str, title: str | None = None, cfg: Config | None = None) -> ScriptIR:
    body = f"Title: {title}\n{text}" if title and not text.lstrip().lower().startswith("title:") else text
    return ingest_bytes(body.encode("utf-8"), "pasted.txt", cfg)
