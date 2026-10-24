"""The review wizard: MainWindow and its pages."""
from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt, QThreadPool, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    COMPLETED_DIR_NAME,
    JPEG_QUALITY,
    SINGLE_SCANS_DIR_NAME,
    REVIEWED_ORIGINALS_DIR_NAME,
)
from ..grouping import (
    PhotoGroup,
    move_single_scans,
    move_reviewed_originals,
    single_scan_groups,
    reviewed_groups,
    scan_directory,
    unique_output_path,
)
from ..imaging import load_image, orient_image
from ..state import ReviewState
from .widgets import ImageLabel, display_pixmap
from .workers import PillowWorker, save_image_job, save_oriented_job, stitch_job


class MainWindow(QMainWindow):
    def __init__(self, move_single_scans: bool = False, move_reviewed_originals: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Photo Scan Review & Stitcher")
        self.resize(1280, 860)
        self.auto_move_single_scans = move_single_scans  # --move-single-scans flag
        self.auto_move_reviewed_originals = move_reviewed_originals        # --move-reviewed-originals flag

        # Review state
        self.source_dir: Path | None = None
        self.groups: list[PhotoGroup] = []
        self.index = 0
        self.current: PhotoGroup | None = None
        self.best_front_path: Path | None = None
        self.front_img: Image.Image | None = None   # full-res PIL image
        self.back_img: Image.Image | None = None    # full-res PIL image
        self.result_img: Image.Image | None = None  # full-res stitched PIL image
        self.state: ReviewState | None = None       # progress tracking
        self.rotations: dict[str, int] = {}         # filename -> 90° CW turns
        self.last_stitch_direction: str | None = None
        self.pending_groups: list[PhotoGroup] = []  # unfiltered review queue
        self.current_filter = "all"                 # all | front | back
        self._filter_keys = ["all", "front", "back"]
        self._already_count = 0
        self._auto_moved_single_count = 0
        self._auto_moved_reviewed_count = 0
        self._progress_bars: list[tuple[QProgressBar, QLabel]] = []  # queue progress widgets

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.page_welcome = self._build_welcome_page()
        self.page_summary = self._build_summary_page()
        self.page_front = self._build_front_page()
        self.page_stitch = self._build_stitch_page()
        self.page_preview = self._build_preview_page()
        self.page_done = self._build_done_page()
        for page in (
            self.page_welcome, self.page_summary, self.page_front,
            self.page_stitch, self.page_preview, self.page_done,
        ):
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self.page_welcome)
        self.statusBar().showMessage("Choose a folder to begin.")

    # -- small builders ----------------------------------------------------

    @staticmethod
    def _header() -> QLabel:
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 17px; font-weight: bold; padding: 8px;")
        return lbl

    @staticmethod
    def _big_button(text: str, min_height: int = 80) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(min_height)
        btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #888; font-size: 12px; padding: 2px;")
        return lbl

    def _progress_row(self) -> QWidget:
        """Determinate queue-progress bar + 'Group N of M' label for step pages."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(12)
        label = QLabel()
        label.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(bar, 1)
        layout.addWidget(label)
        self._progress_bars.append((bar, label))
        return row

    def _update_progress(self) -> None:
        """Refresh every queue-progress bar/label for the current position."""
        total = len(self.groups)
        done = min(self.index, total)
        for bar, label in self._progress_bars:
            bar.setMaximum(max(total, 1))
            bar.setValue(done)
            label.setText(f"Group {done + 1} of {total}" if total else "No groups")

    @contextmanager
    def _busy(self, message: str):
        """Modal busy indicator around blocking Pillow work (stitch/save).

        The heavy image ops run on the GUI thread; this paints a small
        "working…" dialog first so the app never looks hung. A short minimum
        duration keeps instant operations from flashing it.
        """
        dlg = QProgressDialog(message, None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setCancelButton(None)  # not cancellable; a dead button would mislead
        dlg.show()
        QApplication.processEvents()  # let the dialog paint before we block
        try:
            yield dlg
        finally:
            dlg.close()

    def _run_in_background(self, message, fn, on_done, *args, **kwargs) -> None:
        """Run ``fn(*args, **kwargs)`` on the global QThreadPool.

        Shows a modal busy dialog while the work runs: the event loop keeps
        spinning (so the OS never sees a hung app) but the user can't start
        anything else until the worker finishes. ``on_done`` is called on
        the GUI thread with the worker's return value.
        """
        dlg = QProgressDialog(message, None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)  # stitch/save are the slow ops; show immediately
        dlg.setCancelButton(None)  # not cancellable; a dead button would mislead
        worker = PillowWorker(fn, *args, **kwargs)

        def _succeeded(result) -> None:
            worker.signals.finished.disconnect(_succeeded)
            worker.signals.error.disconnect(_failed)
            dlg.close()
            on_done(result)

        def _failed(msg: str) -> None:
            worker.signals.finished.disconnect(_succeeded)
            worker.signals.error.disconnect(_failed)
            dlg.close()
            self._on_worker_error(msg)

        worker.signals.finished.connect(_succeeded)
        worker.signals.error.connect(_failed)
        dlg.show()
        QThreadPool.globalInstance().start(worker)

    def _on_worker_error(self, message: str) -> None:
        QMessageBox.warning(self, "Processing failed",
                            f"Something went wrong:\n{message}")

    def _image_panel(self, caption: str, on_rotate=None) -> tuple[QFrame, QLabel, ImageLabel]:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setWordWrap(True)
        cap.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(cap)
        img = ImageLabel()
        layout.addWidget(img, 1)
        if on_rotate is not None:
            row = QHBoxLayout()
            ccw = QPushButton("⟲ 90°")
            cw = QPushButton("⟳ 90°")
            for b in (ccw, cw):
                b.setStyleSheet("font-size: 12px; padding: 6px;")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
            ccw.clicked.connect(lambda: on_rotate(-1))
            cw.clicked.connect(lambda: on_rotate(1))
            row.addWidget(ccw)
            row.addWidget(cw)
            layout.addLayout(row)
        return frame, cap, img

    # -- pages ---------------------------------------------------------------

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel("Photo Scan Review & Stitcher")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: bold;")
        layout.addWidget(title)
        layout.addSpacing(12)
        info = QLabel(
            "Point this app at a folder of Epson FastFoto-style scans.\n\n"
            "It groups files like  FastFoto_0158.jpg  /  _a.jpg  /  _b.jpg,\n"
            "lets you pick the best front scan, optionally stitches the back\n"
            "of the photo onto it, and saves finished images to a 'completed'\n"
            "subfolder — always at full original resolution."
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("font-size: 14px;")
        layout.addWidget(info)
        layout.addSpacing(20)
        browse = self._big_button("Browse…", min_height=70)
        browse.setFixedWidth(340)
        browse.clicked.connect(self.browse)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        self.lbl_summary = QLabel()
        self.lbl_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.lbl_summary)
        layout.addSpacing(12)
        filter_box = QWidget()
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addStretch(1)
        filter_title = QLabel("Show:")
        filter_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        filter_layout.addWidget(filter_title)
        self.filter_all = QRadioButton("All")
        self.filter_front = QRadioButton("Needs front choice")
        self.filter_back = QRadioButton("Has back scan")
        self.filter_all.setChecked(True)
        self.filter_group = QButtonGroup(self)
        for i, rb in enumerate((self.filter_all, self.filter_front, self.filter_back)):
            rb.setStyleSheet("font-size: 14px;")
            self.filter_group.addButton(rb, i)
            filter_layout.addWidget(rb)
        self.filter_group.idClicked.connect(self._on_filter_id)
        filter_layout.addStretch(1)
        layout.addWidget(filter_box)
        layout.addSpacing(12)
        self.btn_start = self._big_button("Start Review  →", min_height=70)
        self.btn_start.setFixedWidth(340)
        self.btn_start.clicked.connect(self.start_review)
        layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        change = QPushButton("Choose a different folder")
        change.clicked.connect(self.browse)
        layout.addWidget(change, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        reset = QPushButton("Reset saved progress…")
        reset.setStyleSheet("color: #a66;")
        reset.clicked.connect(self.reset_progress)
        layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        self.btn_organize = QPushButton("Move single scans…")
        self.btn_organize.clicked.connect(self.organize_single_scans)
        layout.addWidget(self.btn_organize, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        self.btn_reviewed = QPushButton("Move reviewed originals…")
        self.btn_reviewed.clicked.connect(self.move_reviewed_originals)
        layout.addWidget(self.btn_reviewed, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return page

    def _build_front_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._progress_row())
        self.lbl_front_header = self._header()
        layout.addWidget(self.lbl_front_header)

        images = QHBoxLayout()
        panel_primary, self.lbl_primary_caption, self.img_primary = self._image_panel(
            "Primary scan", lambda direction: self.rotate_candidate("primary", direction))
        panel_secondary, self.lbl_secondary_caption, self.img_secondary = self._image_panel(
            "Second scan (_a)", lambda direction: self.rotate_candidate("secondary", direction))
        images.addWidget(panel_primary)
        images.addWidget(panel_secondary)
        layout.addLayout(images, 1)

        buttons = QHBoxLayout()
        self.btn_use_primary = self._big_button("Use PRIMARY\nas Best Front  (1)")
        self.btn_use_secondary = self._big_button("Use SECONDARY (_a)\nas Best Front  (2)")
        self.btn_use_primary.clicked.connect(lambda: self.choose_front("primary"))
        self.btn_use_secondary.clicked.connect(lambda: self.choose_front("secondary"))
        buttons.addWidget(self.btn_use_primary)
        buttons.addWidget(self.btn_use_secondary)
        layout.addLayout(buttons)
        layout.addWidget(self._hint("Tip: press 1 or 2 on your keyboard. "
                                    "Use ⟲ / ⟳ under a photo to rotate it."))
        return page

    def _build_stitch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._progress_row())
        self.lbl_stitch_header = self._header()
        layout.addWidget(self.lbl_stitch_header)

        images = QHBoxLayout()
        panel_best, self.lbl_best_caption, self.img_best = self._image_panel(
            "Best front", lambda direction: self.rotate_review_image("front", direction))
        panel_back, self.lbl_back_caption, self.img_back = self._image_panel(
            "Back of photo (_b)", lambda direction: self.rotate_review_image("back", direction))
        images.addWidget(panel_best)
        images.addWidget(panel_back)
        layout.addLayout(images, 1)

        grid = QGridLayout()
        self.btn_stitch_top = self._big_button("⬆  Stitch TOP  (↑)", 64)
        self.btn_stitch_bottom = self._big_button("⬇  Stitch BOTTOM  (↓)", 64)
        self.btn_stitch_left = self._big_button("⬅  Stitch LEFT  (←)", 64)
        self.btn_stitch_right = self._big_button("➡  Stitch RIGHT  (→)", 64)
        self.btn_stitch_top.clicked.connect(lambda: self.choose_stitch("top"))
        self.btn_stitch_bottom.clicked.connect(lambda: self.choose_stitch("bottom"))
        self.btn_stitch_left.clicked.connect(lambda: self.choose_stitch("left"))
        self.btn_stitch_right.clicked.connect(lambda: self.choose_stitch("right"))
        grid.addWidget(self.btn_stitch_top, 0, 0)
        grid.addWidget(self.btn_stitch_bottom, 0, 1)
        grid.addWidget(self.btn_stitch_left, 1, 0)
        grid.addWidget(self.btn_stitch_right, 1, 1)
        layout.addLayout(grid)

        self.btn_skip_stitch = self._big_button("Skip Stitching — keep front only  (S)", 64)
        self.btn_skip_stitch.clicked.connect(self.skip_stitching)
        layout.addWidget(self.btn_skip_stitch)
        layout.addWidget(self._hint(
            "The back scan is scaled proportionally to match the shared edge; "
            "the front scan is never resampled."
        ))
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._progress_row())
        self.lbl_preview_header = self._header()
        layout.addWidget(self.lbl_preview_header)
        panel_preview, _, self.img_preview = self._image_panel("Stitched result (preview)")
        layout.addWidget(panel_preview, 1)

        buttons = QHBoxLayout()
        self.btn_change_direction = self._big_button("← Change direction", 70)
        self.btn_change_direction.clicked.connect(self.change_direction)
        self.btn_save_next = self._big_button("Save & Next  →  (Enter)", 70)
        self.btn_save_next.setStyleSheet(
            "font-size: 16px; font-weight: bold; padding: 10px;"
            "background: #2e7d32; color: white;"
        )
        self.btn_save_next.clicked.connect(self.save_stitched)
        self.btn_save_next.setDefault(True)
        buttons.addWidget(self.btn_change_direction)
        buttons.addWidget(self.btn_save_next)
        layout.addLayout(buttons)
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        self.lbl_done = QLabel()
        self.lbl_done.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_done.setWordWrap(True)
        self.lbl_done.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.lbl_done)
        layout.addSpacing(20)
        buttons = QHBoxLayout()
        self.btn_open_completed = self._big_button("Open 'completed' folder", 60)
        self.btn_open_completed.clicked.connect(self.open_completed)
        self.btn_back_to_summary = self._big_button("← Back to summary", 60)
        self.btn_back_to_summary.clicked.connect(self._back_to_summary)
        self.btn_another_folder = self._big_button("Review another folder", 60)
        self.btn_another_folder.clicked.connect(self.browse)
        buttons.addWidget(self.btn_open_completed)
        buttons.addWidget(self.btn_back_to_summary)
        buttons.addWidget(self.btn_another_folder)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    # -- wizard flow -----------------------------------------------------------

    def browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select folder with scanned photos"
        )
        if directory:
            self.load_directory(Path(directory))

    def _back_to_summary(self) -> None:
        """Return to the summary page, refreshing the queue from saved progress."""
        if self.source_dir is not None:
            self.load_directory(self.source_dir)

    def load_directory(self, directory: Path, requeue_finished: bool = False) -> None:
        """Scan a folder and show the review summary (also used by tests)."""
        self.source_dir = directory
        self.state = ReviewState(directory)
        if self.state.corrupt:
            QMessageBox.warning(
                self, "Progress file unreadable",
                "The saved progress file was corrupt, so progress was reset.\n"
                f"{self.state.corrupt}",
            )
        # Restore rotations saved by an earlier session.
        self.rotations = dict(self.state.data["rotations"])
        auto_moved_single = 0
        if self.auto_move_single_scans:
            self.auto_move_single_scans = False  # one-shot per folder choice
            auto_moved_single = len(move_single_scans(directory))
        auto_moved_reviewed = 0
        if self.auto_move_reviewed_originals:
            self.auto_move_reviewed_originals = False  # one-shot per folder choice
            auto_moved_reviewed = len(move_reviewed_originals(directory, self.state))
        completed_dir = directory / COMPLETED_DIR_NAME
        fresh: list[PhotoGroup] = []
        already = 0
        for group in scan_directory(directory):
            status = self.state.status_of(group.base)
            has_front = group.primary is not None or group.secondary is not None
            if status == "skipped" and has_front:
                # A front scan appeared since the skip — requeue the group.
                self.state.mark_pending(group.base)
                status = "pending"
            if status == "done" or (
                not requeue_finished
                and (completed_dir / f"{group.base}.jpg").exists()
            ):
                already += 1  # finished in a previous run
            elif status == "skipped":
                already += 1  # unprocessable (no front scan)
            else:
                fresh.append(group)
        self.pending_groups = fresh
        self.index = 0
        self._already_count = already
        self._auto_moved_single_count = auto_moved_single
        self._auto_moved_reviewed_count = auto_moved_reviewed

        n_single_scans = len(single_scan_groups(directory))
        self.btn_organize.setText(
            f"Move {n_single_scans} single scan(s) to '{SINGLE_SCANS_DIR_NAME}'…"
        )
        self.btn_organize.setEnabled(n_single_scans > 0)

        n_reviewed_files = sum(
            1 for g in reviewed_groups(directory, self.state)
            for f in (g.primary, g.secondary, g.back) if f is not None
        )
        self.btn_reviewed.setText(
            f"Move {n_reviewed_files} reviewed original(s) to '{REVIEWED_ORIGINALS_DIR_NAME}'…"
        )
        self.btn_reviewed.setEnabled(n_reviewed_files > 0)

        if not fresh:
            self.current_filter = "all"
            self.filter_all.setChecked(True)
            self._apply_filter()  # keeps self.groups consistent (empty)
            if n_reviewed_files == 0 and n_single_scans == 0:
                QMessageBox.information(
                    self, "Nothing to review",
                    "No photo groups need review in this folder."
                    + (f"\n({already} already finished or skipped.)" if already else "")
                    + (f"\n({auto_moved_single} single scan(s) moved to '{SINGLE_SCANS_DIR_NAME}'.)" if auto_moved_single else "")
                    + (f"\n({auto_moved_reviewed} reviewed original(s) moved to '{REVIEWED_ORIGINALS_DIR_NAME}'.)" if auto_moved_reviewed else "")
                    + "\n\nGroups containing only a primary scan are ignored.",
                )
                self.stack.setCurrentWidget(self.page_welcome)
                return
            # Everything is reviewed, but finished originals / primary-only
            # scans are still sitting in the folder — land on the summary
            # page so the move buttons stay reachable.
            QMessageBox.information(
                self, "Nothing left to review",
                "No photo groups need review in this folder."
                + (f"\n({already} already finished or skipped.)" if already else "")
                + "\n\nYou can still move the finished originals or "
                  "single scans below.",
            )
            self.stack.setCurrentWidget(self.page_summary)
            return

        self.current_filter = "all"
        self.filter_all.setChecked(True)
        self._apply_filter()
        self.stack.setCurrentWidget(self.page_summary)

    # -- queue filtering ---------------------------------------------------------

    @staticmethod
    def _matches_filter(group: PhotoGroup, filt: str) -> bool:
        if filt == "front":
            return group.primary is not None and group.secondary is not None
        if filt == "back":
            return group.back is not None
        return True

    @staticmethod
    def _group_kind(group: PhotoGroup) -> str:
        kinds = []
        if group.primary is not None and group.secondary is not None:
            kinds.append("front choice")
        if group.back is not None:
            kinds.append("back scan")
        return " + ".join(kinds)

    def _on_filter_id(self, idx: int) -> None:
        self._set_filter(self._filter_keys[idx])

    def _set_filter(self, filt: str) -> None:
        if filt == self.current_filter:
            return
        self.current_filter = filt
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Recompute the review queue from the pending groups + current filter."""
        filt = self.current_filter
        self.groups = [g for g in self.pending_groups if self._matches_filter(g, filt)]
        self.index = 0
        self.filter_all.setText(f"All ({len(self.pending_groups)})")
        self.filter_front.setText(
            "Needs front choice ("
            f"{sum(1 for g in self.pending_groups if self._matches_filter(g, 'front'))})")
        self.filter_back.setText(
            "Has back scan ("
            f"{sum(1 for g in self.pending_groups if self._matches_filter(g, 'back'))})")
        self._update_summary_text()

    def _update_summary_text(self) -> None:
        total = len(self.pending_groups)
        n = len(self.groups)
        filt_desc = {"all": "all groups",
                     "front": "groups needing a front choice",
                     "back": "groups with a back scan"}[self.current_filter]
        summary = (
            f"Review queue: <b>{n}</b> of <b>{total}</b> pending group(s) "
            f"({filt_desc}) in:<br>{self.source_dir}<br><br>"
            "Each group has a second front scan (_a), a back scan (_b), or both.<br>"
            "Finished images are saved to a <b>'completed'</b> subfolder.<br>"
            "Progress is tracked automatically — you can close the app and resume later."
        )
        if self._already_count:
            summary += f"<br><br>{self._already_count} group(s) already finished or skipped."
        if self._auto_moved_single_count:
            summary += (f"<br><br>Moved <b>{self._auto_moved_single_count}</b> single scan(s) "
                        f"to '<b>{SINGLE_SCANS_DIR_NAME}</b>'.")
        if self._auto_moved_reviewed_count:
            summary += (f"<br><br>Moved <b>{self._auto_moved_reviewed_count}</b> reviewed original(s) "
                        f"to '<b>{REVIEWED_ORIGINALS_DIR_NAME}</b>'.")
        if n == 0 and total > 0:
            summary += "<br><br><b>No groups match this filter — choose another.</b>"
        self.lbl_summary.setText(summary)
        self.btn_start.setEnabled(n > 0)
        self.statusBar().showMessage(f"{n} group(s) queued for review.")

    def reset_progress(self) -> None:
        """Clear the saved progress for this folder (keeps 'completed' files)."""
        if self.state is None or self.source_dir is None:
            return
        reply = QMessageBox.question(
            self, "Reset progress?",
            "Clear the saved review progress for this folder?\n\n"
            "Images already saved in 'completed' are kept, but every group "
            "will be queued for review again (re-saved files get numbered names).\n"
            "Originals previously moved to 'reviewed_originals' stay there.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.state.path.unlink(missing_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self, "Reset failed",
                f"Could not delete the progress file:\n{exc}",
            )
            return
        self.rotations = {}
        self.load_directory(self.source_dir, requeue_finished=True)

    def organize_single_scans(self) -> None:
        """Move single scans into a 'single_scans' subfolder (with confirm)."""
        if self.source_dir is None:
            return
        groups = single_scan_groups(self.source_dir)
        if not groups:
            QMessageBox.information(
                self, "Nothing to move",
                "No single scans found — everything is already organized.",
            )
            return
        reply = QMessageBox.question(
            self, "Move single scans?",
            f"Move {len(groups)} scan(s) with only a primary front "
            f"(no _a/_b files) into a '{SINGLE_SCANS_DIR_NAME}' subfolder?\n\n"
            "These photos don't need review, so this keeps the folder tidy.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        moved = move_single_scans(self.source_dir)
        QMessageBox.information(
            self, "Organized",
            f"Moved {len(moved)} scan(s) to '{SINGLE_SCANS_DIR_NAME}/'.",
        )
        self.load_directory(self.source_dir)  # refresh the queue and summary

    def move_reviewed_originals(self) -> None:
        """Move originals of reviewed groups into a 'reviewed_originals' subfolder (with confirm)."""
        if self.source_dir is None:
            return
        groups = reviewed_groups(self.source_dir, self.state)
        n_files = sum(1 for g in groups
                      for f in (g.primary, g.secondary, g.back) if f is not None)
        if not n_files:
            QMessageBox.information(
                self, "Nothing to move",
                "No reviewed originals found — nothing to move.",
            )
            return
        reply = QMessageBox.question(
            self, "Move reviewed originals?",
            f"Move {n_files} original file(s) from {len(groups)} reviewed group(s) "
            f"into a '{REVIEWED_ORIGINALS_DIR_NAME}' subfolder?\n\n"
            "These are the source scans for photos you have already finished reviewing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        moved = move_reviewed_originals(self.source_dir, self.state)
        QMessageBox.information(
            self, "Organized",
            f"Moved {len(moved)} original file(s) to '{REVIEWED_ORIGINALS_DIR_NAME}/'.",
        )
        self.load_directory(self.source_dir)  # refresh the queue and summary

    def start_review(self) -> None:
        self.index = 0
        self._advance_to_next_group()

    # -- per-group steps ---------------------------------------------------------

    def _release_images(self) -> None:
        for attr in ("front_img", "back_img", "result_img"):
            img = getattr(self, attr)
            if img is not None:
                img.close()
            setattr(self, attr, None)

    def _progress_text(self, step: str) -> str:
        total = len(self.groups)
        base = self.current.base if self.current else ""
        text = f"{step}   •   Group {self.index + 1} of {total}   •   {base}"
        kind = self._group_kind(self.current) if self.current else ""
        if kind:
            text += f"   •   {kind}"
        return text

    # -- rotation ---------------------------------------------------------------

    def _load_oriented(self, path: Path) -> Image.Image:
        """Load a scan at full resolution with the user's rotation applied."""
        return orient_image(load_image(path), self.rotations.get(path.name, 0))

    def _caption(self, label: str, path: Path) -> str:
        """Panel caption showing the file name plus any rotation applied."""
        text = f"{label}\n{path.name}"
        turns = self.rotations.get(path.name, 0) % 4
        if turns == 1:
            text += "  ⟳90°"
        elif turns == 2:
            text += "  ⟳180°"
        elif turns == 3:
            text += "  ⟲90°"
        return text

    def _persist_rotations(self) -> None:
        if self.state is not None:
            self.state.persist_rotations(self.rotations)

    def rotate_candidate(self, which: str, direction: int = 1) -> None:
        """Rotate one front candidate 90° (Step 1). direction: +1 CW, -1 CCW."""
        group = self.current
        assert group is not None
        path = group.primary if which == "primary" else group.secondary
        assert path is not None
        self.rotations[path.name] = (self.rotations.get(path.name, 0) + direction) % 4
        self._persist_rotations()
        img = self._load_oriented(path)
        pixmap = display_pixmap(img)
        img.close()
        if which == "primary":
            self.img_primary.set_image(pixmap)
            self.lbl_primary_caption.setText(self._caption("Primary scan", path))
        else:
            self.img_secondary.set_image(pixmap)
            self.lbl_secondary_caption.setText(self._caption("Second scan (_a)", path))

    def rotate_review_image(self, which: str, direction: int = 1) -> None:
        """Rotate the best front or back scan 90° (Step 2). +1 CW, -1 CCW."""
        assert self.current is not None
        op = Image.ROTATE_270 if direction > 0 else Image.ROTATE_90
        if which == "front":
            assert self.front_img is not None and self.best_front_path is not None
            path, label = self.best_front_path, "Best front"
            self.front_img = self.front_img.transpose(op)
            self.img_best.set_image(display_pixmap(self.front_img))
            self.lbl_best_caption.setText(self._caption(label, path))
        else:
            assert self.back_img is not None and self.current.back is not None
            path, label = self.current.back, "Back of photo (_b)"
            self.back_img = self.back_img.transpose(op)
            self.img_back.set_image(display_pixmap(self.back_img))
            self.lbl_back_caption.setText(self._caption(label, path))
        self.rotations[path.name] = (self.rotations.get(path.name, 0) + direction) % 4
        self._persist_rotations()

    def _advance_to_next_group(self) -> None:
        """Load the next group, or finish when the queue is empty."""
        self._release_images()
        self.last_stitch_direction = None
        while self.index < len(self.groups):
            group = self.groups[self.index]
            self.current = group
            fronts = [p for p in (group.primary, group.secondary) if p]
            if not fronts:
                if self.state is not None:
                    self.state.mark_skipped(group.base, "no_front_scan")
                QMessageBox.warning(
                    self, "Skipped",
                    f"'{group.base}' has a back scan but no front scan — skipping it.",
                )
                self.index += 1
                continue
            self.statusBar().showMessage(
                f"Group {self.index + 1} of {len(self.groups)}: {group.base}"
            )
            if group.primary and group.secondary:
                self._show_front_step(group)
            else:
                # Only one front scan exists — it wins by default.
                self.best_front_path = fronts[0]
                self._begin_back_step_or_finish(group)
            return
        self._show_done()

    def _show_front_step(self, group: PhotoGroup) -> None:
        try:
            with self._busy("Loading scans…"):
                primary_img = self._load_oriented(group.primary)  # type: ignore[arg-type]
                secondary_img = self._load_oriented(group.secondary)  # type: ignore[arg-type]
                self.img_primary.set_image(display_pixmap(primary_img))
                self.img_secondary.set_image(display_pixmap(secondary_img))
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not load images",
                f"Skipping '{group.base}': {exc}",
            )
            self.index += 1
            self._advance_to_next_group()
            return
        primary_img.close()
        secondary_img.close()
        self.lbl_primary_caption.setText(self._caption("Primary scan", group.primary))  # type: ignore[arg-type]
        self.lbl_secondary_caption.setText(self._caption("Second scan (_a)", group.secondary))  # type: ignore[arg-type]
        self.lbl_front_header.setText(
            self._progress_text("Step 1 of 2 — pick the best front")
        )
        self._update_progress()
        self.stack.setCurrentWidget(self.page_front)

    def choose_front(self, which: str) -> None:
        """Store the user's best-front choice and continue."""
        group = self.current
        assert group is not None
        self.best_front_path = group.primary if which == "primary" else group.secondary
        self._begin_back_step_or_finish(group)

    def _begin_back_step_or_finish(self, group: PhotoGroup) -> None:
        try:
            assert self.best_front_path is not None
            with self._busy("Loading scans…"):
                self.front_img = self._load_oriented(self.best_front_path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not load image",
                f"Skipping '{group.base}': {exc}",
            )
            self.index += 1
            self._advance_to_next_group()
            return
        if group.back is None:
            self._save_front_only()
            return
        try:
            with self._busy("Loading scans…"):
                self.back_img = self._load_oriented(group.back)
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not load back scan",
                f"'{group.base}': {exc}\nSaving the front scan only.",
            )
            self._save_front_only()
            return
        self.img_best.set_image(display_pixmap(self.front_img))
        self.img_back.set_image(display_pixmap(self.back_img))
        assert self.best_front_path is not None
        self.lbl_best_caption.setText(self._caption("Best front", self.best_front_path))
        self.lbl_back_caption.setText(self._caption("Back of photo (_b)", group.back))  # type: ignore[arg-type]
        self.lbl_stitch_header.setText(
            self._progress_text("Step 2 of 2 — stitch the back (optional)")
        )
        self._update_progress()
        self.stack.setCurrentWidget(self.page_stitch)

    def choose_stitch(self, direction: str) -> None:
        """Stitch the back onto the front (worker thread) and show a preview."""
        group = self.current
        assert group is not None and group.back is not None
        assert self.best_front_path is not None
        front_path = self.best_front_path
        back_path = group.back
        front_turns = self.rotations.get(front_path.name, 0)
        back_turns = self.rotations.get(back_path.name, 0)
        self.last_stitch_direction = direction

        def on_stitched(result_img: Image.Image) -> None:
            self.result_img = result_img
            self.img_preview.set_image(display_pixmap(result_img))
            self._update_progress()
            self.lbl_preview_header.setText(
                self._progress_text(f"Preview — back stitched {direction.upper()}")
            )
            assert self.current is not None
            self.statusBar().showMessage(
                f"Previewing '{self.current.base}' stitched {direction} "
                f"({result_img.width}×{result_img.height}px)"
            )
            self.stack.setCurrentWidget(self.page_preview)

        self._run_in_background(
            "Stitching images…", stitch_job, on_stitched,
            front_path, front_turns, back_path, back_turns, direction,
        )

    def change_direction(self) -> None:
        """Go back to the stitch-direction step (nothing saved yet)."""
        if self.result_img is not None:
            self.result_img.close()
            self.result_img = None
        self.stack.setCurrentWidget(self.page_stitch)

    def skip_stitching(self) -> None:
        self._save_front_only()

    # -- saving ------------------------------------------------------------------

    def _completed_dir(self) -> Path:
        assert self.source_dir is not None
        return self.source_dir / COMPLETED_DIR_NAME

    def _save_front_only(self) -> None:
        """Save the chosen front (byte-for-byte copy unless it was rotated)."""
        assert self.current is not None and self.best_front_path is not None
        out = unique_output_path(self._completed_dir(), self.current.base)
        turns = self.rotations.get(self.best_front_path.name, 0) % 4
        front_path = self.best_front_path

        def on_saved(saved_out: Path) -> None:
            note = (f"Saved {saved_out.name} (rotated {turns * 90}°)" if turns
                    else f"Saved {saved_out.name} (original quality, no stitching)")
            self._record_done(saved_out, stitched=None)
            self.statusBar().showMessage(note)
            self.index += 1
            self._advance_to_next_group()

        if turns:
            # Rotated: re-encode the oriented image off the GUI thread
            # (EXIF already corrected on load).
            self._run_in_background(
                "Saving image…", save_oriented_job, on_saved,
                front_path, turns, out, JPEG_QUALITY,
            )
        else:
            shutil.copy2(front_path, out)
            on_saved(out)

    def save_stitched(self) -> None:
        """Save the stitched preview at full resolution (worker thread)."""
        assert self.current is not None and self.result_img is not None
        out = unique_output_path(self._completed_dir(), self.current.base)
        result_img = self.result_img  # not touched on the GUI thread until done

        def on_saved(saved_out: Path) -> None:
            self._record_done(saved_out, stitched=self.last_stitch_direction)
            self.statusBar().showMessage(f"Saved stitched image as {saved_out.name}")
            self.index += 1
            self._advance_to_next_group()

        self._run_in_background(
            "Saving stitched image…", save_image_job, on_saved,
            result_img, out, JPEG_QUALITY,
        )

    def _record_done(self, out: Path, stitched: str | None) -> None:
        """Record the finished group's choices in the progress file."""
        assert self.current is not None
        assert self.best_front_path is not None
        assert self.state is not None
        record: dict = {
            "best_front": self.best_front_path.name,
            "front_rotations": self.rotations.get(self.best_front_path.name, 0) % 4,
            "stitched": stitched,
            "output": out.name,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if self.current.back is not None:
            record["back_rotations"] = self.rotations.get(self.current.back.name, 0) % 4
        self.state.mark_done(self.current.base, record)

    def _show_done(self) -> None:
        self.lbl_done.setText(
            f"<b>All done!</b><br><br>"
            f"Reviewed {len(self.groups)} photo group(s).<br>"
            f"Finished images are in:<br>{self._completed_dir()}"
        )
        self.statusBar().showMessage("Review complete.")
        self.stack.setCurrentWidget(self.page_done)

    def open_completed(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._completed_dir())))

    # -- keyboard shortcuts --------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
        page = self.stack.currentWidget()
        key = event.key()
        if page is self.page_front:
            if key == Qt.Key.Key_1:
                self.choose_front("primary")
            elif key == Qt.Key.Key_2:
                self.choose_front("secondary")
            else:
                super().keyPressEvent(event)
        elif page is self.page_stitch:
            directions = {
                Qt.Key.Key_Up: "top",
                Qt.Key.Key_Down: "bottom",
                Qt.Key.Key_Left: "left",
                Qt.Key.Key_Right: "right",
            }
            if key in directions:
                self.choose_stitch(directions[key])
            elif key in (Qt.Key.Key_S, Qt.Key.Key_Escape):
                self.skip_stitching()
            else:
                super().keyPressEvent(event)
        elif page is self.page_preview:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.save_stitched()
            elif key == Qt.Key.Key_Backspace:
                self.change_direction()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

