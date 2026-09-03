"""
Tolerant DXF loading.

ezdxf.readfile() is strict: one malformed line and the whole drawing is
refused. That is the right default for a library and the wrong default for
a plotting service, because the DXF files people actually upload are very
often machine-generated - and the machine that generates them is frequently
LibreDWG's dwg2dxf, which writes a value longer than the 255-byte DXF string
limit by hard-wrapping it onto a second line:

      1
    THIS DRAWING IS THE PROPERTY OF DESIGN GROUP FACILITY SOLUTIONS, INC. ...
    N GROUP FACILITY SOLUTIONS, INC. ON COMPLETION OF WORK, IF REQUESTED.
      7
    BORDER1

(AutoCAD splits a long MTEXT value into 250-byte chunks under group code 3
instead, which is legal. dwg2dxf just wraps the line, mid-word.)

A DXF value is exactly one line, so the tail of that title-block note lands
where the next group code belongs and the reader stops with

    Invalid group code "N GROUP FACILITY SOLUTIONS, INC. ..." at line 95113.

The drawing itself is fine - every wall, dimension and layer in it is
perfectly readable - so refusing to plot it is a bug in us, not a problem
with the file. read_dxf() walks an escalating ladder instead:

  1. ezdxf.readfile()          - strict, and what a clean file gets.
  2. ezdxf.recover.readfile()  - repairs damaged structure. No data loss.
  3. stitch + recover          - rejoins wrapped string values onto the line
                                 they belong to, then recovers. This is the
                                 stage that handles the case above, and it
                                 keeps the full text of the note.
  4. ezdxf.recover.explore()   - salvage mode: skip anything that doesn't
                                 look like a tag. Lossy, so it is last.

Whenever a drawing needs stage 2 or later, the caller gets a note to show
the user: the plot is still exact, but they should know the file they were
handed is malformed.
"""

from __future__ import annotations

import dataclasses
import os
import re
import tempfile
from typing import Optional, Tuple

import ezdxf
import ezdxf.recover

# A DXF group code is a small integer alone on its line. Anything else in
# that position is not a group code, whatever it looks like.
_GROUP_CODE_RE = re.compile(rb"^[ \t]*[+-]?\d{1,4}[ \t]*$")
_MAX_GROUP_CODE = 1071

# Binary DXF has no lines to stitch; the sentinel identifies it.
_BINARY_SENTINEL = b"AutoCAD Binary DXF"

# A stitched value that grows past this is not a wrapped note, it is a file
# that has lost its structure entirely. Stop appending rather than build a
# multi-megabyte string; stage 4 is the right tool for a file like that.
_MAX_STITCHED_VALUE_BYTES = 64 * 1024

# 255 bytes is the DXF string limit, and dwg2dxf overruns it by hard-wrapping
# the value at exactly that width - mid-word, with no separator. A line that
# long is therefore a wrap to rejoin with nothing between the halves; a
# shorter one ended where the text itself had a line break, which was a
# space, so it is rejoined with one. Getting this backwards turns
# "...RETURNED TO DESIGN GROUP..." into "...RETURNED TO DESIG N GROUP..."
# and breaks MTEXT formatting codes that straddle the split.
_WRAP_WIDTH_BYTES = 255


class DxfReadError(Exception):
    """A DXF file that could not be read even in salvage mode."""


@dataclasses.dataclass
class LoadedDxf:
    """A loaded drawing, plus what we had to do to load it."""

    doc: object
    #: "clean", "recovered", "stitched" or "salvaged".
    strategy: str = "clean"
    #: User-facing explanation, or None when the file loaded cleanly.
    note: Optional[str] = None

    @property
    def repaired(self) -> bool:
        return self.strategy != "clean"


_RECOVERED_NOTE = (
    "This file had some damaged structure, which was repaired automatically "
    "before plotting. The geometry and scale are unaffected, but the file "
    "you were sent is malformed - worth mentioning to whoever produced it."
)

_SALVAGED_NOTE = (
    "This file is badly damaged. It was read in salvage mode, so parts of "
    "the drawing may be missing. Check the preview against the original "
    "before relying on this PDF."
)


def _stitched_note(count: int) -> str:
    values = "text value" if count == 1 else "text values"
    was = "was" if count == 1 else "were"
    return (
        f"This file had {count} long {values} split across two lines, which "
        f"a DXF file is not allowed to do - a common result of converting a "
        f"DWG. They {was} rejoined automatically and the drawing loaded in "
        "full. Geometry and scale are unaffected."
    )


def _is_group_code(line: bytes) -> bool:
    if not _GROUP_CODE_RE.match(line):
        return False
    return 0 <= abs(int(line)) <= _MAX_GROUP_CODE


def _is_binary_dxf(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(_BINARY_SENTINEL)) == _BINARY_SENTINEL


def stitch_wrapped_values(src_path: str, dst_path: str) -> int:
    """
    Copy a DXF, rejoining string values that were written across lines.

    A DXF is a strict alternation of code line, value line. Walk the file in
    that rhythm: a line sitting in a code position that is not a group code
    can only be the rest of the value above it, so append it there instead
    of leaving it to derail the reader.

    How the two halves are rejoined depends on why they were split - see
    _WRAP_WIDTH_BYTES.

    Returns the number of lines that were rejoined - 0 means the file has no
    wrapped values and re-reading the copy would gain nothing.
    """
    stitched = 0
    pending: Optional[bytes] = None  # value line held back, still growing
    expect_code = True

    with open(src_path, "rb") as fin, open(dst_path, "wb") as fout:
        for raw in fin:
            line = raw.rstrip(b"\r\n")
            if not expect_code:
                pending = line
                expect_code = True
                continue

            if _is_group_code(line):
                if pending is not None:
                    fout.write(pending + b"\n")
                    pending = None
                fout.write(line + b"\n")
                expect_code = False
            elif pending is None:
                # Junk with no value above it to attach to. Leave it where
                # it is and let the recover stage decide what to do.
                fout.write(line + b"\n")
            elif len(pending) + len(line) + 1 <= _MAX_STITCHED_VALUE_BYTES:
                joiner = b"" if len(pending) >= _WRAP_WIDTH_BYTES else b" "
                pending += joiner + line
                stitched += 1
            else:
                stitched += 1  # counted, but dropped rather than appended

        if pending is not None:
            fout.write(pending + b"\n")

    return stitched


def _read_stitched(path: str) -> Optional[Tuple[object, int]]:
    """
    Stage 3: rejoin wrapped values in a temp copy, then recover from that.

    Returns (doc, stitched_count), or None if the file has nothing to stitch
    or the stitched copy still won't load.
    """
    if _is_binary_dxf(path):
        return None

    # Written next to the input, which for a web request is already the
    # per-request temp dir that gets deleted with the upload.
    fd, repaired_path = tempfile.mkstemp(
        prefix="cad2pdf-stitched-", suffix=".dxf", dir=os.path.dirname(path) or None
    )
    os.close(fd)
    try:
        count = stitch_wrapped_values(path, repaired_path)
        if count == 0:
            return None
        doc, _auditor = ezdxf.recover.readfile(repaired_path)
        return doc, count
    except Exception:  # noqa: BLE001 - a stage that fails just doesn't apply
        return None
    finally:
        try:
            os.unlink(repaired_path)
        except OSError:
            pass


def read_dxf(path: str) -> LoadedDxf:
    """
    Load a DXF document, repairing it if that is what it takes.

    Raises DxfReadError only when even salvage mode cannot make sense of
    the file.
    """
    # A file we cannot open at all is the caller's problem, not a parsing
    # one - never turn "no such file" into "this drawing is damaged".
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No such DXF file: {path}")

    try:
        return LoadedDxf(ezdxf.readfile(path))
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        raise
    except Exception:  # noqa: BLE001 - every parse failure escalates
        pass

    try:
        doc, _auditor = ezdxf.recover.readfile(path)
        return LoadedDxf(doc, "recovered", _RECOVERED_NOTE)
    except Exception:  # noqa: BLE001
        pass

    stitched = _read_stitched(path)
    if stitched is not None:
        doc, count = stitched
        return LoadedDxf(doc, "stitched", _stitched_note(count))

    try:
        doc, _auditor = ezdxf.recover.explore(path)
    except Exception as exc:  # noqa: BLE001 - the ladder ends here
        raise DxfReadError(str(exc)) from exc

    # Salvage mode skips anything that doesn't look like a tag, so handed a
    # file that is not a DXF at all it succeeds and returns an empty
    # document. That is not a drawing, and calling it one sends the user off
    # to debug their sheet instead of their file.
    if not any(True for _ in doc.modelspace()):
        raise DxfReadError(
            "no readable drawing content was found in this file"
        )
    return LoadedDxf(doc, "salvaged", _SALVAGED_NOTE)
