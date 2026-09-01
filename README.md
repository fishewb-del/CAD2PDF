# cad2pdf

A small command-line tool that converts CAD drawings (`.dxf`) into PDF
files while preserving full geometric accuracy and a correct, labeled
print scale — the way a real CAD plotter works, not an image-resize tool.

## Why this is different from "just export a PDF"

Many quick converters rasterize the drawing or auto-fit it to a page,
which silently changes the scale and blurs fine detail. `cad2pdf` instead:

1. **Draws vectors, not pixels.** Every line, arc, circle, polyline, text
   and hatch is rendered as a true vector path directly into the PDF, so
   there is no pixelation and you can zoom in without quality loss.
2. **Uses an exact, known scale.** You either specify a real drafting
   scale (e.g. `1:50`, `1:100`) or let the tool auto-pick the largest
   *standard* scale (1:1, 1:2, 1:5, 1:10, 1:20 ... 1:5000) that fits the
   chosen paper — never an arbitrary stretch factor. One drawing unit
   always maps to a precise, calculable number of millimetres on paper.
3. **Never lets rendering auto-resize the page.** (This is a real
   footgun in the underlying rendering library — its default behavior is
   to silently resize the output to fit the drawing, which breaks the
   scale. `cad2pdf` explicitly locks the page size and axis extents so
   the scale you asked for is the scale you get — see
   `tests/test_convert.py::test_explicit_scale_matches_page_geometry`.)
4. **Labels the output.** The PDF footer records the source file, scale,
   paper size/orientation, drawing units and generation date, so anyone
   opening the PDF later knows exactly how to measure off it.

## Install

```bash
pip install -e .
# or, without installing the package:
pip install -r requirements.txt
```

Requires Python 3.9+. Uses [`ezdxf`](https://ezdxf.readthedocs.io/) to
parse DXF geometry and `matplotlib`'s vector PDF backend to render it.

## Usage

```bash
cad2pdf INPUT.dxf OUTPUT.pdf [options]
```

| Option | Description | Default |
|---|---|---|
| `--scale N:M` | Print scale, e.g. `1:100`. Omit to auto-fit to the largest standard scale that fits the page. | auto |
| `--paper` | `A0`-`A4`, `LETTER`, `LEGAL`, `TABLOID`, or `WIDTHxHEIGHT` in mm (e.g. `500x700`) | `A4` |
| `--orientation` | `auto`, `portrait`, or `landscape` | `auto` |
| `--units` | Real-world unit one drawing unit represents: `mm`, `cm`, `m`, `in`, `ft` | `mm` |
| `--margin` | Blank margin around the drawing, in mm | `10` |
| `--no-label` | Suppress the scale/units/paper footer | off |
| `--line-width-scale` | Multiplier on rendered line widths | `1.0` |

### Examples

Auto-fit a drawing to A4 at the best standard scale:

```bash
cad2pdf floorplan.dxf floorplan.pdf
```

Plot a 1:100 architectural drawing (in millimetre units) onto A3 landscape:

```bash
cad2pdf floorplan.dxf floorplan.pdf --scale 1:100 --paper A3 --orientation landscape
```

A site plan modeled in metres, printed at 1:500 on A1:

```bash
cad2pdf site.dxf site.pdf --scale 1:500 --paper A1 --units m
```

If a chosen scale/paper combination is too small for the drawing, the
tool reports the exact error instead of silently cropping or distorting
it:

```
cad2pdf: error: Drawing does not fit on A4 at scale 1:1 (952.0x476.0 mm
needed, 277.0x190.0 mm available). Choose a larger paper size, a coarser
scale, or omit --scale to auto-fit.
```

## About `.dwg` files

`.dwg` is Autodesk's closed, proprietary binary format and can't be
parsed without Autodesk's own libraries or a conversion step. To convert
a `.dwg` file:

1. Use the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
   (or AutoCAD/BricsCAD/LibreCAD "Save As") to convert `.dwg` → `.dxf`.
2. Run `cad2pdf` on the resulting `.dxf`.

Because DXF is a lossless, text-based representation of the same
geometry AutoCAD uses internally, this two-step path preserves the same
accuracy as a native DWG plot.

## How the scale math works

Given a drawing's bounding box (in drawing units) and a target scale
`1:N`:

```
plotted_width_mm  = bbox_width_units  * units_to_mm(units) / N
plotted_height_mm = bbox_height_units * units_to_mm(units) / N
```

The matplotlib `Axes` is placed on the figure at exactly
`plotted_width_mm x plotted_height_mm` (converted to inches, since
matplotlib figures are inch-based), and its data limits are set to the
drawing's exact bounding box with an equal aspect ratio. That fixes the
mapping from drawing units to page millimetres to be precisely `1/N`,
with no auto-fit distortion — the same guarantee a licensed CAD
plotter gives you.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The test suite converts synthetic DXF drawings and checks, among other
things, that the *actual PDF page dimensions* (read back with `pypdf`)
match the requested paper size — this is the check that would catch a
renderer silently resizing the output and breaking the scale.
