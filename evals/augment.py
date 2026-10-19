"""Render eval scripts to screenplay-formatted page images and degrade them into 'scanned' PDFs.

Usage: uv run python evals/augment.py evals/scripts/s01_last_message.txt --dpi 200 [--clean]
Writes evals/scanned/<stem>_scan.pdf (degraded) or <stem>_clean.pdf.
"""

import argparse
import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bsa.ingest.text_formats import parse_text  # noqa: E402

LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
DEVA = str(ROOT / "evals" / "fonts" / "NotoSansDevanagari.ttf")
PAGE_IN = (8.5, 11.0)
# screenplay indents in inches from the page edge
INDENT = {
    "action": 1.5,
    "scene_heading": 1.5,
    "episode_marker": 1.5,
    "dialogue": 2.5,
    "parenthetical": 3.1,
    "cue": 3.7,
    "transition": 6.0,
}
WIDTH = {
    "action": 6.0,
    "scene_heading": 6.0,
    "episode_marker": 6.0,
    "dialogue": 3.5,
    "parenthetical": 2.0,
    "cue": 3.0,
    "transition": 1.5,
}


def is_deva(text: str) -> bool:
    return sum("ऀ" <= ch <= "ॿ" for ch in text) > len(text) * 0.3


def wrap(text: str, font: ImageFont.FreeTypeFont, width_px: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) > width_px and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def render(path: Path, dpi: int) -> list[Image.Image]:
    title, raw = parse_text(path.read_text(encoding="utf-8"))
    size = int(12 / 72 * dpi)
    fonts = {False: ImageFont.truetype(LATIN, size), True: ImageFont.truetype(DEVA, int(size * 1.1))}
    W, H = int(PAGE_IN[0] * dpi), int(PAGE_IN[1] * dpi)
    line_h = int(size * 1.6)
    pages: list[Image.Image] = []
    page = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(page)
    y = int(1.0 * dpi)
    blocks: list[tuple[str, str]] = []
    if title:
        blocks.append(("scene_heading", title.upper()))
    last_speaker = None
    for r in raw:
        if r.kind in ("dialogue", "parenthetical") and r.speaker and r.speaker != last_speaker:
            blocks.append(("cue", r.speaker))
        last_speaker = r.speaker if r.kind in ("dialogue", "parenthetical") else None
        blocks.append((r.kind if r.kind in INDENT else "action", r.text))
    for kind, text in blocks:
        font = fonts[is_deva(text)]
        lines = wrap(text, font, int(WIDTH[kind] * dpi), draw)
        need = line_h * len(lines) + (line_h if kind not in ("dialogue", "parenthetical") else 0)
        if y + need > H - int(1.0 * dpi):
            pages.append(page)
            page = Image.new("L", (W, H), 255)
            draw = ImageDraw.Draw(page)
            y = int(1.0 * dpi)
        if kind not in ("dialogue", "parenthetical"):
            y += line_h // 2 if y > dpi else 0
        for ln in lines:
            x = int(INDENT[kind] * dpi)
            if kind == "transition":
                x = int(7.5 * dpi - draw.textlength(ln, font=font))
            draw.text((x, y), ln, font=font, fill=0)
            y += line_h
    pages.append(page)
    return pages


def degrade(img: Image.Image, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = img.rotate(rnd.uniform(-1.8, 1.8), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    px = img.load()
    assert px is not None
    w, h = img.size
    for _ in range(int(w * h * 0.002)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        px[x, y] = rnd.choice((0, 90, 160))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=38)
    return Image.open(io.BytesIO(buf.getvalue())).convert("L")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--clean", action="store_true", help="no degradation")
    args = ap.parse_args()
    out_dir = ROOT / "evals" / "scanned"
    out_dir.mkdir(exist_ok=True)
    for f in args.files:
        pages = render(f, args.dpi)
        if not args.clean:
            pages = [degrade(p, i) for i, p in enumerate(pages)]
        out = out_dir / f"{f.stem}_{'clean' if args.clean else 'scan'}.pdf"
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=args.dpi)
        print(f"{out.relative_to(ROOT)}: {len(pages)} pages at {args.dpi} dpi")


if __name__ == "__main__":
    main()
