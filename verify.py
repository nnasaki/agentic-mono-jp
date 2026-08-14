#!/usr/bin/env python3
"""Verify glyph, identity, and name contracts for Agentic Mono JP.

``--control`` loads each normal derived font as a fresh baseline, verifies that
the baseline passes the selected check, and then creates one violation for that
check. A successful control run therefore proves that the checks are active
rather than merely present in the source. The original font is used only as
the identity/source reference, never as the control baseline.
"""

import argparse
import sys
from pathlib import Path
from typing import Sequence

from fontTools.ttLib import TTFont

from make import (
    CIRCLE_CODEPOINTS,
    CIRCLE_SOURCE_STYLES,
    CJK_VERTICAL_BOXES,
    FINAL_FAMILY,
    FINAL_STEM,
    ELLIPSIS_CODEPOINT,
    HALF_WIDTH,
    NOTE_CODEPOINT,
    SRC_DIR,
    SRC_FAMILY,
    SRC_STEM,
    STYLES,
    TARGETS,
    WARNING_CODEPOINT,
    transformed_glyph,
)


def _glyph_signature(glyph):
    return (
        glyph.numberOfContours,
        tuple(glyph.coordinates),
        tuple(glyph.endPtsOfContours),
        tuple(glyph.flags),
    )


def _bounds(font, glyph):
    glyph.recalcBounds(font["glyf"])
    return glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax


def target_glyph_names(font):
    cmap = font.getBestCmap()
    return {cmap[cp] for cp in TARGETS if cp in cmap}


def check_advance(derived, original):
    """Check target cmap identity and half-cell advances."""
    bad = []
    source_tables = original["cmap"].tables
    derived_tables = derived["cmap"].tables
    if len(source_tables) != len(derived_tables):
        bad.append("cmap subtable count differs from original")
    for index, (source_table, derived_table) in enumerate(
        zip(source_tables, derived_tables)
    ):
        source_metadata = (
            source_table.format,
            source_table.platformID,
            source_table.platEncID,
            getattr(source_table, "language", None),
        )
        derived_metadata = (
            derived_table.format,
            derived_table.platformID,
            derived_table.platEncID,
            getattr(derived_table, "language", None),
        )
        if source_metadata != derived_metadata:
            bad.append(f"cmap subtable {index} metadata differs")
        if source_table.cmap != derived_table.cmap:
            bad.append(f"cmap subtable {index} mapping differs from original")

    source_cmap = original.getBestCmap()
    derived_cmap = derived.getBestCmap()
    source_names = []
    for cp in sorted(TARGETS):
        source_name = source_cmap.get(cp)
        if source_name is None:
            bad.append(f"原本に U+{cp:04X} が無い")
        else:
            source_names.append(source_name)
        derived_name = derived_cmap.get(cp)
        if derived_name is None:
            bad.append(f"U+{cp:04X} が派生フォントに無い")
            continue
        advance = derived["hmtx"][derived_name][0]
        if advance != HALF_WIDTH:
            bad.append(f"U+{cp:04X} advance={advance} (期待 {HALF_WIDTH})")
    if len(set(source_names)) != len(source_names):
        bad.append("原本の対象グリフ名が重複")
    derived_names = [derived_cmap.get(cp) for cp in sorted(TARGETS)]
    present_names = [name for name in derived_names if name is not None]
    if len(set(present_names)) != len(present_names):
        bad.append("派生フォントの対象グリフ名が重複")
    return bad


def check_geometry(derived, original, style="Regular"):
    """Check simple target geometry, bounds, advance, and lsb."""
    del original
    bad = []
    cmap = derived.getBestCmap()
    glyf = derived["glyf"]
    for cp in sorted(TARGETS):
        name = cmap.get(cp)
        if name is None:
            continue
        glyph = glyf[name]
        if glyph.numberOfContours < 0:
            bad.append(f"U+{cp:04X} が複合グリフ")
            continue
        if glyph.numberOfContours == 0:
            bad.append(f"U+{cp:04X} が空グリフ")
            continue
        program = getattr(glyph, "program", None)
        if program is not None and program.getBytecode():
            bad.append(f"U+{cp:04X} にinstructionが残っている")
        x_min, y_min, x_max, y_max = _bounds(derived, glyph)
        if x_min < 0 or x_max > HALF_WIDTH:
            bad.append(
                f"U+{cp:04X} ink=[{x_min},{x_max}] "
                f"(期待 [0,{HALF_WIDTH}])"
            )
        if x_max <= x_min or y_max <= y_min:
            bad.append(f"U+{cp:04X} boundsが空")
        if derived["hmtx"][name][0] != HALF_WIDTH:
            bad.append(f"U+{cp:04X} advanceが525ではない")
        if derived["hmtx"][name][1] != x_min:
            bad.append(f"U+{cp:04X} lsb={derived['hmtx'][name][1]} (期待 xMin={x_min})")
        width = x_max - x_min
        center_x = (x_min + x_max) / 2
        if abs(width - HALF_WIDTH) > 1:
            bad.append(f"U+{cp:04X} ink幅={width} (期待 {HALF_WIDTH}±1)")
        if abs(center_x - HALF_WIDTH / 2) > 1:
            bad.append(f"U+{cp:04X} center_x={center_x} (期待 262.5±1)")
        if cp in (*CIRCLE_CODEPOINTS, NOTE_CODEPOINT, WARNING_CODEPOINT):
            expected_y_min, expected_y_max = CJK_VERTICAL_BOXES[style]
            height = y_max - y_min
            center_y = (y_min + y_max) / 2
            if abs(y_min - expected_y_min) > 1 or abs(y_max - expected_y_max) > 1:
                bad.append(
                    f"U+{cp:04X} y=({y_min},{y_max}) "
                    f"(期待 ({expected_y_min},{expected_y_max})±1)"
                )
            if abs(center_y - (expected_y_min + expected_y_max) / 2) > 1:
                bad.append(
                    f"U+{cp:04X} center_y={center_y} "
                    f"(期待 {(expected_y_min + expected_y_max) / 2}±1)"
                )
    return bad


def check_source_contract(derived, source, style, own_source=None):
    """Check exact transformed source outlines for every adopted glyph."""
    bad = []
    if own_source is None:
        own_source = source
    if source["head"].unitsPerEm != derived["head"].unitsPerEm:
        bad.append(f"{style} source/destination UPMが一致しない")
    derived_cmap = derived.getBestCmap()
    source_cmap = source.getBestCmap()
    own_cmap = own_source.getBestCmap()
    for cp in sorted(TARGETS):
        derived_name = derived_cmap.get(cp)
        expected_source = source if cp in CIRCLE_CODEPOINTS else own_source
        expected_cmap = source_cmap if cp in CIRCLE_CODEPOINTS else own_cmap
        source_name = expected_cmap.get(cp)
        if derived_name is None or source_name is None:
            continue
        source_glyph = expected_source["glyf"][source_name]
        program = getattr(source_glyph, "program", None)
        if source_glyph.numberOfContours < 0:
            bad.append(f"{style} U+{cp:04X} sourceが複合グリフ")
            continue
        if (
            program is not None
            and program.getBytecode()
            and cp != ELLIPSIS_CODEPOINT
        ):
            bad.append(f"{style} U+{cp:04X} sourceにinstructionがある")
            continue
        rule = (
            "core"
            if cp in CIRCLE_CODEPOINTS
            else "fit-cjk"
            if cp == NOTE_CODEPOINT
            else "fit-cjk"
            if cp == WARNING_CODEPOINT
            else "fit-ellipsis"
        )
        expected = transformed_glyph(expected_source, cp, rule, style=style)
        actual = derived["glyf"][derived_name]
        if _glyph_signature(actual) != _glyph_signature(expected):
            bad.append(
                f"{style} U+{cp:04X} が期待source/rule ({rule}) と一致しない"
            )
    return bad


def check_others_untouched(derived, original):
    """Check outline and hmtx identity for every non-target glyph."""
    targets = target_glyph_names(original)
    src_order, dst_order = original.getGlyphOrder(), derived.getGlyphOrder()
    if src_order != dst_order:
        return ["グリフ順が原本と違う"]
    src_glyf, dst_glyf = original["glyf"], derived["glyf"]
    changed = []
    for name in src_order:
        if name in targets:
            continue
        diagnostics = []
        if src_glyf[name].compile(src_glyf) != dst_glyf[name].compile(dst_glyf):
            diagnostics.append(f"{name} の輪郭が原本と違う")
        if original["hmtx"][name] != derived["hmtx"][name]:
            diagnostics.append(f"{name} の hmtx が原本と違う")
        if diagnostics:
            changed.append(diagnostics)

    selected = []
    for diagnostics in changed:
        if len(diagnostics) == 2:
            while sum(len(group) for group in selected) + 2 > 6:
                single_index = next(
                    (
                        index
                        for index in range(len(selected) - 1, -1, -1)
                        if len(selected[index]) == 1
                    ),
                    None,
                )
                if single_index is None:
                    break
                selected.pop(single_index)
            if sum(len(group) for group in selected) + 2 <= 6:
                selected.append(diagnostics)
        elif sum(len(group) for group in selected) < 6:
            selected.append(diagnostics)
    return [line for group in selected for line in group]


def check_renamed(derived, original, style="Regular"):
    """Check final name records and metadata preservation."""
    bad = []
    subfamily = "Bold Italic" if style == "BoldItalic" else style
    expected_by_id = {
        1: FINAL_FAMILY,
        2: subfamily,
        3: f"Version 2.0.0; Moralerspace-derived; {FINAL_FAMILY}; {subfamily}",
        4: f"{FINAL_FAMILY} {subfamily}",
        6: f"{FINAL_STEM}-{style}",
        16: FINAL_FAMILY,
        17: subfamily,
    }
    source_records = [
        (
            (record.nameID, record.platformID, record.platEncID, record.langID),
            record.toUnicode(),
        )
        for record in original["name"].names
    ]
    derived_records = [
        (
            (record.nameID, record.platformID, record.platEncID, record.langID),
            record.toUnicode(),
        )
        for record in derived["name"].names
    ]
    source_metadata = [
        metadata for metadata, _ in source_records if metadata[0] not in {16, 17}
    ]
    derived_metadata = [
        metadata for metadata, _ in derived_records if metadata[0] not in {16, 17}
    ]
    if derived_metadata != source_metadata:
        bad.append("name record metadata differs from original")
    source_preserved = [
        (metadata, value)
        for metadata, value in source_records
        if metadata[0] not in {16, 17}
    ]
    derived_preserved = [
        (metadata, value)
        for metadata, value in derived_records
        if metadata[0] not in {16, 17}
    ]
    for index, ((source_meta, source_value), (derived_meta, derived_value)) in enumerate(
        zip(source_preserved, derived_preserved)
    ):
        expected = expected_by_id.get(
            source_meta[0],
            source_value.replace(SRC_FAMILY, FINAL_FAMILY).replace(
                SRC_STEM, FINAL_STEM
            ),
        )
        if source_meta != derived_meta:
            bad.append(f"name record metadata differs at index {index}")
        if derived_value != expected:
            bad.append(f"name record {derived_meta} 文字列が期待値と違う")
        if (
            SRC_FAMILY in derived_value
            or SRC_STEM in derived_value
        ):
            bad.append(f"name record {derived_meta} に旧名が残っている")
    if not any(
        metadata[0] == 1 and FINAL_FAMILY in value
        for metadata, value in derived_records
    ):
        bad.append("name ID 1 に派生ファミリ名が無い")
    for name_id, expected in expected_by_id.items():
        if not any(
            record.nameID == name_id and record.toUnicode() == expected
            for record in derived["name"].names
        ):
            bad.append(f"name ID {name_id} が期待値と違う")
    return bad


CHECKS = (
    ("1. 対象の advance/cmap", check_advance),
    ("2. 対象の geometry", check_geometry),
    ("3. source glyph contract", check_source_contract),
    ("4. 対象以外は原本と一致", check_others_untouched),
    ("5. final name table", check_renamed),
)


def break_one_non_target(font):
    """Break both outline and hmtx for a non-target positive-control glyph."""
    targets = target_glyph_names(font)
    for name in font.getGlyphOrder():
        glyph = font["glyf"][name]
        if (
            name not in targets
            and glyph.numberOfContours > 0
            and len(glyph.coordinates) > 0
        ):
            x, y = glyph.coordinates[0]
            glyph.coordinates[0] = (x + 1, y)
            advance, lsb = font["hmtx"][name]
            font["hmtx"][name] = (advance + 1, lsb)
            return name
    raise ValueError("control requires a non-target simple glyph")


def _break_target_advance(font):
    name = font.getBestCmap()[sorted(TARGETS)[0]]
    advance, lsb = font["hmtx"][name]
    font["hmtx"][name] = (advance + 1, lsb)


def _break_target_geometry(font):
    name = font.getBestCmap()[CIRCLE_CODEPOINTS[0]]
    glyph = font["glyf"][name]
    x, y = glyph.coordinates[0]
    glyph.coordinates[0] = (x - HALF_WIDTH - 1, y)


def _break_source_contract(font):
    name = font.getBestCmap()[CIRCLE_CODEPOINTS[0]]
    glyph = font["glyf"][name]
    x, y = glyph.coordinates[0]
    glyph.coordinates[0] = (x + 1, y)


def _break_name(font):
    for record in font["name"].names:
        value = record.toUnicode()
        if FINAL_FAMILY in value or FINAL_STEM in value:
            record.string = value.replace(FINAL_FAMILY, SRC_FAMILY).replace(
                FINAL_STEM, SRC_STEM
            ).encode(record.getEncoding())


def _check_problems(check, derived, source, style, original):
    """Run one check with the same source arguments used by normal verification."""
    if check is check_source_contract:
        return check(derived, source, style, original)
    if check is check_geometry:
        return check(derived, original, style)
    if check is check_renamed:
        return check(derived, original, style)
    return check(derived, original)


def _control_variants():
    """Return fresh mutation/check pairs so tests can replace a mutation."""
    return (
        (_break_target_advance, check_advance),
        (_break_target_geometry, check_geometry),
        (_break_source_contract, check_source_contract),
        (break_one_non_target, check_others_untouched),
        (_break_name, check_renamed),
    )


def run(out_dir: Path, control: bool) -> bool:
    out_dir = Path(out_dir)
    ok = True
    for style in STYLES:
        original_path = SRC_DIR / f"{SRC_STEM}-{style}.ttf"
        derived_path = out_dir / f"{FINAL_STEM}-{style}.ttf"
        source_style = CIRCLE_SOURCE_STYLES[style]
        source_path = SRC_DIR / f"{SRC_STEM}-{source_style}.ttf"
        original = TTFont(original_path)
        source = original if source_style == style else TTFont(source_path)
        try:
            if control:
                print(f"== {style} [陽性対照]")
                for (mutate, check), (check_name, _) in zip(
                    _control_variants(), CHECKS
                ):
                    derived = TTFont(derived_path)
                    try:
                        baseline_problems = _check_problems(
                            check, derived, source, style, original
                        )
                        if baseline_problems:
                            print(f"  [FAIL] {check_name} baseline不正")
                            for line in baseline_problems[:6]:
                                print(f"         {line}")
                            ok = False
                            continue
                        mutate(derived)
                        problems = _check_problems(
                            check, derived, source, style, original
                        )
                    finally:
                        derived.close()
                    passed = bool(problems)
                    print(f"  [{'PASS' if passed else 'FAIL'}] {check_name}")
                    for line in problems[:6]:
                        print(f"         {line}")
                    ok = ok and passed
                continue

            derived_path = out_dir / f"{FINAL_STEM}-{style}.ttf"
            derived = TTFont(derived_path)
            try:
                print(f"== {style}")
                for check_name, check in CHECKS:
                    problems = _check_problems(
                        check, derived, source, style, original
                    )
                    failed = bool(problems)
                    print(f"  [{'PASS' if not failed else 'FAIL'}] {check_name}")
                    for line in problems[:6]:
                        print(f"         {line}")
                    ok = ok and not failed
            finally:
                derived.close()
        finally:
            if source is not original:
                source.close()
            original.close()
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default="build")
    parser.add_argument("--control", action="store_true")
    args = parser.parse_args(argv)
    for style in STYLES:
        source_path = SRC_DIR / f"{SRC_STEM}-{style}.ttf"
        if not source_path.is_file():
            print(f"error: source font not found: {source_path}", file=sys.stderr)
            return 2
    for style in STYLES:
        path = Path(args.out_dir) / f"{FINAL_STEM}-{style}.ttf"
        if not path.is_file():
            print(f"error: derived font not found: {path}", file=sys.stderr)
            return 2
    return 0 if run(Path(args.out_dir), args.control) else 1


if __name__ == "__main__":
    raise SystemExit(main())
