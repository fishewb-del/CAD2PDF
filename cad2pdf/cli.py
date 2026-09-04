"""Command-line interface for cad2pdf."""

from __future__ import annotations

import argparse
import sys

from .converter import convert_dxf_to_pdf, PAPER_SIZES_MM, UNITS_TO_MM


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cad2pdf",
        description=(
            "Convert a CAD DXF drawing to an accurately scaled, vector PDF. "
            "Geometry is drawn as true vector paths (no rasterization), and "
            "the drawing is placed on the page at an exact, labeled scale "
            "(e.g. 1:100) so real-world measurements can still be taken off "
            "the printed PDF."
        ),
    )
    parser.add_argument("input", help="Path to the input .dxf file")
    parser.add_argument("output", help="Path to write the output .pdf file")
    parser.add_argument(
        "--scale", default=None,
        help="Print scale as 'N:M', e.g. '1:100'. Omit to auto-pick the "
             "largest standard scale that fits the paper.",
    )
    parser.add_argument(
        "--paper", default="A4",
        help=f"Paper size: one of {sorted(PAPER_SIZES_MM)} or 'WIDTHxHEIGHT' "
             f"in mm (e.g. '500x700'). Default: A4",
    )
    parser.add_argument(
        "--orientation", choices=["auto", "portrait", "landscape"],
        default="auto", help="Page orientation. Default: auto",
    )
    parser.add_argument(
        "--units", choices=sorted(UNITS_TO_MM), default="mm",
        help="Real-world unit represented by one DXF drawing unit. "
             "Default: mm",
    )
    parser.add_argument(
        "--margin", type=float, default=10.0,
        help="Blank margin around the drawing, in mm. Default: 10",
    )
    parser.add_argument(
        "--no-label", action="store_true",
        help="Do not print the scale/units/paper footer on the PDF",
    )
    parser.add_argument(
        "--line-width-scale", type=float, default=1.0,
        help="Multiplier applied to rendered line widths. Default: 1.0",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = convert_dxf_to_pdf(
            input_path=args.input,
            output_path=args.output,
            scale=args.scale,
            paper=args.paper,
            orientation=args.orientation,
            margin_mm=args.margin,
            units=args.units,
            show_scale_label=not args.no_label,
            line_width_scale=args.line_width_scale,
        )
    except Exception as exc:  # surface a clean CLI error, not a traceback
        print(f"cad2pdf: error: {exc}", file=sys.stderr)
        return 1

    if result.repair_note:
        # stderr, so piping stdout somewhere still gets clean output while
        # the warning stays visible.
        print(f"cad2pdf: warning: {result.repair_note}", file=sys.stderr)

    print(
        f"Wrote {result.output_path}\n"
        f"  scale:       1:{result.scale_denominator:g}"
        f"{' (auto-fit)' if result.fit_mode else ''}\n"
        f"  paper:       {result.paper_size} "
        f"({result.paper_mm[0]:.0f}x{result.paper_mm[1]:.0f} mm, "
        f"{result.orientation})\n"
        f"  drawing:     {result.drawing_extents_mm[0]:.1f}x"
        f"{result.drawing_extents_mm[1]:.1f} mm ({result.drawing_units} units)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
