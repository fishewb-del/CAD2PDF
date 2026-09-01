"""
Tests for the drawing viewer: the preview you pan and zoom around before
committing to a conversion.
"""

import base64
import io

import ezdxf
import pytest

from app import app as flask_app
from cad2pdf.converter import render_preview


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _dxf_bytes(width=4800.0, height=3600.0, insunits=None, text=True):
    doc = ezdxf.new("R2010", setup=True)
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    )
    msp.add_circle(center=(width / 2, height / 2), radius=min(width, height) / 4)
    if text:
        msp.add_text("OFFICE 101", height=height / 30).set_placement((10, 10))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def _post(client, data_bytes, filename="plan.dxf", **fields):
    data = {"file": (io.BytesIO(data_bytes), filename)}
    data.update(fields)
    return client.post("/api/preview", data=data,
                       content_type="multipart/form-data")


def test_preview_returns_scalable_svg(client):
    body = _post(client, _dxf_bytes()).get_json()
    assert body["ok"] is True
    assert body["format"] == "svg"
    svg = body["svg"]
    # A viewBox with no fixed width/height is what lets the browser scale
    # it; keeping width="720pt" would pin the drawing to one size.
    assert "viewBox" in svg
    root = svg[: svg.index(">") + 1]
    assert "width=" not in root and "height=" not in root


def test_preview_reports_the_aspect_ratio(client):
    body = _post(client, _dxf_bytes(width=4800, height=2400)).get_json()
    # The viewer sizes its stage from this rather than trusting the browser
    # to infer an SVG's height, so it has to be right.
    assert body["aspect"] == pytest.approx(2.0, rel=0.02)


def test_preview_reads_units_from_the_drawing(client):
    body = _post(client, _dxf_bytes(insunits=1)).get_json()  # 1 = inches
    assert body["info"]["units"] == "in"
    assert body["info"]["units_autodetected"] is True
    # Imperial drawings read back in feet and inches, not millimetres.
    assert "'" in body["info"]["drawing_display"]


def test_preview_does_not_apply_paper_or_scale(client):
    """
    The viewer shows the drawing, not the plotted sheet, so nothing in the
    response should describe paper.
    """
    body = _post(client, _dxf_bytes()).get_json()
    assert "paper" not in body["info"]
    assert "scale" not in body["info"]


def test_preview_svg_carries_no_scripts_or_handlers(client):
    body = _post(client, _dxf_bytes()).get_json()
    svg = body["svg"].lower()
    # This markup is injected into the page, so it must never be able to
    # execute anything.
    assert "<script" not in svg
    assert "<foreignobject" not in svg
    assert "onload=" not in svg and "onclick=" not in svg


def test_dense_drawings_fall_back_to_a_raster_preview(tmp_path):
    """
    A drawing too dense to ship as vectors comes back as an image instead,
    with an explanation, rather than freezing the browser.
    """
    path = tmp_path / "plan.dxf"
    path.write_bytes(_dxf_bytes())
    result = render_preview(str(path), max_svg_bytes=200)
    assert result.format == "png"
    assert result.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.svg is None
    assert "high-resolution image" in result.note


def test_preview_rejects_a_non_cad_file(client):
    res = _post(client, b"not a drawing", filename="notes.txt")
    assert res.status_code == 400
    assert "dxf" in res.get_json()["error"].lower()


def test_preview_rejects_a_missing_file(client):
    res = client.post("/api/preview", data={},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_preview_reports_a_corrupt_drawing_cleanly(client):
    res = _post(client, b"0\nSECTION\ngarbage\n", filename="broken.dxf")
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["error"]
