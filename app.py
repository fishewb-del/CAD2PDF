"""
cad2pdf web app.

A browser front-end for the accurate DXF -> PDF converter. Users upload a
drawing, pick a scale/paper size, and get back a true-vector, correctly
scaled PDF - no software to install on their machine.

The conversion itself is done by cad2pdf.converter, which is deliberately
kept free of any web/framework concerns.
"""

from __future__ import annotations

import base64
import os
import tempfile
import traceback

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from cad2pdf.converter import (
    PAPER_SIZES_MM,
    STANDARD_SCALES,
    UNITS_TO_MM,
    convert_dxf_to_pdf,
)
from cad2pdf.dwg import DwgConversionError, convert_dwg_to_dxf, dwg_available

MAX_UPLOAD_MB = int(os.environ.get("CAD2PDF_MAX_UPLOAD_MB", "32"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


@app.get("/")
def index():
    return render_template(
        "index.html",
        paper_sizes=sorted(PAPER_SIZES_MM),
        units=sorted(UNITS_TO_MM),
        standard_scales=STANDARD_SCALES,
        max_upload_mb=MAX_UPLOAD_MB,
        dwg_supported=dwg_available(),
    )


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


def _format_extent(mm: float, units: str) -> str:
    """
    Render a real-world length the way someone working in that unit system
    would read it: feet-and-inches for imperial drawings, metres (or mm)
    for metric ones. "47617.6 mm" is technically right but useless to an
    engineer whose drawing is dimensioned in feet.
    """
    if units in ("in", "ft"):
        total_in = mm / 25.4
        feet = int(total_in // 12)
        inches = total_in - feet * 12
        if round(inches) == 12:  # rounding rolled over
            feet += 1
            inches = 0.0
        return f"{feet}'-{inches:.0f}\""
    if mm >= 1000:
        return f"{mm / 1000:.2f} m"
    return f"{mm:.0f} mm"


def _form_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a numeric form field, rejecting junk and out-of-range values."""
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"'{name}' must be a number")
    if not (minimum <= value <= maximum):
        raise ValueError(f"'{name}' must be between {minimum} and {maximum}")
    return value


@app.post("/api/convert")
def api_convert():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(ok=False, error="Please choose a DXF file to convert."), 400

    filename = secure_filename(upload.filename)
    stem, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext == ".dwg" and not dwg_available():
        return jsonify(
            ok=False,
            error=(
                "DWG support isn't installed on this server. Convert the "
                "file to DXF first (free ODA File Converter, or 'Save As -> "
                "DXF' in AutoCAD / BricsCAD / LibreCAD), then upload the "
                "DXF. Geometry and scale are preserved either way."
            ),
        ), 400
    if ext not in (".dxf", ".dwg"):
        return jsonify(
            ok=False,
            error=(
                f"Unsupported file type '{ext or 'unknown'}'. "
                f"Please upload a .dxf or .dwg file."
            ),
        ), 400

    scale = (request.form.get("scale") or "").strip() or None
    paper = (request.form.get("paper") or "A4").strip()
    orientation = (request.form.get("orientation") or "auto").strip()
    units = (request.form.get("units") or "auto").strip()
    show_label = request.form.get("show_label", "true").lower() != "false"

    try:
        margin_mm = _form_float("margin", 10.0, 0.0, 200.0)
        line_width_scale = _form_float("line_width_scale", 1.0, 0.1, 10.0)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    # Everything lives in a per-request temp dir that is removed on exit,
    # so no uploaded drawing or generated PDF is retained on the server.
    with tempfile.TemporaryDirectory(prefix="cad2pdf-") as workdir:
        dxf_path = os.path.join(workdir, "input.dxf")
        pdf_path = os.path.join(workdir, "output.pdf")
        png_path = os.path.join(workdir, "preview.png")

        if ext == ".dwg":
            dwg_path = os.path.join(workdir, "input.dwg")
            upload.save(dwg_path)
            try:
                convert_dwg_to_dxf(dwg_path, dxf_path)
            except DwgConversionError as exc:
                return jsonify(ok=False, error=str(exc)), 400
        else:
            upload.save(dxf_path)

        try:
            result = convert_dxf_to_pdf(
                input_path=dxf_path,
                output_path=pdf_path,
                scale=scale,
                paper=paper,
                orientation=orientation,
                margin_mm=margin_mm,
                units=units,
                show_scale_label=show_label,
                line_width_scale=line_width_scale,
                preview_path=png_path,
                # Uploads are staged as input.dxf; the footer should name
                # the file the user actually uploaded.
                source_name=filename,
            )
        except ValueError as exc:
            # Expected, user-fixable problems (bad scale, drawing too big
            # for the page, empty drawing, unknown paper size).
            return jsonify(ok=False, error=str(exc)), 400
        except Exception as exc:  # noqa: BLE001 - surface a clean message
            app.logger.error("conversion failed: %s", traceback.format_exc())
            return jsonify(
                ok=False,
                error=f"Could not read this DXF file: {exc}",
            ), 400

        with open(pdf_path, "rb") as fh:
            pdf_b64 = base64.b64encode(fh.read()).decode("ascii")
        preview_b64 = None
        if os.path.exists(png_path):
            with open(png_path, "rb") as fh:
                preview_b64 = base64.b64encode(fh.read()).decode("ascii")

    return jsonify(
        ok=True,
        filename=f"{stem or 'drawing'}.pdf",
        pdf_b64=pdf_b64,
        preview_b64=preview_b64,
        info={
            "scale": f"1:{result.scale_denominator:g}",
            "scale_denominator": result.scale_denominator,
            "auto_scale": result.fit_mode,
            "paper": result.paper_size,
            "paper_mm": [round(v, 1) for v in result.paper_mm],
            "orientation": result.orientation,
            "units": result.drawing_units,
            "units_autodetected": result.units_autodetected,
            "drawing_mm": [round(v, 1) for v in result.drawing_extents_mm],
            "drawing_display": " × ".join(
                _format_extent(v, result.drawing_units)
                for v in result.drawing_extents_mm
            ),
            "plotted_mm": [
                round(result.drawing_extents_mm[0] / result.scale_denominator, 1),
                round(result.drawing_extents_mm[1] / result.scale_denominator, 1),
            ],
        },
    )


@app.errorhandler(RequestEntityTooLarge)
def too_large(_exc):
    return jsonify(
        ok=False,
        error=f"That file is larger than the {MAX_UPLOAD_MB} MB upload limit.",
    ), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("CAD2PDF_DEBUG")))
