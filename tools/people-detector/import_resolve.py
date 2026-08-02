"""
Import a person-presence CSV into DaVinci Resolve as timeline markers.

⚠️  MUST be run with DaVinci Resolve's **embedded Python interpreter**, not
your venv — it imports DaVinciResolveScript which lives only in that
interpreter.

Typical Windows invocation:

    "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\python.exe" \\
        tools/people-detector/import_resolve.py \\
        --csv output/mon_film.csv

CSV format expected (produced by detect.py):
    start_seconds,end_seconds,duration_seconds,avg_confidence
    3.200,8.500,5.300,0.870

Markers are created as range markers (start..end) on the **selected clip** in
the current timeline. Each marker is labelled with its confidence, e.g.
`person 0.87`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Resolve must be imported via the embedded interpreter — see module docstring.
# Imported lazily so this file can also be `--help`'d without resolve_api.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared import resolve_api  # noqa: E402  (resolve_api itself lazy-imports Resolve)


# Marker colour chosen so it's visible on both light and dark backgrounds.
# Resolve accepts hex colours like "#FFCC00". Yellow → easy to spot in the timeline.
DEFAULT_MARKER_COLOR = "#FFCC00"


def load_ranges(csv_path: Path) -> list[dict]:
    """Return list of dicts with keys: start_seconds, end_seconds, avg_confidence."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    ranges: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "start_seconds" not in reader.fieldnames:
            raise ValueError(
                "CSV is missing required column 'start_seconds'. "
                "Did you produce it with detect.py?"
            )
        for row in reader:
            try:
                ranges.append(
                    {
                        "start_seconds": float(row["start_seconds"]),
                        "end_seconds": float(row["end_seconds"]),
                        "avg_confidence": float(
                            row.get("avg_confidence") or row.get("confidence") or 0.0
                        ),
                    }
                )
            except ValueError as e:
                print(f"Skipping malformed row {row}: {e}", file=sys.stderr)
    return ranges


def add_marker_to_clip(
    timeline: object, fps: float, frame_offset: int, label: str, duration_frames: int = 0
) -> None:
    """Add a (range) marker to the timeline at the given frame.

    Args:
        timeline: the Timeline object resolved from Resolve.
        fps: frames per second (kept here for symmetry with future helpers).
        frame_offset: timeline-relative frame for the marker start.
        label: marker text.
        duration_frames: 0 = point marker, >0 = range marker (from start to start+N).
    """
    # The Resolve Python API uses 1-based seconds for AddMarker(). It returns
    # the marker id (we ignore it) or -1 on failure.
    # We pass the marker color and label here for both visibility and traceability.
    # type: ignore[attr-defined] — AddMarker is provided by the Resolve runtime.
    _ = timeline.AddMarker(  # type: ignore[attr-defined]
        int(frame_offset),  # frame: int
        "Blue",  # color name Resolve understands (default: blue markers)
        label,  # name
        label,  # note (same text makes the marker readable everywhere)
        duration_frames if duration_frames > 0 else 1,  # duration: int frames
    )


def main(argv: list[str] | None = None) -> int:
    _doc = __doc__ or ""
    parser = argparse.ArgumentParser(description=_doc.split("\n", 1)[0])
    parser.add_argument("--csv", required=True, type=Path, help="CSV from detect.py")
    parser.add_argument(
        "--track",
        type=int,
        default=0,
        help="Timeline video track index (default 0 = V1). Use 1 for V2, etc.",
    )
    parser.add_argument(
        "--confidence-format",
        choices=["percent", "decimal", "hide"],
        default="decimal",
        help="How to format the confidence in marker labels.",
    )
    args = parser.parse_args(argv)

    ranges = load_ranges(args.csv)
    if not ranges:
        print("[import] CSV is empty — nothing to import.", file=sys.stderr)
        return 1

    print(f"[import] Loaded {len(ranges)} range(s) from {args.csv}.", file=sys.stderr)

    resolve = resolve_api.connect()
    timeline = resolve_api.get_timeline_or_die(resolve)
    fps = resolve_api.frames_per_second(timeline)

    added = 0
    failed = 0
    for r in ranges:
        if args.confidence_format == "hide":
            label = "person"
        elif args.confidence_format == "percent":
            label = f"person {int(round(r['avg_confidence'] * 100))}%"
        else:
            label = f"person {r['avg_confidence']:.2f}"

        start_frame = int(round(r["start_seconds"] * fps))
        end_frame = int(round(r["end_seconds"] * fps))
        duration_frames = max(end_frame - start_frame, 1)

        try:
            # timeline.AddMarker expects seconds (as int) and duration in frames.
            # For range markers, pass duration > 0. Resolve will store both.
            timeline.AddMarker(
                start_frame,
                "Blue",
                label,
                label,
                duration_frames,
            )
            added += 1
        except Exception as e:
            failed += 1
            print(f"[import] Failed to add marker {label}: {e}", file=sys.stderr)

    print(
        f"[import] Done. {added} marker(s) added"
        + (f", {failed} failed." if failed else "."),
        file=sys.stderr,
    )
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
