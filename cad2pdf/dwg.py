"""
DWG support.

DWG is Autodesk's closed binary format, so it can't be parsed directly the
way DXF can. We shell out to LibreDWG's `dwg2dxf`, which converts DWG to
DXF losslessly enough for plotting (it preserves coordinates, layers,
colours and the $INSUNITS header that our scale logic depends on).

If the binary isn't installed, dwg_available() returns False and callers
fall back to telling the user to convert manually.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# Allow deployments to point at a specific binary.
DWG2DXF_BIN = os.environ.get("CAD2PDF_DWG2DXF", "dwg2dxf")

# DWG files can be large; don't let a pathological file hang a web worker.
CONVERT_TIMEOUT_SEC = int(os.environ.get("CAD2PDF_DWG_TIMEOUT", "120"))


class DwgConversionError(RuntimeError):
    """Raised when a DWG file could not be converted to DXF."""


def dwg_available() -> bool:
    """True if a usable dwg2dxf binary is on PATH (or configured)."""
    return shutil.which(DWG2DXF_BIN) is not None


def convert_dwg_to_dxf(dwg_path: str, dxf_path: str) -> str:
    """
    Convert a DWG file to DXF in place. Returns dxf_path.

    Raises DwgConversionError with a user-readable message on failure.
    """
    if not dwg_available():
        raise DwgConversionError(
            "DWG support is not installed on this server (missing "
            "'dwg2dxf'). Convert the file to DXF and upload that instead."
        )

    try:
        proc = subprocess.run(
            [DWG2DXF_BIN, "-y", "-o", dxf_path, dwg_path],
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DwgConversionError(
            "This DWG file took too long to convert. It may be very large "
            "or corrupt."
        )
    except OSError as exc:
        raise DwgConversionError(f"Could not run the DWG converter: {exc}")

    if not os.path.exists(dxf_path) or os.path.getsize(dxf_path) == 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = detail[-1] if detail else f"exit code {proc.returncode}"
        raise DwgConversionError(
            "This DWG file could not be read. Very new or unusual DWG "
            "versions aren't always supported - re-saving it as DXF from "
            f"your CAD program will work. ({hint})"
        )

    return dxf_path
