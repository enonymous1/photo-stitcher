"""Off-GUI-thread workers for heavy Pillow operations.

Stitching full-resolution scans and JPEG-encoding the results can take
seconds — long enough for the OS to flag the app as "not responding" if it
happens on the GUI thread. The job functions below are pure Pillow (no Qt,
no shared state); :class:`PillowWorker` runs one on the global QThreadPool
and reports back via signals, which Qt delivers on the GUI thread.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..constants import JPEG_QUALITY
from ..imaging import load_image, orient_image, stitch_images


class WorkerSignals(QObject):
    """Result channels for :class:`PillowWorker` (all emitted off-thread)."""

    finished = pyqtSignal(object)  # job return value
    error = pyqtSignal(str)        # error message if the job raised


class PillowWorker(QRunnable):
    """Run a Pillow callable off the GUI thread; results arrive via signals."""

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - reported back to the GUI thread
            self.signals.error.emit(str(exc))
        else:
            self.signals.finished.emit(result)


def stitch_job(
    front_path: Path | str,
    front_turns: int,
    back_path: Path | str,
    back_turns: int,
    direction: str,
):
    """Load, orient, and stitch two scans; returns the stitched PIL image."""
    front = orient_image(load_image(Path(front_path)), front_turns)
    try:
        back = orient_image(load_image(Path(back_path)), back_turns)
        try:
            return stitch_images(front, back, direction)
        finally:
            back.close()
    finally:
        front.close()


def save_oriented_job(
    src_path: Path | str,
    turns: int,
    out_path: Path | str,
    quality: int = JPEG_QUALITY,
) -> Path:
    """Load one scan, apply rotation, and JPEG-save it; returns the output path."""
    img = orient_image(load_image(Path(src_path)), turns)
    try:
        img.save(Path(out_path), "JPEG", quality=quality)
    finally:
        img.close()
    return Path(out_path)


def save_image_job(img, out_path: Path | str, quality: int = JPEG_QUALITY) -> Path:
    """JPEG-save an in-memory PIL image; returns the output path.

    The image must not be touched on the GUI thread while the job runs —
    callers keep the busy dialog up until ``finished`` fires.
    """
    img.save(Path(out_path), "JPEG", quality=quality)
    return Path(out_path)
