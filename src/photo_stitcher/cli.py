"""Command-line interface for photo-stitcher."""
from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-stitch",
        description="Review, rotate, and stitch FastFoto-style photo scans.")
    parser.add_argument(
        "--move-single-scans", action="store_true",
        help="When a folder is chosen, automatically move scans that have "
             "only a primary front (no _a/_b files) into a 'single_scans' "
             "subfolder, then continue with the review queue.")
    parser.add_argument(
        "--move-reviewed-originals", action="store_true",
        help="When a folder is chosen, automatically move the original scans "
             "of already-finished groups into a 'reviewed_originals' subfolder, then "
             "continue with the review queue.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        sys.exit(
            "Could not import the PyQt6 GUI toolkit.\n"
            f"Underlying error: {exc}\n\n"
            "Install it with:  pip install PyQt6 Pillow\n"
            "On some Linux systems you may also need OS packages providing\n"
            "libEGL/libGL (e.g. 'apt install libegl1 libgl1')."
        )
    from .gui.wizard import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Photo Scan Review & Stitcher")
    window = MainWindow(move_single_scans=args.move_single_scans,
                        move_reviewed_originals=args.move_reviewed_originals)
    window.show()
    sys.exit(app.exec())
