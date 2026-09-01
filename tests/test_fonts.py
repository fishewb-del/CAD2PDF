"""
Regression tests for the font failure that made every drawing containing
text unconvertible on a deployed instance:

    Could not read this DXF file: no fonts available, not even fallback fonts

The drawing was never the problem. python:3.11-slim ships no system fonts,
ezdxf needs a real TrueType font to draw TEXT/MTEXT/dimensions, and its
font cache came up empty. Our own sample plan has no text in it, which is
exactly why nothing caught this.
"""

import ezdxf
import pytest
from ezdxf.fonts import fonts as ezdxf_fonts
from ezdxf.fonts.font_manager import FontNotFoundError

from cad2pdf import fontsetup
from cad2pdf.converter import convert_dxf_to_pdf, render_preview


@pytest.fixture
def fontless_host(monkeypatch):
    """
    Wipe every font ezdxf found, the way a slim container image looks.

    The font manager is module-level global state in ezdxf, so this saves
    and restores it rather than leaving other tests on a stripped cache.
    """
    manager = ezdxf_fonts.font_manager
    saved_cache = manager._font_cache
    saved_fallback = manager._fallback_font_name
    saved_ensured = fontsetup._ensured

    manager.clear()
    manager._fallback_font_name = ""
    fontsetup._ensured = False
    yield manager

    manager._font_cache = saved_cache
    manager._fallback_font_name = saved_fallback
    fontsetup._ensured = saved_ensured


def _drawing_with_text(path):
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (5000, 0), (5000, 3000), (0, 3000), (0, 0)])
    msp.add_text("OFFICE 101", height=150).set_placement((100, 100))
    msp.add_mtext("SLAB ON GRADE", dxfattribs={"char_height": 120}).set_location(
        (100, 500)
    )
    doc.saveas(path)
    return path


def test_a_fontless_host_really_does_break_ezdxf(fontless_host):
    """The failure this module exists to prevent, reproduced."""
    assert not fontsetup.has_usable_font()
    with pytest.raises(FontNotFoundError, match="no fonts available"):
        fontless_host.get_ttf_font("arial.ttf")


def test_ensure_fonts_recovers_a_fontless_host(fontless_host):
    assert fontsetup.ensure_fonts(force=True) is True
    assert fontsetup.has_usable_font()
    assert fontsetup.font_count() > 0
    # matplotlib bundles DejaVu, which is on ezdxf's own list of acceptable
    # fallbacks, so a font the drawing asks for by name now resolves.
    fontless_host.get_ttf_font("arial.ttf")
    assert fontsetup.fallback_font_name().lower().startswith("dejavu")


def test_text_drawing_converts_on_a_fontless_host(fontless_host, tmp_path):
    fontsetup.ensure_fonts(force=True)
    dxf = _drawing_with_text(tmp_path / "text.dxf")
    pdf = tmp_path / "text.pdf"
    convert_dxf_to_pdf(str(dxf), str(pdf), paper="ARCH D", units="mm")
    assert pdf.exists() and pdf.stat().st_size > 0


def test_text_is_drawn_not_silently_dropped(tmp_path):
    """
    Glyphs are rendered as outlines, so a drawing with text must produce
    substantially more vector paths than the same drawing without it. This
    catches the quieter failure mode where text is skipped and the plot
    comes out looking almost right.
    """
    import re

    with_text = _drawing_with_text(tmp_path / "with.dxf")

    doc = ezdxf.readfile(str(with_text))
    msp = doc.modelspace()
    for entity in list(msp):
        if entity.dxftype() in ("TEXT", "MTEXT"):
            msp.delete_entity(entity)
    doc.saveas(tmp_path / "without.dxf")

    svg_with = render_preview(str(with_text)).svg
    svg_without = render_preview(str(tmp_path / "without.dxf")).svg

    paths_with = len(re.findall(r"<path", svg_with))
    paths_without = len(re.findall(r"<path", svg_without))
    assert paths_with > paths_without, (paths_with, paths_without)

    # Glyph outlines carry a lot of path data, so the text version is not
    # merely bigger, it is dramatically bigger. A run of text that silently
    # rendered as nothing would not move this number.
    assert len(svg_with) > 3 * len(svg_without), (len(svg_with), len(svg_without))


def test_bundled_font_dir_exists():
    """matplotlib is a hard dependency, so this fallback is always there."""
    assert fontsetup.bundled_font_dir() is not None
