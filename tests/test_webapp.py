import base64
import io

import ezdxf
import pytest
from pypdf import PdfReader

from app import _format_extent
from app import app as flask_app
from cad2pdf.converter import MM_PER_INCH


@pytest.mark.parametrize("mm,units,expected", [
    (304.8, "ft", "1'-0\""),        # exactly one foot
    (47617.575, "in", "156'-3\""),  # a real structural drawing's width
    (5000.0, "mm", "5.00 m"),
    (500.0, "mm", "500 mm"),
    (3657.6, "in", "12'-0\""),      # rounding must not produce 11'-12"
])
def test_format_extent_reads_naturally(mm, units, expected):
    assert _format_extent(mm, units) == expected


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _dxf_bytes(width=5000.0, height=3000.0, insunits=None):
    doc = ezdxf.new("R2010")
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    )
    msp.add_circle(center=(width / 2, height / 2), radius=min(width, height) / 4)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def _upload(client, data_bytes, filename="plan.dxf", **fields):
    data = {"file": (io.BytesIO(data_bytes), filename)}
    data.update(fields)
    return client.post("/api/convert", data=data,
                        content_type="multipart/form-data")


def test_index_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"CAD" in res.data


def test_healthz(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_convert_returns_scaled_pdf(client):
    res = _upload(client, _dxf_bytes(), scale="1:100", paper="A4", units="mm")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["filename"] == "plan.pdf"
    assert payload["info"]["scale"] == "1:100"
    assert payload["info"]["auto_scale"] is False
    # 5000x3000mm at 1:100 => 50x30mm on paper
    assert payload["info"]["plotted_mm"] == [50.0, 30.0]

    pdf = base64.b64decode(payload["pdf_b64"])
    assert pdf[:4] == b"%PDF"
    box = PdfReader(io.BytesIO(pdf)).pages[0].mediabox
    page_w = float(box.width) / 72 * MM_PER_INCH
    page_h = float(box.height) / 72 * MM_PER_INCH
    # A4, auto orientation -> landscape for a wide drawing
    assert sorted([round(page_w), round(page_h)]) == [210, 297]
    assert payload["preview_b64"]


def test_footer_names_the_uploaded_file_not_the_temp_file(client):
    """Uploads are staged as input.dxf server-side; the PDF footer must
    still identify the drawing the user actually uploaded."""
    res = _upload(client, _dxf_bytes(), filename="site-plan-rev-C.dxf",
                   scale="1:200", paper="A3", units="mm")
    payload = res.get_json()
    assert payload["ok"] is True

    pdf = base64.b64decode(payload["pdf_b64"])
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "site-plan-rev-C.dxf" in text
    assert "input.dxf" not in text


def test_units_autodetected_from_header(client):
    # $INSUNITS = 6 means metres.
    res = _upload(client, _dxf_bytes(width=20, height=10, insunits=6),
                   units="auto", paper="A4")
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["info"]["units"] == "m"
    assert payload["info"]["units_autodetected"] is True
    # 20m x 10m really is 20000x10000mm
    assert payload["info"]["drawing_mm"] == [20000.0, 10000.0]


def test_dwg_upload_gives_helpful_error(client):
    res = _upload(client, b"not really a dwg", filename="plan.dwg")
    assert res.status_code == 400
    assert "DXF" in res.get_json()["error"]


def test_wrong_extension_rejected(client):
    res = _upload(client, b"hello", filename="notes.txt")
    assert res.status_code == 400
    assert "Unsupported file type" in res.get_json()["error"]


def test_missing_file_rejected(client):
    res = client.post("/api/convert", data={},
                       content_type="multipart/form-data")
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_scale_too_coarse_reports_user_error(client):
    res = _upload(client, _dxf_bytes(), scale="1:1", paper="A4", units="mm")
    assert res.status_code == 400
    assert "does not fit" in res.get_json()["error"]


def test_corrupt_dxf_reports_clean_error(client):
    res = _upload(client, b"this is not a dxf file at all")
    assert res.status_code == 400
    payload = res.get_json()
    assert payload["ok"] is False
    assert payload["error"]


def test_bad_numeric_field_rejected(client):
    res = _upload(client, _dxf_bytes(), margin="not-a-number")
    assert res.status_code == 400
    assert "margin" in res.get_json()["error"]


def test_out_of_range_margin_rejected(client):
    res = _upload(client, _dxf_bytes(), margin="9999")
    assert res.status_code == 400
    assert "between" in res.get_json()["error"]
