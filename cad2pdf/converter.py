"""
Core conversion logic: DXF -> PDF with exact geometric accuracy and a true,
labeled print scale (e.g. 1:100), the same way a CAD plotter works.

Key idea for "keep all accuracy and scale":
  1. Never rasterize. Entities are drawn as vector paths straight into a
     matplotlib PDF backend, so lines/arcs/text stay mathematically exact
     (no pixelation, no lossy resampling).
  2. Never let matplotlib "auto-fit" the drawing to the page (that silently
     changes the scale). Instead we place the axes at a physical size, in
     inches, computed from the paper size and the chosen scale ratio, and
     set the data limits to the drawing's real extents. That guarantees
     1 drawing unit maps to an exact, known number of millimetres on paper.
  3. If the caller doesn't pick a scale, we choose the largest *standard*
     drafting scale (1:1, 1:2, 1:5, 1:10, 1:20 ... 1:5000) that still fits
     the page, rather than an arbitrary stretch factor like 1:137.42 -
     matching normal drafting practice.
  4. The chosen scale, drawing units and paper size are printed on the PDF
     itself, so the output is self-describing.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
from typing import Optional, Tuple

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf import bbox as ezdxf_bbox

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Paper sizes in millimetres, portrait (width, height).
PAPER_SIZES_MM = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
    "TABLOID": (279.4, 431.8),
}

# Drawing-unit -> millimetre conversion factors.
UNITS_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "ft": 304.8,
}

# Standard drafting scale denominators (1:N), ascending.
STANDARD_SCALES = [1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250,
                    500, 750, 1000, 1250, 2500, 5000, 10000]

MM_PER_INCH = 25.4


@dataclasses.dataclass
class ConversionResult:
    output_path: str
    scale_denominator: float
    paper_size: str
    paper_mm: Tuple[float, float]
    orientation: str
    drawing_units: str
    drawing_extents_mm: Tuple[float, float]
    fit_mode: bool


def _parse_scale(scale: Optional[str]) -> Optional[float]:
    """Parse a scale string like '1:100' or '100' into a denominator (100.0)."""
    if scale is None:
        return None
    s = str(scale).strip()
    if ":" in s:
        left, right = s.split(":", 1)
        left, right = float(left), float(right)
        if left <= 0 or right <= 0:
            raise ValueError(f"Invalid scale '{scale}': parts must be positive")
        return right / left
    value = float(s)
    if value <= 0:
        raise ValueError(f"Invalid scale '{scale}': must be positive")
    return value


def _get_paper_mm(paper: str, orientation: str) -> Tuple[float, float]:
    key = paper.strip().upper()
    if key in PAPER_SIZES_MM:
        w, h = PAPER_SIZES_MM[key]
    else:
        # Custom "WIDTHxHEIGHT" in mm, e.g. "500x700"
        if "x" not in key.lower():
            raise ValueError(
                f"Unknown paper size '{paper}'. Use one of "
                f"{sorted(PAPER_SIZES_MM)} or 'WIDTHxHEIGHT' in mm."
            )
        w_str, h_str = key.lower().split("x", 1)
        w, h = float(w_str), float(h_str)

    if orientation == "landscape":
        w, h = max(w, h), min(w, h)
    elif orientation == "portrait":
        w, h = min(w, h), max(w, h)
    elif orientation != "auto":
        raise ValueError("orientation must be 'auto', 'portrait' or 'landscape'")
    return w, h


def _drawing_extents(doc) -> Tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) of model space in drawing units."""
    msp = doc.modelspace()
    entities = [e for e in msp if e.dxftype() not in ("HATCH",) or True]
    cache = ezdxf_bbox.Cache()
    ext = ezdxf_bbox.extents(entities, cache=cache)
    if ext is None or not ext.has_data:
        raise ValueError("Drawing has no visible geometry in model space")
    xmin, ymin, _ = ext.extmin
    xmax, ymax, _ = ext.extmax
    if xmax <= xmin or ymax <= ymin:
        # Degenerate (single point / straight line) - pad a little.
        pad = 1.0
        xmin -= pad
        ymin -= pad
        xmax += pad
        ymax += pad
    return xmin, ymin, xmax, ymax


def _choose_fit_scale(width_mm: float, height_mm: float,
                       avail_w_mm: float, avail_h_mm: float) -> float:
    """Pick the smallest standard 1:N scale (i.e. largest drawing) that fits."""
    for n in STANDARD_SCALES:
        if width_mm / n <= avail_w_mm and height_mm / n <= avail_h_mm:
            return float(n)
    # Nothing in the table is small enough a plot; compute an exact
    # (non-standard) scale as a fallback so it still fits.
    needed = max(width_mm / avail_w_mm, height_mm / avail_h_mm)
    return needed


def convert_dxf_to_pdf(
    input_path: str,
    output_path: str,
    scale: Optional[str] = None,
    paper: str = "A4",
    orientation: str = "auto",
    margin_mm: float = 10.0,
    units: str = "mm",
    show_scale_label: bool = True,
    line_width_scale: float = 1.0,
) -> ConversionResult:
    """
    Convert a DXF file to an accurately-scaled, vector PDF.

    Args:
        input_path: path to a .dxf file.
        output_path: path to write the .pdf file.
        scale: e.g. "1:100". If omitted, the largest standard scale that
            fits the chosen paper is picked automatically.
        paper: one of PAPER_SIZES_MM keys, or "WIDTHxHEIGHT" in mm.
        orientation: "auto" (fit drawing best), "portrait" or "landscape".
        margin_mm: blank margin kept around the drawing on all sides.
        units: drawing's real-world unit ("mm", "cm", "m", "in", "ft").
            DXF files store unitless numbers; this tells cad2pdf what one
            drawing unit actually represents.
        show_scale_label: print scale/units/paper info in the PDF footer.
        line_width_scale: multiplier applied to rendered line widths.

    Returns:
        ConversionResult with the scale and layout actually used.
    """
    if units not in UNITS_TO_MM:
        raise ValueError(f"units must be one of {sorted(UNITS_TO_MM)}")
    unit_to_mm = UNITS_TO_MM[units]

    doc = ezdxf.readfile(input_path)
    xmin, ymin, xmax, ymax = _drawing_extents(doc)
    width_units = xmax - xmin
    height_units = ymax - ymin
    width_mm = width_units * unit_to_mm
    height_mm = height_units * unit_to_mm

    paper_w_mm, paper_h_mm = _get_paper_mm(paper, orientation)
    avail_w_mm = paper_w_mm - 2 * margin_mm
    avail_h_mm = paper_h_mm - 2 * margin_mm
    if avail_w_mm <= 0 or avail_h_mm <= 0:
        raise ValueError("margin_mm too large for the chosen paper size")

    fit_mode = scale is None
    if fit_mode:
        # Try both orientations if orientation == "auto" and pick whichever
        # yields the finest (smallest N) fitting standard scale.
        if orientation == "auto":
            s_portrait = _choose_fit_scale(width_mm, height_mm, avail_w_mm, avail_h_mm)
            # try swapped paper orientation too
            alt_w, alt_h = paper_h_mm - 2 * margin_mm, paper_w_mm - 2 * margin_mm
            s_landscape = _choose_fit_scale(width_mm, height_mm, alt_w, alt_h)
            if s_landscape < s_portrait:
                paper_w_mm, paper_h_mm = paper_h_mm, paper_w_mm
                avail_w_mm, avail_h_mm = alt_w, alt_h
                scale_den = s_landscape
                orientation_used = "landscape"
            else:
                scale_den = s_portrait
                orientation_used = "portrait"
        else:
            scale_den = _choose_fit_scale(width_mm, height_mm, avail_w_mm, avail_h_mm)
            orientation_used = orientation
    else:
        scale_den = _parse_scale(scale)
        orientation_used = orientation if orientation != "auto" else (
            "landscape" if width_mm >= height_mm else "portrait"
        )
        if orientation == "auto":
            paper_w_mm, paper_h_mm = _get_paper_mm(paper, orientation_used)
            avail_w_mm = paper_w_mm - 2 * margin_mm
            avail_h_mm = paper_h_mm - 2 * margin_mm
        plotted_w_mm = width_mm / scale_den
        plotted_h_mm = height_mm / scale_den
        if plotted_w_mm > avail_w_mm + 1e-6 or plotted_h_mm > avail_h_mm + 1e-6:
            raise ValueError(
                f"Drawing does not fit on {paper} at scale 1:{scale_den:g} "
                f"({plotted_w_mm:.1f}x{plotted_h_mm:.1f} mm needed, "
                f"{avail_w_mm:.1f}x{avail_h_mm:.1f} mm available). "
                f"Choose a larger paper size, a coarser scale, or omit "
                f"--scale to auto-fit."
            )

    plotted_w_mm = width_mm / scale_den
    plotted_h_mm = height_mm / scale_den

    fig_w_in = paper_w_mm / MM_PER_INCH
    fig_h_in = paper_h_mm / MM_PER_INCH
    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=300)

    axes_w_frac = plotted_w_mm / paper_w_mm
    axes_h_frac = plotted_h_mm / paper_h_mm
    left = (1.0 - axes_w_frac) / 2.0
    bottom = (1.0 - axes_h_frac) / 2.0
    if show_scale_label:
        # Reserve a thin strip at the bottom for the label so the
        # geometry itself is never shifted off true scale placement
        # within its own box.
        bottom = max(bottom, 12.0 / paper_h_mm)

    ax = fig.add_axes((left, bottom, axes_w_frac, axes_h_frac))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    ctx = RenderContext(doc)
    # adjust_figure=False: without it, MatplotlibBackend.finalize() resizes
    # our precisely-computed page/figure to fit the data's aspect ratio,
    # silently discarding the paper size and scale we just calculated.
    backend = MatplotlibBackend(ax, adjust_figure=False)
    frontend = Frontend(ctx, backend)
    if line_width_scale != 1.0:
        try:
            backend.line_width_scaling = line_width_scale
        except AttributeError:
            pass
    frontend.draw_layout(doc.modelspace(), finalize=True)

    # finalize() also re-enables autoscale on the axes, which can nudge the
    # data limits away from the exact extents we based the scale on. Pin
    # them back so the printed scale stays exact.
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal", adjustable="box")
    ax.autoscale(False)

    if show_scale_label:
        label = (
            f"{os.path.basename(input_path)}   |   "
            f"Scale 1:{scale_den:g}"
            f"{' (auto-fit)' if fit_mode else ''}   |   "
            f"Paper {paper.upper()} {orientation_used}   |   "
            f"Units: {units}   |   "
            f"Generated {datetime.date.today().isoformat()}"
        )
        fig.text(0.5, 0.02, label, ha="center", va="bottom", fontsize=6,
                  family="monospace", color="black")

    with PdfPages(output_path) as pdf:
        pdf.savefig(fig)
    plt.close(fig)

    return ConversionResult(
        output_path=output_path,
        scale_denominator=scale_den,
        paper_size=paper.upper(),
        paper_mm=(paper_w_mm, paper_h_mm),
        orientation=orientation_used,
        drawing_units=units,
        drawing_extents_mm=(width_mm, height_mm),
        fit_mode=fit_mode,
    )
