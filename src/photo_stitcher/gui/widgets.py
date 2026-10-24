"""Reusable Qt widgets for the review wizard."""
from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..constants import DISPLAY_MAX_EDGE


def display_pixmap(img: Image.Image) -> QPixmap:
    """Downscaled QPixmap for on-screen display (the original is untouched)."""
    w, h = img.size
    scale = min(1.0, DISPLAY_MAX_EDGE / max(w, h))
    if scale < 1.0:
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    rgb = img.convert("RGB")
    data = rgb.tobytes()
    qimage = QImage(
        data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888
    )
    return QPixmap.fromImage(qimage)  # fromImage copies the pixel data



class ImageLabel(QLabel):
    """QLabel that keeps the full pixmap and rescales it smoothly on resize."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #1c1c1c; border-radius: 6px; color: #888;")
        self.setText("loading…")
        self._pixmap: QPixmap | None = None

    def set_image(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._pixmap or self._pixmap.isNull():
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)

