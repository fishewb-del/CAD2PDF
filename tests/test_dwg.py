"""
Tests for DWG handling.

The heavy path (a real DWG -> DXF conversion) needs LibreDWG's dwg2dxf
binary, so those tests skip cleanly when it isn't installed.
"""

import io
import os

import pytest

from app import app as flask_app
from cad2pdf.dwg import DwgConversionError, convert_dwg_to_dxf, dwg_available

requires_dwg = pytest.mark.skipif(
    not dwg_available(), reason="dwg2dxf (LibreDWG) not installed"
)

# A real DWG fixture is optional - point at one via this env var to run the
# full end-to-end check against actual CAD output.
SAMPLE_DWG = os.environ.get("CAD2PDF_SAMPLE_DWG")


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_garbage_dwg_raises_readable_error(tmp_path):
    if not dwg_available():
        pytest.skip("dwg2dxf not installed")
    dwg = tmp_path / "bad.dwg"
    dwg.write_bytes(b"definitely not a dwg file")
    with pytest.raises(DwgConversionError) as exc:
        convert_dwg_to_dxf(str(dwg), str(tmp_path / "out.dxf"))
    # The message must be actionable, not a raw exit code dump.
    assert "DXF" in str(exc.value)


def test_upload_of_corrupt_dwg_is_a_400_not_a_500(client):
    data = {"file": (io.BytesIO(b"not a real dwg"), "plan.dwg")}
    res = client.post("/api/convert", data=data,
                       content_type="multipart/form-data")
    assert res.status_code == 400
    payload = res.get_json()
    assert payload["ok"] is False
    assert payload["error"]


@requires_dwg
@pytest.mark.skipif(not SAMPLE_DWG, reason="set CAD2PDF_SAMPLE_DWG to run")
def test_real_dwg_converts_end_to_end(client):
    with open(SAMPLE_DWG, "rb") as fh:
        payload_bytes = fh.read()

    data = {"file": (io.BytesIO(payload_bytes), "sample.dwg"),
            "paper": "A3", "units": "auto"}
    res = client.post("/api/convert", data=data,
                       content_type="multipart/form-data")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["filename"] == "sample.pdf"
    assert payload["preview_b64"]
    # A real structural drawing has real extents and a sane fitted scale.
    w, h = payload["info"]["drawing_mm"]
    assert w > 0 and h > 0
    assert payload["info"]["scale_denominator"] > 0
