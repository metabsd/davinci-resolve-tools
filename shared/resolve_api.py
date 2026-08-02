"""
Thin wrapper around DaVinciResolveScript for the resolve-tools scripts.

Imports only work when this file is run with DaVinci Resolve's **embedded
Python interpreter**. If you try to import it with the system Python you'll
see `ModuleNotFoundError: No module named 'DaVinciResolveScript'` — that's
expected, run the script with the Resolve-bundled Python instead.
"""

from __future__ import annotations

import sys


def connect() -> "object":
    """Open a connection to the running Resolve instance.

    Returns the `resolve` module (entry point to the whole scripting tree).
    On macOS/Linux you must set RESOLVE_SCRIPT_API and RESOLVE_SCRIPT_LIB
    environment variables first; we handle that automatically via
    auto_set_env() so user scripts can just call connect().

    Raises:
        RuntimeError: if Resolve is not running, scripting is disabled, or
            the embedded interpreter cannot be found.
    """
    auto_set_env()
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Cannot import DaVinciResolveScript. Are you running this with "
            "DaVinci Resolve's bundled Python interpreter? See "
            "docs/INSTALL_WINDOWS.md §5 for the exact path."
        ) from e

    resolve = dvr.scriptapp("Resolve")  # type: ignore[attr-defined]
    if resolve is None:
        raise RuntimeError(
            "Could not connect to Resolve. Check that DaVinci Resolve is "
            "running and that External scripting is enabled (Settings → "
            "System → General → ☑ External scripting using → Local)."
        )
    return resolve


def auto_set_env() -> None:
    """Set RESOLVE_SCRIPT_API/LIB so the DaVinciResolveScript module is importable.

    These variables are only required on macOS/Linux. On Windows, the module
    is auto-discoverable as long as you're running the bundled interpreter.
    Setting them is harmless there.
    """
    if sys.platform.startswith("win"):
        # On Windows the embedded interpreter already has the path baked in,
        # but exporting the vars is useful documentation.
        import os
        os.environ.setdefault(
            "RESOLVE_SCRIPT_API",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
        )
        # RESOLVE_SCRIPT_LIB points at the Fusion/Scripting dlls; not used on
        # the Python-side but kept for parity with the official docs.
        os.environ.setdefault(
            "RESOLVE_SCRIPT_LIB",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusion",
        )
        return

    if sys.platform == "darwin":
        import os
        os.environ.setdefault(
            "RESOLVE_SCRIPT_API",
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve",
        )
        os.environ.setdefault(
            "RESOLVE_SCRIPT_LIB",
            "/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion",
        )
        return

    # Linux (Debian/Ubuntu from davinci-resolve deb package)
    import os
    os.environ.setdefault("RESOLVE_SCRIPT_API", "/opt/resolve")
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion")


def get_timeline_or_die(resolve) -> "object":
    """Return the Timeline object for the clip the user has selected.

    Looks for `resolve.GetCurrentProject().GetCurrentTimeline()` first.
    Raises with a helpful message if nothing is selected/loaded.
    """
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError(
            "No project is open in DaVinci Resolve. Open a project first."
        )
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError(
            "No timeline is selected. Click a timeline in the Media Pool "
            "before running this tool."
        )
    return timeline


def frames_per_second(timeline) -> float:
    """Return the frame rate of the given timeline as a float (e.g. 23.976)."""
    fps_str = timeline.GetSetting("timelineFrameRate")
    # Resolve returns strings like "23.976", "29.97", "24", "60"
    try:
        return float(fps_str)
    except (TypeError, ValueError):
        return 24.0


def seconds_to_timecode(seconds: float, fps: float) -> str:
    """Convert seconds (float) to a Resolve-friendly SMPTE timecode string.

    We always generate non-drop-frame timecode, which is what the markers API
    accepts as a plain string (e.g. "00:01:23:14").

    Args:
        seconds: time in seconds (may be fractional).
        fps: frames per second.

    Returns:
        Timecode string formatted "HH:MM:SS:FF".
    """
    if seconds < 0:
        seconds = 0.0
    total_frames = int(round(seconds * fps))
    f = total_frames % int(round(fps))
    total_seconds = total_frames // int(round(fps))
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
