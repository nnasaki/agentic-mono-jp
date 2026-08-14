#!/usr/bin/env python3
"""Render a compact source and derived font comparison."""

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont, TTLibError

from make import FINAL_STEM, HALF_WIDTH, SRC_DIR, SRC_STEM

SAMPLE = (
    "①設定確認",
    "※注記  ⚠警告",
    "①A ②B ⑧…wait",
)
IMAGE_SIZE = (1440, 760)
BLUE = "#1683ff"
TEXT = "#202124"
MUTED = "#667085"
LIGHT = "#d9dde3"


class RenderError(Exception):
    """A narrow rendering input or output error."""


def _load_font(path: Path, size: int):
    try:
        font = TTFont(path)
        font.close()
        return ImageFont.truetype(str(path), size)
    except (OSError, TTLibError) as exc:
        raise RenderError(f"cannot load font: {path}: {exc}") from exc


def cells(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def draw_cell_text(draw, path: Path, text: str, x: int, y: int, size: int) -> None:
    font = _load_font(path, size)
    cell = size * HALF_WIDTH / 1000
    cursor = float(x)
    for char in text:
        draw.text((cursor, y), char, font=font, fill=TEXT)
        cursor += cell * cells(char)


def draw_height_comparison(draw, path: Path, x: int, y: int, width: int) -> None:
    font = _load_font(path, 56)
    _, ink_top, _, ink_bottom = font.getbbox("設定確認")
    top = y + ink_top
    bottom = y + ink_bottom
    draw.line((x, top, x + width, top), fill=BLUE, width=2)
    draw.line((x, bottom, x + width, bottom), fill=BLUE, width=2)
    draw.text(
        (x, top - 26),
        "日本語本文の高さ",
        font=_load_font(path, 16),
        fill=BLUE,
    )
    draw_cell_text(draw, path, SAMPLE[0], x + 18, y, 56)


def draw_width_comparison(draw, path: Path, x: int, y: int, width: int) -> None:
    size = 48
    font = _load_font(path, size)
    cell = size * HALF_WIDTH / 1000
    _, ink_top, _, ink_bottom = font.getbbox("注記警告")
    top = y + ink_top
    bottom = y + ink_bottom
    draw.line((x, top, x + width, top), fill=BLUE, width=2)
    draw.line((x, bottom, x + width, bottom), fill=BLUE, width=2)
    draw.line((x + 18, top, x + 18, bottom), fill=BLUE, width=2)
    draw.line((x + 18 + cell, top, x + 18 + cell, bottom), fill=BLUE, width=2)
    draw.text(
        (x + 22, bottom + 7),
        "1 cell",
        font=_load_font(path, 14),
        fill=BLUE,
    )
    draw_cell_text(draw, path, SAMPLE[1], x + 18, y, size)


def render_sample(out_dir: Path, png: Path) -> None:
    out_dir = Path(out_dir)
    png = Path(png)
    try:
        png.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(f"cannot create PNG parent: {png.parent}: {exc}") from exc

    source_path = SRC_DIR / f"{SRC_STEM}-Regular.ttf"
    derived_path = out_dir / f"{FINAL_STEM}-Regular.ttf"
    image = Image.new("RGB", IMAGE_SIZE, "#ffffff")
    draw = ImageDraw.Draw(image)

    draw.text(
        (48, 30),
        "AIがよく使う記号、日本語にピッタリ。",
        font=_load_font(derived_path, 34),
        fill=TEXT,
    )

    left_x = 48
    right_x = 760
    column_width = 620
    draw.line((720, 126, 720, 710), fill=LIGHT, width=2)
    draw.text((left_x, 128), "BEFORE", font=_load_font(source_path, 24), fill=TEXT)
    draw.text(
        (left_x, 164),
        "小さい / はみ出す / 後続文字と重なる",
        font=_load_font(source_path, 18),
        fill=MUTED,
    )
    draw.text((right_x, 128), "AFTER", font=_load_font(derived_path, 24), fill=TEXT)
    draw.text(
        (right_x, 164),
        "本文高まで拡大 / 1セル内に収める",
        font=_load_font(derived_path, 18),
        fill=MUTED,
    )

    draw_height_comparison(draw, source_path, left_x, 230, column_width)
    draw_height_comparison(draw, derived_path, right_x, 230, column_width)
    draw.text(
        (left_x, 330),
        "①が本文より小さく、手順番号を見落としやすい",
        font=_load_font(source_path, 17),
        fill=MUTED,
    )
    draw.text(
        (right_x, 330),
        "①〜⑨を日本語本文高ぎりぎりまで拡大",
        font=_load_font(derived_path, 17),
        fill=BLUE,
    )

    draw_width_comparison(draw, source_path, left_x, 414, column_width)
    draw_width_comparison(draw, derived_path, right_x, 414, column_width)
    draw.text(
        (left_x, 520),
        "※と⚠が1セルからはみ出し、注記と重なる",
        font=_load_font(source_path, 17),
        fill=MUTED,
    )
    draw.text(
        (right_x, 520),
        "1セル内に収まり、後続の日本語と重ならない",
        font=_load_font(derived_path, 17),
        fill=BLUE,
    )

    draw.line((48, 580, 1380, 580), fill=LIGHT, width=2)
    draw.text(
        (48, 608),
        "半角文字との組み合わせ",
        font=_load_font(derived_path, 18),
        fill=MUTED,
    )
    draw_cell_text(draw, source_path, SAMPLE[2], 48, 642, 42)
    draw_cell_text(draw, derived_path, SAMPLE[2], 760, 642, 42)

    try:
        image.save(png, format="PNG")
    except (OSError, ValueError) as exc:
        raise RenderError(f"cannot save PNG: {png}: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default="build")
    parser.add_argument("png", nargs="?")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    png = Path(args.png) if args.png else out_dir / "sample.png"

    source_path = SRC_DIR / f"{SRC_STEM}-Regular.ttf"
    if not source_path.is_file():
        print(f"error: source font not found: {source_path}", file=sys.stderr)
        return 2
    derived_path = out_dir / f"{FINAL_STEM}-Regular.ttf"
    if not derived_path.is_file():
        print(f"error: derived font not found: {derived_path}", file=sys.stderr)
        return 2
    try:
        render_sample(out_dir, png)
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
