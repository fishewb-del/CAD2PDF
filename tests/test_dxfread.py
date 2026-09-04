"""
Tests for tolerant DXF loading.

The case that drove this: a DWG run through LibreDWG's dwg2dxf came back
with the second line of a multi-line note sitting where a group code
belongs, and ezdxf.readfile() refused the whole drawing with

    Invalid group code "N GROUP FACILITY SOLUTIONS, INC. ..." at line 95113.

Nothing was wrong with the geometry. These tests pin down that such a file
now loads, keeps its text, and reports that it was repaired.
"""

import io

import ezdxf
import ezdxf.recover
import pytest
from ezdxf.lldxf.const import DXFStructureError

from app import app as flask_app
from cad2pdf.converter import convert_dxf_to_pdf, render_preview
from cad2pdf.dxfread import DxfReadError, read_dxf, stitch_wrapped_values

NOTE_LINE_1 = "CONTRACTOR SHALL REMOVE ALL DEBRIS FROM SITE AND RETURN KEYS TO"
NOTE_LINE_2 = "N GROUP FACILITY SOLUTIONS, INC. ON COMPLETION OF WORK, IF REQUESTED."


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _write_dxf(path, text=NOTE_LINE_1):
    """A small but complete drawing with one TEXT entity."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 500), (0, 500), (0, 0)])
    msp.add_text(text, dxfattribs={"height": 20}).set_placement((10, 10))
    doc.saveas(path)
    return path


def _wrap_text_value(path, extra_lines=(NOTE_LINE_2,)):
    """
    Break a string value across lines, the way dwg2dxf does with a note.

    The extra lines land in the group-code position, which is exactly the
    corruption that used to sink the whole file.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        out.append(line)
        if line.strip() == NOTE_LINE_1:
            out.extend(extra + "\n" for extra in extra_lines)
    path.write_text("".join(out), encoding="utf-8")
    return path


def _texts(doc):
    return [e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"]


def test_the_reported_file_shape_is_rejected_by_strict_ezdxf(tmp_path):
    """Guard the premise: without repair this really does fail."""
    path = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))
    with pytest.raises(DXFStructureError) as exc:
        ezdxf.readfile(str(path))
    assert "Invalid group code" in str(exc.value)


def test_clean_file_is_read_untouched(tmp_path):
    loaded = read_dxf(str(_write_dxf(tmp_path / "clean.dxf")))
    assert loaded.strategy == "clean"
    assert loaded.repaired is False
    assert loaded.note is None
    assert _texts(loaded.doc) == [NOTE_LINE_1]


def test_wrapped_text_value_is_stitched_back_together(tmp_path):
    path = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))

    loaded = read_dxf(str(path))

    assert loaded.strategy == "stitched"
    assert loaded.repaired is True
    # No data loss: both halves of the note survive, on one line.
    assert _texts(loaded.doc) == [f"{NOTE_LINE_1} {NOTE_LINE_2}"]
    # The geometry is the whole point - it must come through intact.
    assert sum(1 for e in loaded.doc.modelspace()) == 2
    assert loaded.note and "split across two lines" in loaded.note


def test_a_value_wrapped_over_several_lines_is_fully_rejoined(tmp_path):
    extra = ("SECOND LINE OF THE NOTE", "THIRD LINE OF THE NOTE")
    path = _wrap_text_value(_write_dxf(tmp_path / "multi.dxf"), extra_lines=extra)

    loaded = read_dxf(str(path))

    assert loaded.strategy == "stitched"
    assert _texts(loaded.doc) == [" ".join((NOTE_LINE_1,) + extra)]
    assert "2 long text values" in loaded.note


def test_stitching_counts_only_the_lines_it_rejoins(tmp_path):
    src = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))
    dst = tmp_path / "stitched.dxf"
    assert stitch_wrapped_values(str(src), str(dst)) == 1

    clean = _write_dxf(tmp_path / "clean.dxf")
    assert stitch_wrapped_values(str(clean), str(tmp_path / "copy.dxf")) == 0


def test_stitching_leaves_a_clean_file_byte_for_byte_readable(tmp_path):
    """A copy of a valid file must still be a valid file."""
    src = _write_dxf(tmp_path / "clean.dxf")
    dst = tmp_path / "copy.dxf"
    stitch_wrapped_values(str(src), str(dst))
    assert _texts(ezdxf.readfile(str(dst))) == [NOTE_LINE_1]


def test_a_hard_wrap_at_the_255_byte_limit_rejoins_with_no_gap(tmp_path):
    """
    The real failure from the field. dwg2dxf writes a value longer than the
    255-byte DXF string limit by wrapping the line mid-word, so the halves
    must be rejoined with nothing between them. Putting a space there would
    quietly corrupt the text, and would break an MTEXT formatting code that
    straddles the split.
    """
    head = "THIS DRAWING IS THE PROPERTY OF DESIGN GROUP FACILITY SOLUTIONS"
    head = head + "X" * (255 - len(head) - 5) + "DESIG"
    assert len(head) == 255
    tail = "N GROUP FACILITY SOLUTIONS, INC. ON COMPLETION OF WORK."

    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 0)])
    doc.modelspace().add_text(head + tail, dxfattribs={"height": 5})
    path = tmp_path / "wrapped255.dxf"
    doc.saveas(path)

    # Re-wrap the way dwg2dxf does: cut the value at exactly 255 bytes.
    text = path.read_text(encoding="utf-8")
    assert head + tail in text
    path.write_text(text.replace(head + tail, head + "\n" + tail), encoding="utf-8")

    loaded = read_dxf(str(path))

    assert loaded.strategy == "stitched"
    assert _texts(loaded.doc) == [head + tail]
    assert "DESIGN GROUP" in _texts(loaded.doc)[0]
    assert "DESIG N GROUP" not in _texts(loaded.doc)[0]


def test_numeric_looking_text_is_not_mistaken_for_a_group_code(tmp_path):
    """
    A wrapped line that happens to be a bare number is ambiguous, but a
    line that is out of the group-code range is not - it is text.
    """
    path = _wrap_text_value(_write_dxf(tmp_path / "numeric.dxf"),
                            extra_lines=("99999",))
    loaded = read_dxf(str(path))
    assert loaded.strategy == "stitched"
    assert _texts(loaded.doc) == [f"{NOTE_LINE_1} 99999"]


def test_a_recoverable_file_reports_that_it_was_repaired(tmp_path):
    """Structural damage short of a bad group code takes the recover path."""
    path = _write_dxf(tmp_path / "trunc.dxf")
    text = path.read_text(encoding="utf-8")
    # Drop the terminating EOF tag: valid tags, invalid structure.
    path.write_text(text.replace("  0\nEOF\n", ""), encoding="utf-8")

    loaded = read_dxf(str(path))

    assert loaded.repaired is True
    assert loaded.strategy in ("recovered", "stitched", "salvaged")
    assert loaded.note


def test_hopeless_file_raises_a_read_error(tmp_path):
    path = tmp_path / "junk.dxf"
    path.write_bytes(b"this is not a dxf file at all\n" * 50)
    with pytest.raises(DxfReadError):
        read_dxf(str(path))


def test_a_missing_file_still_raises_ioerror(tmp_path):
    with pytest.raises(IOError):
        read_dxf(str(tmp_path / "nope.dxf"))


# --- through the converter and the web app --------------------------------

def test_wrapped_file_converts_to_pdf_and_reports_the_repair(tmp_path):
    path = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))
    pdf_path = tmp_path / "out.pdf"

    result = convert_dxf_to_pdf(str(path), str(pdf_path), paper="A3", units="mm")

    assert pdf_path.read_bytes()[:4] == b"%PDF"
    assert result.repair_note and "split across two lines" in result.repair_note


def test_wrapped_file_previews_and_carries_the_note(tmp_path):
    path = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))
    preview = render_preview(str(path), units="mm")
    assert preview.repair_note
    # Folded into the note the viewer already displays.
    assert preview.repair_note in preview.note


def test_upload_of_a_wrapped_dxf_converts_instead_of_400(tmp_path, client):
    path = _wrap_text_value(_write_dxf(tmp_path / "wrapped.dxf"))
    data = {
        "file": (io.BytesIO(path.read_bytes()), "plan.dxf"),
        "paper": "A3",
        "units": "mm",
    }
    res = client.post("/api/convert", data=data,
                      content_type="multipart/form-data")

    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["pdf_b64"]
    assert "split across two lines" in payload["note"]


def test_unreadable_dxf_upload_explains_the_next_step(client):
    data = {"file": (io.BytesIO(b"not a dxf\n" * 50), "plan.dxf")}
    res = client.post("/api/convert", data=data,
                      content_type="multipart/form-data")

    assert res.status_code == 400
    error = res.get_json()["error"]
    assert "DXF" in error
    # The old message pasted ezdxf's parser error and stopped there.
    assert "Re-exporting" in error
