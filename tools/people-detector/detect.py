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


# ---------------------------------------------------------------------------
# Backend auto-detection
# ---------------------------------------------------------------------------
def _detect_providers() -> tuple[str, list[str]]:
    """Return (onnxruntime_providers, ultralytics_device).

    `onnxruntime_providers` is what we feed `onnxruntime.InferenceSession(...,
    providers=...)`. Falls back to `["CPUExecutionProvider"]` if nothing else is
    available.

    `ultralytics_device` is the string we pass to Ultralytics `.predict(device=)`.
    Ultralytics DOES NOT support DirectML natively (its `.to()` is a thin
    PyTorch wrapper and PyTorch doesn't include "dml"), so the right answer is
    to bypass Ultralytics' own inference on AMD iGPUs — we use Ultralytics only
    to export the model to ONNX, then run inference through onnxruntime.

    Returns:
        ("CUDAExecutionProvider", ["CUDAExecutionProvider"]) on NVIDIA
        ("DmlExecutionProvider",  ["DmlExecutionProvider"]) on AMD/Intel/NVIDIA
            via DirectML
        ("CPUExecutionProvider",  ["CPUExecutionProvider"]) fallback
    """
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        available = ort.get_available_providers()
    except ImportError:
        return ("CPUExecutionProvider", ["CPUExecutionProvider"])

    if "CUDAExecutionProvider" in available:
        # Prefer CUDA on NVIDIA boxes (it's faster than DirectML on the same
        # GPU) — DirectML is the fallback if for some reason CUDA isn't usable.
        return ("CUDAExecutionProvider", ["CUDAExecutionProvider"])

    if "DmlExecutionProvider" in available:
        return ("DmlExecutionProvider", ["DmlExecutionProvider"])

    return ("CPUExecutionProvider", ["CPUExecutionProvider"])


# ---------------------------------------------------------------------------
# ONNX session helper
# ---------------------------------------------------------------------------
def _load_onnx_session(providers: list[str]):
    """Export yolo11n to ONNX (if needed) and open an onnxruntime InferenceSession.

    We export once to `<model_name>.onnx` next to `yolo11n.pt` (which Ultralytics
    downloads on demand). Re-export only if the ONNX file is missing.
    """
    from pathlib import Path as _Path
    import onnxruntime as ort  # type: ignore[import-not-found]
    from ultralytics import YOLO  # type: ignore[import-not-found]

    pt_path = _Path("yolo11n.pt")
    onnx_path = _Path("yolo11n.onnx")

    if not onnx_path.exists():
        # Ultralytics handles the export; this triggers a one-time conversion.
        # imgsz=320 keeps the model small/fast (good enough for "person" detection).
        # opset=12 is required by onnxruntime-directml.
        # simplify=True runs onnx-simplifier for a leaner graph.
        YOLO(str(pt_path)).export(
            format="onnx",
            imgsz=320,
            opset=12,
            simplify=True,
            half=False,  # FP32 is the safest default across providers
        )

    sess = ort.InferenceSession(str(onnx_path), providers=providers)
    return sess, _input_name(sess), _output_name(sess)


def _input_name(sess) -> str:
    return sess.get_inputs()[0].name


def _output_name(sess) -> str:
    return sess.get_outputs()[0].name


# Person-class index in the COCO 80-class list (Ultralytics follows COCO order).
PERSON_CLASS_ID = 0


def _letterbox(img, new_w: int, new_h: int) -> tuple:
    """Resize + pad `img` to (new_w, new_h) keeping aspect ratio.

    Returns (resized_image, scale, pad_left, pad_top).

    YOLO models are trained on letterboxed inputs at training resolution, so
    any new frame must go through the same transform for inference to be valid.
    """
    h0, w0 = img.shape[:2]
    r = min(new_w / w0, new_h / h0)
    new_unpad_w, new_unpad_h = int(round(w0 * r)), int(round(h0 * r))
    pad_l = (new_w - new_unpad_w) // 2
    pad_t = (new_h - new_unpad_h) // 2
    resized = cv2.resize(img, (new_unpad_w, new_unpad_h), interpolation=cv2.INTER_LINEAR)
    padded = cv2.copyMakeBorder(
        resized, pad_t, new_h - new_unpad_h - pad_t, pad_l, new_w - new_unpad_w - pad_l,
        borderType=cv2.BORDER_CONSTANT, value=(114, 114, 114),
    )
    return padded, r, pad_l, pad_t


def _run_onnx_inference(frame, sess, input_name: str, output_name: str,
                        input_w: int, input_h: int, confidence: float) -> list[float]:
    """Run a single YOLO11 frame through the ONNX session.

    The YOLO11 ONNX export has a single output of shape [1, 84, N_anchors] —
    4 box coords (x, y, w, h) followed by 80 COCO class scores. Anchor 0 = the
    "person" class. We don't need full NMS for the time-range product; it's
    enough to count distinct detections (we only need "was a person seen?").
    """
    import numpy as np  # type: ignore[import-not-found]

    img, r, pad_l, pad_t = _letterbox(frame, input_w, input_h)
    # HWC uint8 BGR → NCHW float32 normalized to [0, 1], RGB order.
    blob = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    blob = np.transpose(blob, (2, 0, 1))[None, ...]  # 1x3xHxW

    outputs = sess.run([output_name], {input_name: blob})
    pred = outputs[0]  # shape [1, 84, N_anchors]

    # Best class score per anchor.
    class_scores = pred[0, 4:, :]                   # [80, N]
    person_scores = class_scores[PERSON_CLASS_ID]  # [N]
    mask = person_scores >= confidence
    return person_scores[mask].tolist()


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
    # We export to ONNX once and run inference through onnxruntime (which can
    # target DirectML on AMD/Intel/NVIDIA GPUs through DX12). Bypassing
    # Ultralytics' own forward pass is required because Ultralytics' .to() is
    # a PyTorch wrapper that doesn't accept "dml" as a device string.
    provider_name, providers = _detect_providers()
    if not quiet:
        print(f"[detect] Using onnxruntime provider: {provider_name}", file=sys.stderr)
    sess, input_name, output_name = _load_onnx_session(providers)

    # Pre-compute the letterbox transform for one input size.
    # Ultralytics uses 640 by default but we export at 320 for speed on iGPUs.
    input_w = sess.get_inputs()[0].shape[2] or 320
    input_h = sess.get_inputs()[0].shape[3] or 320

    ranges: list[PersonRange] = []
    current_start: float | None = None
    current_confs: list[float] = []

    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % sample_every_n_frames == 0:
                person_confs = _run_onnx_inference(
                    frame, sess, input_name, output_name, input_w, input_h, confidence
                )

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
