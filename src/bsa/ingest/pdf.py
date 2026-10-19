"""PDF and image ingest: per-page digital/scanned detection, digital text with boxes, OCR, layout."""

import io
import re
from dataclasses import dataclass, field

import pdfplumber
import pypdfium2 as pdfium
from pdfplumber.page import Page
from PIL import Image

from bsa.config import Config
from bsa.domain.enums import PageSource, SourceKind
from bsa.ingest import ocr
from bsa.ingest.layout import classify, restructure_with_llm
from bsa.ingest.types import PageLine, RawLine

RENDER_SCALE = 2.0  # viewer page images: 1 PDF point = 2 pixels (144 dpi)
IMAGE_DPI = 300  # pixel-to-point assumption for photos and scans (same as DOC_QnA)
_EXPECTED = re.compile(r"[A-Za-z0-9ऀ-ॿঀ-৿஀-௿ఀ-౿\s.,!?'\"():;\-]")


@dataclass
class VisualResult:
    title: str | None
    lines: list[RawLine]
    pages: int
    source_kind: SourceKind
    page_sources: dict[int, PageSource] = field(default_factory=dict)
    ocr_mean_conf: float | None = None
    warnings: list[str] = field(default_factory=list)


def is_digital(page: Page) -> bool:
    text = "".join(c["text"] for c in page.chars)
    if len(text.strip()) < 50:
        return False
    expected = len(_EXPECTED.findall(text)) / max(1, len(text))
    if expected < 0.6:
        return False
    area = float(page.width * page.height)
    big_image = any((im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) >= 0.9 * area for im in page.images)
    sizes = [c.get("size", 10) for c in page.chars]
    tiny = sum(sizes) / max(1, len(sizes)) < 4
    return not (big_image and tiny)


def digital_lines(page: Page, n: int) -> list[PageLine]:
    words = page.extract_words(x_tolerance=1.5, y_tolerance=3, keep_blank_chars=False)
    rows: list[list[dict[str, float | str]]] = []
    for w in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        if rows and abs(float(rows[-1][0]["top"]) - float(w["top"])) <= 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[PageLine] = []
    for row in rows:
        row.sort(key=lambda w: float(w["x0"]))
        out.append(
            PageLine(
                n,
                " ".join(str(w["text"]) for w in row),
                float(row[0]["x0"]),
                min(float(w["top"]) for w in row),
                max(float(w["x1"]) for w in row),
                max(float(w["bottom"]) for w in row),
            )
        )
    return out


def native_render(
    pdf: pdfium.PdfDocument, plumber_page: Page, index: int, max_dpi: int
) -> tuple[Image.Image, float]:
    """Render at the embedded image's native resolution, capped at max_dpi. Never upsample."""
    dpi = 150.0
    if plumber_page.images:
        im = max(plumber_page.images, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]))
        width_in = float(im["x1"] - im["x0"]) / 72
        if width_in > 0 and im.get("srcsize"):
            dpi = float(im["srcsize"][0]) / width_in
    dpi = min(dpi, float(max_dpi))
    img = pdf[index].render(scale=dpi / 72).to_pil()  # type: ignore[arg-type]
    return img, 72 / dpi


def ingest_visual(data: bytes, ext: str, cfg: Config) -> VisualResult:
    from bsa.ingest.detect import IngestError

    warnings: list[str] = []
    widths: dict[int, float] = {}
    lines: list[PageLine] = []
    scanned: list[int] = []
    images: dict[int, tuple[Image.Image, float]] = {}
    sources: dict[int, PageSource] = {}
    if ext == ".pdf":
        with pdfplumber.open(io.BytesIO(data)) as doc:
            n_pages = len(doc.pages)
            if n_pages > cfg.limits.max_pages:
                raise IngestError(413, f"PDF has {n_pages} pages; the limit is {cfg.limits.max_pages}")
            pdf = pdfium.PdfDocument(data)
            for i, page in enumerate(doc.pages, start=1):
                widths[i] = float(page.width)
                if is_digital(page):
                    lines.extend(digital_lines(page, i))
                    sources[i] = "digital"
                else:
                    scanned.append(i)
                    images[i] = native_render(pdf, page, i - 1, cfg.ocr.max_dpi)
                    sources[i] = "ocr"
        filename = "document.pdf"
    else:
        img = Image.open(io.BytesIO(data))
        n_pages = getattr(img, "n_frames", 1)
        if n_pages > cfg.limits.max_pages:
            raise IngestError(413, f"Image has {n_pages} pages; the limit is {cfg.limits.max_pages}")
        img.seek(0)
        frame = img.convert("RGB")
        widths[1] = frame.width * 72 / IMAGE_DPI
        scanned, images, sources = [1], {1: (frame, 72 / IMAGE_DPI)}, {1: "ocr"}
        filename = f"page{ext}"
    conf: float | None = None
    if scanned:
        res = ocr.run(data, filename, scanned, images, cfg)
        warnings.extend(res.warnings)
        for p in scanned:
            lines.extend(res.lines.get(p, []))
        if res.conf:
            conf = round(sum(res.conf.values()) / len(res.conf), 3)
    lines.sort(key=lambda ln: (ln.page, ln.top, ln.x0))
    title, raw, share = classify(lines, widths)
    if share < 0.6:
        llm_raw = restructure_with_llm(lines, cfg)
        if llm_raw:
            raw = llm_raw
            warnings.append(
                f"layout rules matched {share:.0%} of lines; LLM restructuring accepted (similarity >= 0.98)"
            )
        else:
            warnings.append(
                f"layout rules matched {share:.0%} of lines (below 60%); kept rule result, structure may be approximate"
            )
    kind: SourceKind
    if ext != ".pdf":
        kind = "image"
    elif not scanned:
        kind = "pdf_digital"
    elif len(scanned) == n_pages:
        kind = "pdf_scanned"
    else:
        kind = "pdf_mixed"
    return VisualResult(title, raw, n_pages, kind, sources, conf, warnings)


def render_page_png(data: bytes, ext: str, n: int) -> bytes:
    """Page image for the viewer at RENDER_SCALE pixels per point."""
    if ext == ".pdf":
        pdf = pdfium.PdfDocument(data)
        if not 1 <= n <= len(pdf):
            raise IndexError(n)
        img = pdf[n - 1].render(scale=RENDER_SCALE).to_pil()  # type: ignore[arg-type]
    else:
        src = Image.open(io.BytesIO(data))
        src.seek(n - 1)
        scale = 72 / IMAGE_DPI * RENDER_SCALE
        img = src.convert("RGB").resize((int(src.width * scale), int(src.height * scale)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
