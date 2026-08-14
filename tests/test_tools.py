import contextlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import make
import render_sample as render_sample_module
import verify
from PIL import Image
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools.ttLib.tables.O_S_2f_2 import Panose
from fontTools.ttLib.tables.ttProgram import Program


SRC_FAMILY = make.SRC_FAMILY
SRC_STEM = make.SRC_STEM
FINAL_FAMILY = make.FINAL_FAMILY
FINAL_STEM = make.FINAL_STEM
STYLES = make.STYLES
TARGETS = make.TARGETS
HALF_WIDTH = make.HALF_WIDTH
NON_TARGET_CODEPOINTS = (
    0x24EA,
    *range(0x2469, 0x2474),
    *range(0x2776, 0x277F),
    0x25CF,
    0x25CB,
    0x2713,
    0x2717,
    0x2192,
)


def _set_fields(table, fields):
    for name, value in fields.items():
        setattr(table, name, value)


def _simple_glyph(glyf, x_min, y_min, x_max, y_max):
    pen = TTGlyphPen(glyf)
    pen.moveTo((x_min, y_min))
    pen.lineTo((x_max, y_min))
    pen.lineTo((x_max, y_max))
    pen.lineTo((x_min, y_max))
    pen.closePath()
    glyph = pen.glyph()
    glyph.recalcBounds(glyf)
    return glyph


def load_fixture_in_memory(
    family=SRC_FAMILY,
    y_offset=0,
    missing_codepoint=None,
    composite_target=False,
):
    target_codepoints = sorted(TARGETS)
    target_names = {cp: f"uni{cp:04X}" for cp in target_codepoints}
    non_target_names = {cp: f"uni{cp:04X}" for cp in NON_TARGET_CODEPOINTS}
    glyph_order = [".notdef"] + [target_names[cp] for cp in target_codepoints]
    glyph_order += [non_target_names[cp] for cp in NON_TARGET_CODEPOINTS]
    glyph_order += ["A", "empty", "compound", "ellipsis"]

    glyf = newTable("glyf")
    glyf.glyphs = {}
    glyf.glyphOrder = glyph_order
    glyf.glyphs[".notdef"] = Glyph()
    glyf.glyphs["A"] = _simple_glyph(glyf, 100, 0, 700, 700)
    for codepoint in target_codepoints:
        name = target_names[codepoint]
        if composite_target and codepoint == make.CIRCLE_CODEPOINTS[0]:
            pen = TTGlyphPen(glyf)
            pen.addComponent("A", (1, 0, 0, 1, 0, 0))
            glyf.glyphs[name] = pen.glyph()
        else:
            glyph = _simple_glyph(
                glyf,
                64,
                -131 + y_offset,
                986,
                791 + y_offset,
            )
            if codepoint == make.ELLIPSIS_CODEPOINT:
                program = Program()
                program.fromBytecode([0])
                glyph.program = program
            glyf.glyphs[name] = glyph
    for codepoint in NON_TARGET_CODEPOINTS:
        glyf.glyphs[non_target_names[codepoint]] = _simple_glyph(
            glyf, 100, 0, 600, 500
        )
    glyf.glyphs["empty"] = Glyph()
    compound_pen = TTGlyphPen(glyf)
    compound_pen.addComponent("A", (1, 0, 0, 1, 0, 0))
    glyf.glyphs["compound"] = compound_pen.glyph()
    glyf.glyphs["ellipsis"] = _simple_glyph(glyf, 20, 20, 100, 100)

    font = TTFont()
    font.setGlyphOrder(glyph_order)
    font["glyf"] = glyf

    hmtx = newTable("hmtx")
    hmtx.metrics = {".notdef": (1000, 0)}
    hmtx.metrics.update(
        {target_names[cp]: (1050, 64) for cp in target_codepoints}
    )
    hmtx.metrics.update(
        {non_target_names[cp]: (525, 100) for cp in NON_TARGET_CODEPOINTS}
    )
    hmtx.metrics.update(
        {
            "A": (1000, 100),
            "empty": (1000, 0),
            "compound": (1000, 100),
            "ellipsis": (1000, 20),
        }
    )
    font["hmtx"] = hmtx

    head = newTable("head")
    _set_fields(
        head,
        {
            "tableVersion": 1.0,
            "fontRevision": 1.0,
            "checkSumAdjustment": 0,
            "magicNumber": 0x5F0F3CF5,
            "flags": 3,
            "unitsPerEm": 1000,
            "created": 3860000000,
            "modified": 3860000000,
            "xMin": 0,
            "yMin": -131 + y_offset,
            "xMax": 1050,
            "yMax": 791 + y_offset,
            "macStyle": 0,
            "lowestRecPPEM": 6,
            "fontDirectionHint": 2,
            "indexToLocFormat": 1,
            "glyphDataFormat": 0,
        },
    )
    font["head"] = head

    hhea = newTable("hhea")
    _set_fields(
        hhea,
        {
            "tableVersion": 0x10000,
            "ascent": 800,
            "descent": -200,
            "lineGap": 0,
            "advanceWidthMax": 1050,
            "minLeftSideBearing": 0,
            "minRightSideBearing": 0,
            "xMaxExtent": 986,
            "caretSlopeRise": 1,
            "caretSlopeRun": 0,
            "caretOffset": 0,
            "reserved0": 0,
            "reserved1": 0,
            "reserved2": 0,
            "reserved3": 0,
            "metricDataFormat": 0,
            "numberOfHMetrics": len(glyph_order),
        },
    )
    font["hhea"] = hhea

    maxp = newTable("maxp")
    _set_fields(
        maxp,
        {
            "tableVersion": 0x10000,
            "numGlyphs": len(glyph_order),
            "maxPoints": 4,
            "maxContours": 1,
            "maxCompositePoints": 4,
            "maxCompositeContours": 1,
            "maxZones": 2,
            "maxTwilightPoints": 0,
            "maxStorage": 0,
            "maxFunctionDefs": 0,
            "maxInstructionDefs": 0,
            "maxStackElements": 0,
            "maxSizeOfInstructions": 0,
            "maxComponentElements": 1,
            "maxComponentDepth": 1,
        },
    )
    font["maxp"] = maxp

    font["loca"] = newTable("loca")
    font["loca"].locations = [0] * (len(glyph_order) + 1)

    cmap = newTable("cmap")
    cmap.tableVersion = 0
    unicode_subtable = CmapSubtable.newSubtable(4)
    unicode_subtable.platformID = 3
    unicode_subtable.platEncID = 1
    unicode_subtable.language = 0
    unicode_subtable.cmap = {
        cp: target_names[cp]
        for cp in target_codepoints
        if cp != missing_codepoint
    }
    unicode_subtable.cmap.update(
        {cp: non_target_names[cp] for cp in NON_TARGET_CODEPOINTS}
    )
    unicode_subtable.cmap[0x41] = "A"
    cmap.tables = [unicode_subtable]
    font["cmap"] = cmap

    name = newTable("name")
    name.names = []
    name.setName(family, 1, 3, 1, 0x409)
    name.setName("Regular", 2, 3, 1, 0x409)
    name.setName(f"{family} Regular", 4, 3, 1, 0x409)
    name.setName(f"{SRC_STEM}-Regular", 6, 3, 1, 0x409)
    name.setName(f"{family} {family}", 3, 3, 1, 0x409)
    name.setName(family, 16, 3, 1, 0x409)
    name.setName("Regular", 17, 3, 1, 0x409)
    font["name"] = name

    post = newTable("post")
    _set_fields(
        post,
        {
            "formatType": 2.0,
            "italicAngle": 0,
            "underlinePosition": -100,
            "underlineThickness": 50,
            "isFixedPitch": 1,
            "minMemType42": 0,
            "maxMemType42": 0,
            "minMemType1": 0,
            "maxMemType1": 0,
        },
    )
    post.mapping = {}
    post.extraNames = []
    font["post"] = post

    os2 = newTable("OS/2")
    _set_fields(
        os2,
        {
            "version": 4,
            "xAvgCharWidth": 500,
            "usWeightClass": 400,
            "usWidthClass": 5,
            "fsType": 0,
            "ySubscriptXSize": 650,
            "ySubscriptYSize": 699,
            "ySubscriptXOffset": 0,
            "ySubscriptYOffset": 140,
            "ySuperscriptXSize": 650,
            "ySuperscriptYSize": 699,
            "ySuperscriptXOffset": 0,
            "ySuperscriptYOffset": 479,
            "yStrikeoutSize": 49,
            "yStrikeoutPosition": 258,
            "sFamilyClass": 0,
            "panose": Panose(),
            "ulUnicodeRange1": 0,
            "ulUnicodeRange2": 0,
            "ulUnicodeRange3": 0,
            "ulUnicodeRange4": 0,
            "achVendID": "NONE",
            "fsSelection": 0,
            "usFirstCharIndex": 0,
            "usLastCharIndex": 0,
            "sTypoAscender": 800,
            "sTypoDescender": -200,
            "sTypoLineGap": 0,
            "usWinAscent": 800,
            "usWinDescent": 200,
            "ulCodePageRange1": 0,
            "ulCodePageRange2": 0,
            "sxHeight": 500,
            "sCapHeight": 700,
            "usDefaultChar": 0,
            "usBreakChar": 32,
            "usMaxContext": 1,
        },
    )
    font["OS/2"] = os2

    serialized = io.BytesIO()
    font.save(serialized)
    serialized.seek(0)
    return TTFont(serialized)


def make_fixture_font(path: Path, family=SRC_FAMILY, y_offset=0, composite_target=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    font = load_fixture_in_memory(
        family=family,
        y_offset=y_offset,
        composite_target=composite_target,
    )
    font.save(path)
    font.close()


def _write_fixture_directory(directory):
    offsets = dict(zip(STYLES, (0, 30, 60, 90)))
    directory.mkdir(parents=True, exist_ok=True)
    for style in STYLES:
        make_fixture_font(
            directory / f"{SRC_STEM}-{style}.ttf",
            y_offset=offsets[style],
        )


def _build_fixture_directory(source_dir, output_dir):
    with patch.object(make, "SRC_DIR", source_dir):
        make.build_all(output_dir)


class RenderContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cells_reproduce_terminal_width_rule(self):
        self.assertEqual(render_sample_module.cells("①"), 1)
        self.assertEqual(render_sample_module.cells("※"), 1)
        self.assertEqual(render_sample_module.cells("⚠"), 1)
        self.assertEqual(render_sample_module.cells("あ"), 2)

    def test_sample_is_ai_cli_specific(self):
        sample = "\n".join(render_sample_module.SAMPLE)
        for text in (
            "①",
            "※",
            "⚠",
            "設定確認",
            "wait",
        ):
            self.assertIn(text, sample)
        self.assertLessEqual(len(render_sample_module.SAMPLE), 3)

    def test_render_creates_parent_and_valid_png(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        output = self.tmp_path / "nested" / "sample.png"
        with patch.object(render_sample_module, "SRC_DIR", source_dir):
            render_sample_module.render_sample(output_dir, output)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size[0], 1440)
            self.assertLessEqual(image.size[1], 800)

    def test_render_reports_missing_derived_style(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        (output_dir / f"{FINAL_STEM}-Regular.ttf").unlink()
        stderr = io.StringIO()
        with (
            patch.object(render_sample_module, "SRC_DIR", source_dir),
            redirect_stderr(stderr),
        ):
            status = render_sample_module.main([str(output_dir), str(self.tmp_path / "x.png")])
        self.assertEqual(status, 2)
        self.assertIn("derived font not found", stderr.getvalue())


class ToolContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_target_set_is_core_plus_note_and_adopted_candidates_only(self):
        self.assertEqual(
            TARGETS,
            frozenset(
                (
                    *make.CIRCLE_CODEPOINTS,
                    make.NOTE_CODEPOINT,
                    make.WARNING_CODEPOINT,
                    make.ELLIPSIS_CODEPOINT,
                )
            ),
        )
        self.assertNotIn(0x24EA, TARGETS)
        self.assertNotIn(0x2469, TARGETS)
        self.assertNotIn(0x2473, TARGETS)
        self.assertNotIn(0x2776, TARGETS)
        self.assertNotIn(0x277E, TARGETS)

    def test_source_and_final_destination_identity(self):
        self.assertEqual(SRC_STEM, "MoralerspaceNeonHW")
        self.assertEqual(SRC_FAMILY, "Moralerspace Neon HW")
        self.assertEqual(FINAL_STEM, "AgenticMonoJP")
        self.assertEqual(FINAL_FAMILY, "Agentic Mono JP")

    def test_license_declares_final_reserved_font_name(self):
        license_text = (Path(__file__).parents[1] / "LICENSE").read_text(encoding="utf-8")
        self.assertIn(
            f'Reserved Font Name "{FINAL_FAMILY}"',
            license_text,
        )

    def test_core_source_mapping_and_candidate_rules(self):
        self.assertEqual(
            make.CIRCLE_SOURCE_STYLES,
            {
                "Regular": "Bold",
                "Bold": "Bold",
                "Italic": "BoldItalic",
                "BoldItalic": "BoldItalic",
            },
        )
        self.assertEqual(make.rule_for(make.NOTE_CODEPOINT), "fit-cjk")
        self.assertEqual(make.rule_for(make.WARNING_CODEPOINT), "fit-cjk")
        self.assertEqual(make.rule_for(make.ELLIPSIS_CODEPOINT), "fit-ellipsis")

    def test_transform_rules_fit_cell_and_set_lsb(self):
        font = load_fixture_in_memory()
        for cp, rule in (
            (make.CIRCLE_CODEPOINTS[0], "core"),
            (make.NOTE_CODEPOINT, "fit-cjk"),
            (make.WARNING_CODEPOINT, "fit-cjk"),
            (make.ELLIPSIS_CODEPOINT, "fit-ellipsis"),
        ):
            glyph = make.transformed_glyph(font, cp, rule, style="Regular")
            glyph.recalcBounds(font["glyf"])
            self.assertGreaterEqual(glyph.xMin, 0)
            self.assertLessEqual(glyph.xMax, HALF_WIDTH)
            self.assertGreater(glyph.yMax, glyph.yMin)
            if cp != make.ELLIPSIS_CODEPOINT:
                expected_y_min, expected_y_max = make.CJK_VERTICAL_BOXES["Regular"]
                self.assertAlmostEqual(glyph.yMin, expected_y_min, delta=1)
                self.assertAlmostEqual(glyph.yMax, expected_y_max, delta=1)

    def test_cjk_vertical_boxes_are_explicit_per_style(self):
        self.assertEqual(make.CJK_VERTICAL_BOXES["Regular"], (-84, 850))
        self.assertEqual(make.CJK_VERTICAL_BOXES["Italic"], (-84, 850))
        self.assertEqual(make.CJK_VERTICAL_BOXES["Bold"], (-91, 858))
        self.assertEqual(make.CJK_VERTICAL_BOXES["BoldItalic"], (-91, 858))

    def test_build_uses_bold_sources_and_keeps_own_style_candidates(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        regular = TTFont(output_dir / f"{FINAL_STEM}-Regular.ttf")
        bold = TTFont(source_dir / f"{SRC_STEM}-Bold.ttf")
        regular_source = TTFont(source_dir / f"{SRC_STEM}-Regular.ttf")
        try:
            actual = regular["glyf"][regular.getBestCmap()[0x2460]]
            expected = make.transformed_glyph(
                bold, 0x2460, "core", style="Regular"
            )
            self.assertEqual(tuple(actual.coordinates), tuple(expected.coordinates))
            actual_note = regular["glyf"][regular.getBestCmap()[make.NOTE_CODEPOINT]]
            expected_note = make.transformed_glyph(
                regular_source, make.NOTE_CODEPOINT, "fit-cjk", style="Regular"
            )
            self.assertEqual(tuple(actual_note.coordinates), tuple(expected_note.coordinates))
            ellipsis_name = regular.getBestCmap()[make.ELLIPSIS_CODEPOINT]
            self.assertFalse(
                regular["glyf"][ellipsis_name].program.getBytecode()
            )
            self.assertGreater(
                len(
                    regular_source["glyf"][
                        regular_source.getBestCmap()[make.ELLIPSIS_CODEPOINT]
                    ].program.getBytecode()
                ),
                0,
            )
        finally:
            regular.close()
            bold.close()
            regular_source.close()

    def test_validate_source_rejects_missing_composite_and_alias(self):
        with self.assertRaises(make.BuildInputError):
            make.validate_source(
                load_fixture_in_memory(missing_codepoint=0x2460),
                "Regular",
            )
        with self.assertRaises(make.BuildInputError):
            make.validate_source(
                load_fixture_in_memory(composite_target=True),
                "Regular",
            )
        font = load_fixture_in_memory()
        primary = font["cmap"].tables[0]
        alias = CmapSubtable.newSubtable(4)
        alias.platformID = 0
        alias.platEncID = 3
        alias.language = 0
        alias.cmap = dict(primary.cmap)
        alias.cmap[0x2600] = primary.cmap[0x2460]
        font["cmap"].tables.append(alias)
        with self.assertRaisesRegex(make.BuildInputError, "alias"):
            make.validate_source(font, "Regular")

        font = load_fixture_in_memory()
        program = Program()
        program.fromBytecode([0])
        font["glyf"][font.getBestCmap()[0x2460]].program = program
        with self.assertRaisesRegex(make.BuildInputError, "instructions"):
            make.validate_source(font, "Regular")

        font = load_fixture_in_memory()
        font["head"].unitsPerEm = 900
        with self.assertRaisesRegex(make.BuildInputError, "UPM"):
            make.validate_source(font, "Regular")

    def test_rename_writes_final_name_records_and_preserves_metadata(self):
        font = load_fixture_in_memory()
        metadata = [
            (record.nameID, record.platformID, record.platEncID, record.langID)
            for record in font["name"].names
        ]
        self.assertGreater(make.rename(font, "Regular"), 0)
        self.assertEqual(
            metadata,
            [
                (record.nameID, record.platformID, record.platEncID, record.langID)
                for record in font["name"].names
            ],
        )
        self.assertTrue(any(FINAL_FAMILY in record.toUnicode() for record in font["name"].names))
        self.assertTrue(
            any(
                record.nameID == 6
                and record.toUnicode() == "AgenticMonoJP-Regular"
                for record in font["name"].names
            )
        )

    def test_all_styles_use_final_name_contract_and_filenames(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        for style in STYLES:
            path = output_dir / f"{FINAL_STEM}-{style}.ttf"
            self.assertTrue(path.is_file())
            font = TTFont(path)
            subfamily = "Bold Italic" if style == "BoldItalic" else style
            expected = {
                1: FINAL_FAMILY,
                2: subfamily,
                3: f"Version 2.0.0; Moralerspace-derived; {FINAL_FAMILY}; {subfamily}",
                4: f"{FINAL_FAMILY} {subfamily}",
                6: f"{FINAL_STEM}-{style}",
                16: FINAL_FAMILY,
                17: subfamily,
            }
            try:
                for name_id, value in expected.items():
                    self.assertTrue(
                        any(
                            record.nameID == name_id
                            and record.toUnicode() == value
                            for record in font["name"].names
                        ),
                        (style, name_id),
                    )
            finally:
                font.close()

    def test_verify_normal_and_control_runs(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        with patch.object(verify, "SRC_DIR", source_dir):
            self.assertTrue(verify.run(output_dir, False))
            self.assertTrue(verify.run(output_dir, True))

    def test_verify_control_rejects_noop_mutation_against_derived_baseline(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        with (
            patch.object(verify, "SRC_DIR", source_dir),
            patch.object(verify, "_break_target_advance", lambda font: None),
        ):
            self.assertFalse(verify.run(output_dir, True))

    def test_verify_control_rejects_invalid_derived_baseline(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        path = output_dir / f"{FINAL_STEM}-Regular.ttf"
        font = TTFont(path)
        name = font.getBestCmap()[make.CIRCLE_CODEPOINTS[0]]
        font["hmtx"][name] = (HALF_WIDTH + 1, font["hmtx"][name][1])
        font.save(path)
        font.close()
        with patch.object(verify, "SRC_DIR", source_dir):
            self.assertFalse(verify.run(output_dir, True))

    def test_verify_control_requires_derived_outputs(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        (output_dir / f"{FINAL_STEM}-Italic.ttf").unlink()
        stderr = io.StringIO()
        with patch.object(verify, "SRC_DIR", source_dir), redirect_stderr(stderr):
            self.assertEqual(verify.main([str(output_dir), "--control"]), 2)
        self.assertIn("derived font not found", stderr.getvalue())

    def test_non_target_identity_is_preserved(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        for style in STYLES:
            original = TTFont(source_dir / f"{SRC_STEM}-{style}.ttf")
            derived = TTFont(output_dir / f"{FINAL_STEM}-{style}.ttf")
            try:
                self.assertEqual(verify.check_others_untouched(derived, original), [])
                for cp in NON_TARGET_CODEPOINTS:
                    source_name = original.getBestCmap().get(cp)
                    if source_name is not None:
                        self.assertEqual(
                            original["hmtx"][source_name],
                            derived["hmtx"][source_name],
                        )
            finally:
                original.close()
                derived.close()

    def test_build_missing_last_source_has_no_partial_output(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        (source_dir / f"{SRC_STEM}-{STYLES[-1]}.ttf").unlink()
        output_dir.mkdir()
        with patch.object(make, "SRC_DIR", source_dir):
            with self.assertRaises(OSError):
                make.build_all(output_dir)
        self.assertEqual(list(output_dir.glob("*.ttf")), [])

    def test_build_rolls_back_existing_outputs_when_publish_fails(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        output_dir.mkdir()
        existing = {
            style: output_dir / f"{FINAL_STEM}-{style}.ttf"
            for style in STYLES
        }
        for style, path in existing.items():
            path.write_bytes(f"existing-{style}".encode())

        real_replace = make.os.replace
        publish_count = 0

        def fail_second_publish(source, destination):
            nonlocal publish_count
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.parent.name.startswith(".staging-")
                and destination_path.parent == output_dir
                and not source_path.name.startswith(".backup-")
            ):
                publish_count += 1
                if publish_count == 2:
                    raise OSError("simulated publish failure")
            return real_replace(source, destination)

        with (
            patch.object(make, "SRC_DIR", source_dir),
            patch.object(make.os, "replace", side_effect=fail_second_publish),
        ):
            with self.assertRaisesRegex(OSError, "simulated publish failure"):
                make.build_all(output_dir)
        self.assertEqual(publish_count, 2)
        for style, path in existing.items():
            self.assertEqual(path.read_bytes(), f"existing-{style}".encode())

    def test_verify_cli_rejects_missing_output(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        stderr = io.StringIO()
        with patch.object(verify, "SRC_DIR", source_dir), redirect_stderr(stderr):
            status = verify.main([str(output_dir)])
        self.assertEqual(status, 2)
        self.assertIn("derived font not found", stderr.getvalue())

    def test_verify_cli_detects_corrupt_output(self):
        source_dir = self.tmp_path / "fonts"
        output_dir = self.tmp_path / "build"
        _write_fixture_directory(source_dir)
        _build_fixture_directory(source_dir, output_dir)
        path = output_dir / f"{FINAL_STEM}-Regular.ttf"
        font = TTFont(path)
        name = font.getBestCmap()[0x2460]
        font["hmtx"][name] = (1050, font["hmtx"][name][1])
        font.save(path)
        font.close()
        with patch.object(verify, "SRC_DIR", source_dir):
            self.assertEqual(verify.main([str(output_dir)]), 1)
