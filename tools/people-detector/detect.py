"""
Detect human presence in a video using YOLO11, output time ranges.

Run with the **system Python** (your venv), NOT with Resolve's embedded Python:
YOLO + OpenCV live in your venv, Resolve's interpreter doesn't have them.

Examples:
    python detect.py --video input.mp4 --output output/people.csv
    python detect.py -v input.mp4 -o output/people.json
    python detect.py -v input.mp4 -o output/people.csv --confidence 0.5 --min-duration 0.3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2  # type: ignore[import-not-found]
from ultralytics import YOLO  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Backend auto-detection
# ---------------------------------------------------------------------------
def _pick_device() -> str:
    """Return the best available compute device for Ultralytics YOLO.

    Returns one of:
      - "dml" if onnxruntime-directml is importable (covers AMD RDNA,
        Intel Arc, NVIDIA, basically any DX12 GPU on Windows)
      - "0"  if PyTorch sees a CUDA device (NVIDIA only, requires the
        torch+CUDA wheels installed separately)
      - "cpu" fallback (always works)
    """
    # 1. DirectML — preferred on Windows because it covers every modern GPU
    #    (AMD RDNA, Intel Arc, NVIDIA) without per-vendor installs.
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        # Available providers string includes "DmlExecutionProvider" when the
        # DirectML package is installed.
        if "DmlExecutionProvider" in ort.get_available_providers():
            return "dml"
    except ImportError:
        pass

    # 2. CUDA — NVIDIA only.
    try:
        import torch  # type: ignore[import-not-found]

        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return "0"
    except ImportError:
        pass

    # 3. CPU — always works, just slower.
    return "cpu"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PersonRange:
    """One continuous time span during which at least one person is visible."""

    start_seconds: float
    end_seconds: float
    avg_confidence: float  # mean detection confidence across the range

    def to_csv_row(self) -> dict:
        return {
            "start_seconds": f"{self.start_seconds:.3f}",
            "end_seconds": f"{self.end_seconds:.3f}",
            "duration_seconds": f"{self.end_seconds - self.start_seconds:.3f}",
            "avg_confidence": f"{self.avg_confidence:.3f}",
        }


# ---------------------------------------------------------------------------
# Core detection loop
# ---------------------------------------------------------------------------
def detect_people(
    video_path: Path,
    confidence: float,
    sample_every_n_frames: int,
    quiet: bool = False,
) -> list[PersonRange]:
    """Return a list of time ranges during which a person is visible.

    We sample one frame every N frames (default: every frame). Tracking is
    naive: consecutive sampled frames with ≥1 detected person fuse into one
    range. Confidence is averaged across all frames in the range.

    Args:
        video_path: input video file.
        confidence: minimum detection confidence, 0..1.
        sample_every_n_frames: 1 = every frame, 5 = every 5th frame (faster).

    Returns:
        List of PersonRange sorted by start time.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV failed to open the video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # YOLO11 nano: ~6 MB, mAP ~50 on COCO. Tiny hit on accuracy vs. huge speed win.
    # We auto-pick the best available compute device:
    #   "dml" (DirectML) → any DX12 GPU — RDNA 3 on ROG Ally X, Intel Arc, etc.
    #   "0"  (CUDA)      → first NVIDIA GPU (only if PyTorch+CUDA is installed)
    #   "cpu"            → CPU fallback (always works)
    device = _pick_device()
    if not quiet:
        print(f"[detect] Using device: {device}", file=sys.stderr)
    model = YOLO("yolo11n.pt").to(device)

    ranges: list[PersonRange] = []  # noqa: F821
    current_start: float | None = None
    current_confs: list[float] = []

    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % sample_every_n_frames == 0:
                # verbose=False suppresses per-frame console spam.
                # classes=[0] filters COCO "person" class (index 0).
                results = model(frame, classes=[0], conf=confidence, verbose=False)
                person_confs: list[float] = []
                for r in results:
                    for box in r.boxes:
                        person_confs.append(float(box.conf))

                t = frame_index / fps
                if person_confs:
                    if current_start is None:
                        current_start = t
                    current_confs.extend(person_confs)
                else:
                    if current_start is not None:
                        ranges.append(
                            PersonRange(
                                start_seconds=current_start,
                                end_seconds=t,
                                avg_confidence=sum(current_confs) / len(current_confs),
                            )
                        )
                        current_start = None
                        current_confs = []

            frame_index += 1

        # Close out a range that runs to the end of the video
        if current_start is not None:
            last_t = frame_index / fps
            ranges.append(
                PersonRange(
                    start_seconds=current_start,
                    end_seconds=last_t,
                    avg_confidence=sum(current_confs) / len(current_confs),
                )
            )
    finally:
        cap.release()

    return _merge_close_ranges(ranges, min_gap_seconds=0.25)


def _merge_close_ranges(
    ranges: list[PersonRange], min_gap_seconds: float
) -> list[PersonRange]:
    """Merge ranges that are separated by < `min_gap_seconds` and re-average conf.

    YOLO occasionally flickers (one missed frame between two positive ranges)
    — merging keeps the timeline clean.
    """
    if not ranges:
        return ranges
    merged: list[PersonRange] = [ranges[0]]
    for r in ranges[1:]:
        prev = merged[-1]
        if r.start_seconds - prev.end_seconds <= min_gap_seconds:
            # Re-average confidence over the union (weight by duration).
            total_dur = (prev.end_seconds - prev.start_seconds) + (
                r.end_seconds - r.start_seconds
            )
            merged[-1] = PersonRange(
                start_seconds=prev.start_seconds,
                end_seconds=r.end_seconds,
                avg_confidence=(
                    prev.avg_confidence * (prev.end_seconds - prev.start_seconds)
                    + r.avg_confidence * (r.end_seconds - r.start_seconds)
                )
                / total_dur,
            )
        else:
            merged.append(r)
    return merged


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_csv(ranges: list[PersonRange], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "start_seconds",
                "end_seconds",
                "duration_seconds",
                "avg_confidence",
            ],
        )
        writer.writeheader()
        writer.writerows(r.to_csv_row() for r in ranges)


def write_json(ranges: list[PersonRange], path: Path, video_path: Path) -> None:
    payload = {
        "video": str(video_path.resolve()),
        "range_count": len(ranges),
        "ranges": [asdict(r) for r in ranges],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Detect human presence in a video → time ranges (CSV/JSON)."
    )
    p.add_argument("--video", "-v", required=True, type=Path, help="Input video file")
    p.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Output file path. Extension determines format: .csv or .json",
    )
    p.add_argument(
        "--confidence",
        "-c",
        type=float,
        default=0.4,
        help="Minimum detection confidence (0..1). Default: 0.4.",
    )
    p.add_argument(
        "--sample-every",
        "-s",
        type=int,
        default=1,
        help="Run detection every N frames. Default 1 (every frame). Use 5 for fast preview.",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress prints.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.quiet:
        print(f"[detect] Opening {args.video} ...", file=sys.stderr)

    ranges = detect_people(
        video_path=args.video,
        confidence=args.confidence,
        sample_every_n_frames=args.sample_every,
        quiet=args.quiet,
    )

    ext = args.output.suffix.lower()
    if ext == ".csv":
        write_csv(ranges, args.output)
    elif ext == ".json":
        write_json(ranges, args.output, args.video)
    else:
        print(
            f"Unsupported output extension: {ext}. Use .csv or .json.",
            file=sys.stderr,
        )
        return 2

    total_people_seconds = sum(r.end_seconds - r.start_seconds for r in ranges)
    if not args.quiet:
        print(
            f"[detect] {len(ranges)} person range(s), "
            f"total {total_people_seconds:.2f}s → {args.output}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
