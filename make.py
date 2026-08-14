#!/usr/bin/env python3
"""Build the Agentic Mono JP AI CLI font derivative.

The derivative keeps the upstream Moralerspace Neon HW font untouched. Only the
selected core glyphs (①..⑨ and ※) plus the individually selected warning and
ellipsis glyphs (⚠ and …) are regenerated. All other glyphs keep their original
outline and metrics.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from fontTools.misc.transform import Transform
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

SRC_DIR = Path.home() / "Library" / "Fonts"
STYLES = ("Regular", "Bold", "Italic", "BoldItalic")

SRC_FAMILY = "Moralerspace Neon HW"
SRC_STEM = "MoralerspaceNeonHW"
FINAL_FAMILY = "Agentic Mono JP"
FINAL_STEM = "AgenticMonoJP"

HALF_WIDTH = 525
CIRCLE_CODEPOINTS = tuple(range(0x2460, 0x2469))
NOTE_CODEPOINT = 0x203B
WARNING_CODEPOINT = 0x26A0
ELLIPSIS_CODEPOINT = 0x2026
ADOPTED_CANDIDATES = frozenset({WARNING_CODEPOINT, ELLIPSIS_CODEPOINT})
TARGETS = frozenset(
    (*CIRCLE_CODEPOINTS, NOTE_CODEPOINT, *sorted(ADOPTED_CANDIDATES))
)

# Measured from the documented CJK comparison set used alongside
# render_sample.SAMPLE. The bounds
# use the robust 10th/90th percentile envelope plus a 2-unit safety margin,
# rather than the single most extreme glyph in the sample.
CJK_VERTICAL_BOXES = {
    "Regular": (-84, 850),
    "Bold": (-91, 858),
    "Italic": (-84, 850),
    "BoldItalic": (-91, 858),
}

CIRCLE_SOURCE_STYLES = {
    "Regular": "Bold",
    "Bold": "Bold",
    "Italic": "BoldItalic",
    "BoldItalic": "BoldItalic",
}


class BuildInputError(ValueError):
    """The upstream font does not satisfy the build input contract."""


def _glyph_program_size(glyph) -> int:
    program = getattr(glyph, "program", None)
    return len(program.getBytecode()) if program is not None else 0


def _bounds(font: TTFont, glyph):
    glyph.recalcBounds(font["glyf"])
    return glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax


def validate_source(font: TTFont, style: str) -> dict[int, str]:
    """Validate cmap, UPM, glyph structure, and alias safety for all targets."""
    if font["head"].unitsPerEm != 1000:
        raise BuildInputError(
            f"{style}: UPM={font['head'].unitsPerEm} (expected 1000)"
        )
    cmap = font.getBestCmap()
    mapping: dict[int, str] = {}
    for codepoint in sorted(TARGETS):
        glyph_name = cmap.get(codepoint)
        if glyph_name is None:
            raise BuildInputError(f"{style}: missing target U+{codepoint:04X}")
        mapping[codepoint] = glyph_name
    if len(set(mapping.values())) != len(mapping):
        raise BuildInputError(f"{style}: target glyphs are shared")

    unicode_subtables = [
        (index, table)
        for index, table in enumerate(font["cmap"].tables)
        if table.isUnicode()
    ]
    if not unicode_subtables:
        raise BuildInputError(f"{style}: no Unicode cmap subtable")
    target_names = set(mapping.values())
    for index, table in unicode_subtables:
        references = {
            codepoint: glyph_name
            for codepoint, glyph_name in table.cmap.items()
            if glyph_name in target_names
        }
        if references != mapping:
            raise BuildInputError(
                f"{style}: Unicode cmap subtable {index} has target aliases"
            )

    glyf = font["glyf"]
    for codepoint, glyph_name in mapping.items():
        glyph = glyf[glyph_name]
        if glyph.numberOfContours < 0:
            raise BuildInputError(f"{style}: target glyph {glyph_name} is composite")
        if _glyph_program_size(glyph) and codepoint != ELLIPSIS_CODEPOINT:
            raise BuildInputError(
                f"{style}: target glyph {glyph_name} has instructions"
            )
        x_min, y_min, x_max, y_max = _bounds(font, glyph)
        if x_max <= x_min or y_max <= y_min:
            raise BuildInputError(
                f"{style}: target glyph {glyph_name} has empty bounds"
            )

    for glyph_name in font.getGlyphOrder():
        if glyph_name in target_names:
            continue
        for component in getattr(glyf[glyph_name], "components", ()):
            if component.glyphName in target_names:
                raise BuildInputError(
                    f"{style}: target glyph {component.glyphName} is used as a component"
                )
    return mapping


def _transform_glyph(
    source_font: TTFont,
    codepoint: int,
    *,
    sx: float,
    sy: float,
    center_x: float = HALF_WIDTH / 2,
    center_y: float | None = None,
):
    source_name = source_font.getBestCmap().get(codepoint)
    if source_name is None:
        raise BuildInputError(f"missing source U+{codepoint:04X}")
    source_glyf = source_font["glyf"]
    source = source_glyf[source_name]
    if source.numberOfContours < 0:
        raise BuildInputError(f"source U+{codepoint:04X} is composite")
    x_min, y_min, x_max, y_max = _bounds(source_font, source)
    source_center_x = (x_min + x_max) / 2
    source_center_y = (y_min + y_max) / 2
    if center_y is None:
        center_y = source_center_y
    transform = Transform(
        sx,
        0,
        0,
        sy,
        center_x - sx * source_center_x,
        center_y - sy * source_center_y,
    )
    pen = TTGlyphPen(source_glyf)
    source.draw(TransformPen(pen, transform), source_glyf)
    result = pen.glyph()
    result.recalcBounds(source_glyf)
    return result


def transformed_glyph(
    source_font: TTFont,
    codepoint: int,
    rule: str,
    *,
    style: str = "Regular",
):
    """Return the exact glyph produced by a named per-glyph transform rule."""
    source_name = source_font.getBestCmap().get(codepoint)
    if source_name is None:
        raise BuildInputError(f"missing source U+{codepoint:04X}")
    source = source_font["glyf"][source_name]
    x_min, y_min, x_max, y_max = _bounds(source_font, source)
    ink_width = x_max - x_min
    if ink_width <= 0:
        raise BuildInputError(f"source U+{codepoint:04X} has empty bounds")
    if rule in {"core", "fit-cjk"}:
        scale = HALF_WIDTH / ink_width
        if rule == "core":
            x_min, y_min, x_max, y_max = _bounds(source_font, source)
            return _transform_glyph(
                source_font,
                codepoint,
                sx=scale,
                sy=(CJK_VERTICAL_BOXES[style][1] - CJK_VERTICAL_BOXES[style][0])
                / (y_max - y_min),
                center_y=sum(CJK_VERTICAL_BOXES[style]) / 2,
            )
        target_y_min, target_y_max = CJK_VERTICAL_BOXES[style]
        return _transform_glyph(
            source_font,
            codepoint,
            sx=scale,
            sy=(target_y_max - target_y_min) / (y_max - y_min),
            center_y=(target_y_min + target_y_max) / 2,
        )
    if rule == "fit-ellipsis":
        scale = HALF_WIDTH / ink_width
        return _transform_glyph(source_font, codepoint, sx=scale, sy=1)
    raise BuildInputError(f"unknown transform rule: {rule}")


def rule_for(codepoint: int) -> str:
    if codepoint in CIRCLE_CODEPOINTS:
        return "core"
    if codepoint == NOTE_CODEPOINT:
        return "fit-cjk"
    if codepoint == WARNING_CODEPOINT:
        return "fit-cjk"
    if codepoint == ELLIPSIS_CODEPOINT:
        return "fit-ellipsis"
    raise BuildInputError(f"no transform rule for U+{codepoint:04X}")


def _replace_glyph(
    destination: TTFont,
    destination_name: str,
    source: TTFont,
    codepoint: int,
    rule: str,
    style: str,
) -> None:
    result = transformed_glyph(source, codepoint, rule, style=style)
    destination["glyf"][destination_name] = result
    result.recalcBounds(destination["glyf"])
    if result.xMin < 0 or result.xMax > HALF_WIDTH:
        raise BuildInputError(
            f"U+{codepoint:04X} is outside 0..{HALF_WIDTH}: "
            f"({result.xMin},{result.xMax})"
        )
    destination["hmtx"][destination_name] = (HALF_WIDTH, result.xMin)


def rename(font: TTFont, style: str) -> int:
    """Rename output records to the Agentic Mono JP identity."""
    subfamily = "Bold Italic" if style == "BoldItalic" else style
    canonical = {
        1: FINAL_FAMILY,
        2: subfamily,
        3: f"Version 2.0.0; Moralerspace-derived; {FINAL_FAMILY}; {subfamily}",
        4: f"{FINAL_FAMILY} {subfamily}",
        6: f"{FINAL_STEM}-{style}",
        16: FINAL_FAMILY,
        17: subfamily,
    }
    changed = 0
    for record in font["name"].names:
        value = record.toUnicode()
        renamed = canonical.get(
            record.nameID,
            value.replace(SRC_FAMILY, FINAL_FAMILY).replace(SRC_STEM, FINAL_STEM),
        )
        if renamed == value:
            continue
        record.string = renamed.encode(record.getEncoding())
        changed += 1
    metadata = sorted(
        {
            (record.platformID, record.platEncID, record.langID)
            for record in font["name"].names
            if record.nameID in {1, 2, 3, 4, 6}
        }
    )
    for name_id in (16, 17):
        for platform_id, encoding_id, language_id in metadata:
            if any(
                record.nameID == name_id
                and record.platformID == platform_id
                and record.platEncID == encoding_id
                and record.langID == language_id
                for record in font["name"].names
            ):
                continue
            font["name"].setName(
                canonical[name_id],
                name_id,
                platform_id,
                encoding_id,
                language_id,
            )
            changed += 1
    return changed


def _assert_renamed(font: TTFont, style: str) -> None:
    subfamily = "Bold Italic" if style == "BoldItalic" else style
    records = [record.toUnicode() for record in font["name"].names]
    if any(
        SRC_FAMILY in value
        or SRC_STEM in value
        for value in records
    ):
        raise BuildInputError("name table still contains source or legacy names")
    expected = {
        1: FINAL_FAMILY,
        2: subfamily,
        3: f"Version 2.0.0; Moralerspace-derived; {FINAL_FAMILY}; {subfamily}",
        4: f"{FINAL_FAMILY} {subfamily}",
        6: f"{FINAL_STEM}-{style}",
        16: FINAL_FAMILY,
        17: subfamily,
    }
    for name_id, value in expected.items():
        if not any(
            record.nameID == name_id and record.toUnicode() == value
            for record in font["name"].names
        ):
            raise BuildInputError(f"name table name ID {name_id} is not canonical")


def _load_source(style: str) -> TTFont:
    path = SRC_DIR / f"{SRC_STEM}-{style}.ttf"
    try:
        return TTFont(path)
    except (FileNotFoundError, OSError) as exc:
        raise OSError(f"source font not found: {path}") from exc


def build(style: str, out_dir: Path) -> tuple[Path, int]:
    """Build one style using Bold/BoldItalic source outlines for ①..⑨."""
    destination = _load_source(style)
    source_style = CIRCLE_SOURCE_STYLES[style]
    source = destination if source_style == style else _load_source(source_style)
    try:
        destination_mapping = validate_source(destination, style)
        validate_source(source, source_style)
        if destination["head"].unitsPerEm != source["head"].unitsPerEm:
            raise BuildInputError(f"{style}: source/destination UPM mismatch")
        for codepoint in CIRCLE_CODEPOINTS:
            _replace_glyph(
                destination,
                destination_mapping[codepoint],
                source,
                codepoint,
                "core",
                style,
            )
        for codepoint in (NOTE_CODEPOINT, WARNING_CODEPOINT, ELLIPSIS_CODEPOINT):
            _replace_glyph(
                destination,
                destination_mapping[codepoint],
                destination,
                codepoint,
                rule_for(codepoint),
                style,
            )
        for codepoint in sorted(TARGETS):
            name = destination_mapping[codepoint]
            glyph = destination["glyf"][name]
            glyph.recalcBounds(destination["glyf"])
            if glyph.numberOfContours <= 0 or glyph.xMin < 0 or glyph.xMax > HALF_WIDTH:
                raise BuildInputError(
                    f"{style}: invalid fitted U+{codepoint:04X} geometry"
                )
            if destination["hmtx"][name] != (HALF_WIDTH, glyph.xMin):
                raise BuildInputError(
                    f"{style}: invalid fitted U+{codepoint:04X} metrics"
                )
        rename(destination, style)
        _assert_renamed(destination, style)
    except BuildInputError as exc:
        raise BuildInputError(f"{SRC_DIR / f'{SRC_STEM}-{style}.ttf'}: {exc}") from exc
    finally:
        if source is not destination:
            source.close()

    out_path = out_dir / f"{FINAL_STEM}-{style}.ttf"
    try:
        destination.save(out_path)
    except (FileNotFoundError, OSError) as exc:
        raise OSError(f"cannot save output: {out_path}: {exc}") from exc
    finally:
        destination.close()
    return out_path, len(TARGETS)


def _publish_staged(staging_dir: Path, out_dir: Path, staged_paths: list[Path]) -> list[Path]:
    final_paths = [out_dir / f"{FINAL_STEM}-{style}.ttf" for style in STYLES]
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for final_path in final_paths:
            if final_path.exists():
                if not final_path.is_file():
                    raise OSError(f"cannot publish output: {final_path} is not a file")
                backup_path = staging_dir / f".backup-{final_path.name}"
                os.replace(final_path, backup_path)
                backups[final_path] = backup_path
        for staged_path, final_path in zip(staged_paths, final_paths):
            os.replace(staged_path, final_path)
            published.append(final_path)
    except OSError:
        rollback_error = None
        for final_path in reversed(published):
            try:
                final_path.unlink()
            except OSError as rollback_exc:
                rollback_error = rollback_exc
        for final_path, backup_path in backups.items():
            if not backup_path.exists():
                continue
            try:
                os.replace(backup_path, final_path)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
        if rollback_error is not None:
            raise OSError(
                f"cannot roll back output publication in {out_dir}: {rollback_error}"
            ) from rollback_error
        raise
    return final_paths


def build_all(out_dir: Path) -> list[Path]:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except (FileNotFoundError, OSError) as exc:
        raise OSError(f"cannot create output directory: {out_dir}") from exc
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".staging-") as staging:
        staging_dir = Path(staging)
        staged_paths = [build(style, staging_dir)[0] for style in STYLES]
        return _publish_staged(staging_dir, out_dir, staged_paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default="build")
    args = parser.parse_args(argv)
    try:
        output_paths = build_all(Path(args.out_dir))
    except BuildInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for out_path in output_paths:
        print(f"{out_path}  ({len(TARGETS)} glyphs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
