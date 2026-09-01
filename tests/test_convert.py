import math
import os

import ezdxf
import pytest
from pypdf import PdfReader

from cad2pdf.converter import convert_dxf_to_pdf, MM_PER_INCH, UNITS_TO_MM


def _page_size_mm(pdf_path):
    box = PdfReader(pdf_path).pages[0].mediabox
    return float(box.width) / 72 * MM_PER_INCH, float(box.height) / 72 * MM_PER_INCH


def _make_dxf(path, width=1000.0, height=500.0):
    """A 1000x500 mm rectangle (in mm units) with some detail, as a
    stand-in for a real CAD drawing."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    )
    msp.add_circle(center=(width / 2, height / 2), radius=min(width, height) / 4)
    msp.add_text("TEST", dxfattribs={"height": 20}).set_placement((10, 10))
    doc.saveas(path)
    return width, height


def test_explicit_scale_matches_page_geometry(tmp_path):
    dxf_path = tmp_path / "rect.dxf"
    pdf_path = tmp_path / "rect.pdf"
    width_mm, height_mm = _make_dxf(dxf_path, width=1000.0, height=500.0)

    result = convert_dxf_to_pdf(
        str(dxf_path), str(pdf_path),
        scale="1:50", paper="A3", orientation="landscape", units="mm",
    )

    assert os.path.exists(pdf_path)
    assert pdf_path.read_bytes()[:4] == b"%PDF"
    assert result.scale_denominator == 50.0
    assert result.fit_mode is False
    assert result.drawing_extents_mm == pytest.approx((1000.0, 500.0))

    # At 1:50 a 1000x500mm drawing becomes 20x10mm on paper - must fit
    # comfortably within an A3 sheet (297x420mm).
    plotted_w = width_mm / 50.0
    plotted_h = height_mm / 50.0
    assert plotted_w <= 420.0
    assert plotted_h <= 297.0

    # The physical PDF page itself must be exactly A3 landscape - if a
    # renderer step silently resizes/crops the figure (e.g. matplotlib's
    # autoscale-driven auto-resize), the printed scale becomes a lie even
    # though the reported ConversionResult still looks correct.
    page_w_mm, page_h_mm = _page_size_mm(pdf_path)
    assert page_w_mm == pytest.approx(420.0, abs=0.5)
    assert page_h_mm == pytest.approx(297.0, abs=0.5)


def test_auto_fit_picks_standard_scale(tmp_path):
    dxf_path = tmp_path / "big.dxf"
    pdf_path = tmp_path / "big.pdf"
    _make_dxf(dxf_path, width=20000.0, height=8000.0)  # 20m x 8m building

    result = convert_dxf_to_pdf(
        str(dxf_path), str(pdf_path), paper="A4", units="mm",
    )

    assert result.fit_mode is True
    from cad2pdf.converter import STANDARD_SCALES
    assert result.scale_denominator in STANDARD_SCALES

    avail_w = 297 - 2 * 10  # landscape A4 minus default margins, or portrait
    avail_h = 210 - 2 * 10
    plotted_w = 20000.0 / result.scale_denominator
    plotted_h = 8000.0 / result.scale_denominator
    fits_landscape = plotted_w <= avail_w + 1e-6 and plotted_h <= avail_h + 1e-6
    fits_portrait = plotted_w <= avail_h + 1e-6 and plotted_h <= avail_w + 1e-6
    assert fits_landscape or fits_portrait


def test_scale_too_coarse_for_paper_raises(tmp_path):
    dxf_path = tmp_path / "huge.dxf"
    pdf_path = tmp_path / "huge.pdf"
    _make_dxf(dxf_path, width=100000.0, height=50000.0)

    with pytest.raises(ValueError, match="does not fit"):
        convert_dxf_to_pdf(
            str(dxf_path), str(pdf_path), scale="1:1", paper="A4", units="mm",
        )


def test_units_conversion_affects_required_scale(tmp_path):
    # Same numeric extents, but interpreted as metres instead of mm, means
    # a 1000x correction is needed - should force a much coarser auto scale.
    dxf_path = tmp_path / "meters.dxf"
    pdf_mm = tmp_path / "as_mm.pdf"
    pdf_m = tmp_path / "as_m.pdf"
    _make_dxf(dxf_path, width=20.0, height=10.0)

    result_mm = convert_dxf_to_pdf(str(dxf_path), str(pdf_mm), paper="A4", units="mm")
    result_m = convert_dxf_to_pdf(str(dxf_path), str(pdf_m), paper="A4", units="m")

    assert result_m.scale_denominator > result_mm.scale_denominator


def test_geometry_is_actually_visible_on_the_page(tmp_path):
    """
    Regression test: ezdxf defaults to a DARK model-space background, which
    resolves the default entity colour (ACI 7) to WHITE. Rendered onto a
    white sheet that produces a page that is valid, correctly sized, and
    completely blank. Assert real dark ink lands on the page.
    """
    pytest.importorskip("PIL")
    from PIL import Image

    dxf_path = tmp_path / "visible.dxf"
    pdf_path = tmp_path / "visible.pdf"
    png_path = tmp_path / "visible.png"
    _make_dxf(dxf_path, width=1000.0, height=500.0)

    convert_dxf_to_pdf(
        str(dxf_path), str(pdf_path), scale="1:10", paper="A4", units="mm",
        show_scale_label=False, preview_path=str(png_path),
    )

    img = Image.open(png_path).convert("L")
    pixels = img.tobytes()  # one byte per pixel in mode "L"
    # Threshold is "any ink at all" rather than "dark": CAD linework is
    # hairline-thin, so at preview resolution most stroke pixels antialias
    # to light grey. The bug being guarded against renders the page *pure*
    # white (255 everywhere), so any ink is a decisive signal.
    inked = sum(1 for p in pixels if p < 250)
    assert inked > 500, (
        f"only {inked} inked pixels - the drawing rendered blank or invisible"
    )
    # ...and at least some of it should be properly dark, not washed out.
    assert min(pixels) < 160, f"darkest pixel is {min(pixels)} - nothing solid drawn"


def test_missing_geometry_raises(tmp_path):
    dxf_path = tmp_path / "empty.dxf"
    pdf_path = tmp_path / "empty.pdf"
    doc = ezdxf.new("R2010")
    doc.saveas(dxf_path)

    with pytest.raises(ValueError, match="no visible geometry"):
        convert_dxf_to_pdf(str(dxf_path), str(pdf_path))
