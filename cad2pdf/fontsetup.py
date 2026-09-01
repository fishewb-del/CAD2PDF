"""
Guarantee that ezdxf always has at least one usable font.

ezdxf draws TEXT, MTEXT, dimensions and block attributes by loading a real
TrueType font from the operating system's font directories. A slim
container image has none at all: `python:3.11-slim` ships zero fonts. The
font cache then comes up empty and a drawing containing any text dies with

    FontNotFoundError: no fonts available, not even fallback fonts

A drawing without text converts fine, which is why this never showed up in
testing - the sample floor plan has no text in it, and neither did CI.

matplotlib is already a hard dependency and it bundles the DejaVu family,
including DejaVuSans.ttf, which is on ezdxf's own list of acceptable
fallback fonts. So there is always a usable font on disk, even on a host
that has none of its own. Registering that directory costs nothing on a
host that does have fonts, because we only do it when nothing else was
found.

Installing real system fonts is still worth doing (see the Dockerfile): a
drawing whose text style asks for Arial should get Arial metrics, not
DejaVu's. This module is the floor, not the ceiling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ezdxf.fonts import fonts as ezdxf_fonts
from ezdxf.fonts.font_manager import FontNotFoundError

logger = logging.getLogger(__name__)

_ensured = False


def bundled_font_dir() -> Optional[Path]:
    """Directory of the TrueType fonts shipped inside matplotlib."""
    try:
        import matplotlib

        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    except Exception:  # noqa: BLE001 - never let font setup break a conversion
        return None
    return path if path.is_dir() else None


def has_usable_font() -> bool:
    """
    True if ezdxf can resolve a default font face.

    This is the exact call the drawing pipeline makes, so it is the honest
    test of whether text will render.
    """
    try:
        ezdxf_fonts.font_manager.get_font_face("")
    except FontNotFoundError:
        return False
    return True


def font_count() -> int:
    try:
        return len(ezdxf_fonts.font_manager._font_cache)
    except Exception:  # noqa: BLE001
        return 0


def fallback_font_name() -> str:
    try:
        return ezdxf_fonts.font_manager.fallback_font_name()
    except Exception:  # noqa: BLE001
        return "none"


def ensure_fonts(force: bool = False) -> bool:
    """
    Make sure ezdxf has a font to render text with. Returns True if one is
    available afterwards.

    Safe to call repeatedly; the scan only happens once, and only when the
    host turned out to have no fonts of its own.
    """
    global _ensured
    if _ensured and not force:
        return has_usable_font()
    _ensured = True

    if has_usable_font():
        return True

    font_dir = bundled_font_dir()
    if font_dir is None:
        logger.warning(
            "no system fonts and no bundled fonts found; drawings "
            "containing text will fail to render"
        )
        return False

    # build() is additive - it scans the given folders and adds what it
    # finds, so this cannot discard fonts the host does have.
    ezdxf_fonts.font_manager.build([str(font_dir)], support_dirs=False)

    # fallback_font_name() memoises its answer, and it will have already
    # cached a name that resolved to nothing back when the cache was empty.
    # Clear it so it re-resolves against the fonts we just added.
    ezdxf_fonts.font_manager._fallback_font_name = ""

    ok = has_usable_font()
    if ok:
        logger.info(
            "no system fonts found; using the fonts bundled with matplotlib "
            "at %s (fallback: %s)", font_dir, fallback_font_name()
        )
    else:
        logger.warning("could not register any usable font from %s", font_dir)
    return ok
