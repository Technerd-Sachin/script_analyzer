"""OCR: PaddleOCR via the DOC_QnA service for Latin pages, a local PaddleOCR Devanagari recognizer
(GPU build, CPU fallback) for pages the service reads poorly, and the router that picks between them."""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx
import structlog
from PIL import Image

from bsa.config import Config
from bsa.ingest.types import PageLine


def ocr_document(
    data: bytes, filename: str, base_url: str, timeout: float = 300
) -> dict[int, tuple[list[PageLine], tuple[float, float]]]:
    """Return {page: (lines, (width_pt, height_pt))}. DOC_QnA reports points, top-left origin."""
    resp = httpx.post(
        f"{base_url}/idoc/layout",
        files={"file": (filename, data)},
        data={"include_page_markdown": "false"},
        timeout=timeout,
    )
    resp.raise_for_status()
    out: dict[int, tuple[list[PageLine], tuple[float, float]]] = {}
    for page in resp.json().get("ocr_layout", {}).get("pages", []):
        n = int(page["page"])
        lines = [
            PageLine(
                n,
                str(ln["content"]),
                float(ln["bbox"][0]),
                float(ln["bbox"][1]),
                float(ln["bbox"][2]),
                float(ln["bbox"][3]),
            )
            for ln in page.get("lines", [])
            if str(ln.get("content", "")).strip()
        ]
        out[n] = (lines, (float(page.get("width", 612.0)), float(page.get("height", 792.0))))
    return out


log = structlog.get_logger()
DEVA_REC = "devanagari_PP-OCRv5_mobile_rec"
DET = "PP-OCRv5_mobile_det"


def local_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("paddleocr") is not None


def resolve_device(wanted: str) -> str:
    """Use the GPU only when Paddle was compiled with CUDA and a device is visible."""
    if wanted != "gpu":
        return "cpu"
    try:
        import paddle  # pyright: ignore[reportMissingImports]  (optional "ocr" extra)

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu"
    except Exception:  # noqa: BLE001 - fall back to CPU on any CUDA problem
        log.warning("paddle_gpu_unavailable")
    return "cpu"


@lru_cache(maxsize=2)
def _engine(rec_model: str, device: str) -> Any:
    from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]  (optional "ocr" extra)

    return PaddleOCR(
        text_detection_model_name=DET,
        text_recognition_model_name=rec_model,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
        enable_mkldnn=False,  # CPU path only: Paddle 3.3 + oneDNN fails on PIR attributes for these models
    )


def local_ocr_image(
    img: Image.Image, page: int, pt_per_px: float, device: str = "gpu", rec_model: str = DEVA_REC
) -> list[PageLine]:
    import numpy as np

    result = _engine(rec_model, resolve_device(device)).predict(np.array(img.convert("RGB")))
    lines: list[PageLine] = []
    for res in result:
        texts, scores, boxes = res["rec_texts"], res["rec_scores"], res["rec_boxes"]
        for text, score, box in zip(texts, scores, boxes, strict=False):
            if not str(text).strip():
                continue
            x0, y0, x1, y1 = (float(v) * pt_per_px for v in box)
            lines.append(PageLine(page, str(text), x0, y0, x1, y1, float(score)))
    lines.sort(key=lambda ln: (round(ln.top / 4), ln.x0))
    return lines


log = structlog.get_logger()
_TOKEN = re.compile(r"\S+")
_GOOD = re.compile(r"^[\"'(\[]*(?:[A-Za-z][A-Za-z'\-]*|[ऀ-ॿ]+|\d+)[\"')\].,!?:;।-]*$")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def text_quality(lines: list[PageLine]) -> float:
    """Confidence proxy for engines that return no scores: share of word-like tokens, penalising CJK output."""
    text = " ".join(ln.text for ln in lines)
    tokens = _TOKEN.findall(text)
    if not tokens:
        return 0.0
    good = sum(bool(_GOOD.match(t)) for t in tokens) / len(tokens)
    cjk = len(_CJK.findall(text)) / max(1, len(text.replace(" ", "")))
    return round(good * (1 - min(1.0, 3 * cjk)), 3)


@dataclass
class OCRResult:
    lines: dict[int, list[PageLine]] = field(default_factory=dict)
    conf: dict[int, float] = field(default_factory=dict)
    engine: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def run(
    data: bytes, filename: str, pages: list[int], images: dict[int, tuple[Image.Image, float]], cfg: Config
) -> OCRResult:
    """images: {page: (image at native resolution capped at 300 dpi, points per pixel)}."""
    res = OCRResult()
    try:
        remote = ocr_document(data, filename, cfg.ocr.doc_qna_url)
    except Exception as exc:  # noqa: BLE001 - the local engine can still run
        remote = {}
        res.warnings.append(f"DOC_QnA OCR unavailable ({type(exc).__name__}); using local PaddleOCR only")
    for p in pages:
        lines = remote.get(p, ([], (612.0, 792.0)))[0]
        q = text_quality(lines)
        res.lines[p], res.conf[p], res.engine[p] = lines, q, "doc_qna:PP-OCRv5"
        if q >= cfg.ocr.low_conf_page and lines:
            continue
        if not local_available():
            res.warnings.append(
                f"page {p}: low OCR quality {q:.2f}; install the 'ocr' extra for Devanagari pages"
            )
            continue
        img, pt_per_px = images[p]
        local = local_ocr_image(img, p, pt_per_px, device=cfg.ocr.local_device)
        if local:
            lq = sum(ln.conf or 0 for ln in local) / len(local)
            low_share = sum((ln.conf or 0) < cfg.ocr.low_conf_line for ln in local) / len(local)
            if lq > q:
                res.lines[p], res.conf[p], res.engine[p] = (
                    local,
                    round(lq, 3),
                    f"local:{DEVA_REC}",
                )
                if lq < cfg.ocr.low_conf_page or low_share > cfg.ocr.low_line_share:
                    res.warnings.append(
                        f"page {p}: low OCR confidence {lq:.2f} ({low_share:.0%} of lines below {cfg.ocr.low_conf_line})"
                    )
    log.info("ocr_done", pages=len(pages), engines=sorted(set(res.engine.values())))
    return res
