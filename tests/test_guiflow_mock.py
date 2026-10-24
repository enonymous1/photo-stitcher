"""GUI flow tests with stubbed PyQt6: wizard logic, rotation, progress tracking,
organizing, queue filtering, and file outputs."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from stubs import install as install_qt_stubs  # noqa: E402

install_qt_stubs()

from PyQt6.QtWidgets import QMessageBox  # noqa: E402  (stubbed)

import photo_stitcher.gui.wizard as wizard_mod  # noqa: E402
from photo_stitcher import constants  # noqa: E402
from PIL import Image  # noqa: E402


def make_jpg(path: Path, size, color):
    Image.new("RGB", size, color).save(path, "JPEG", quality=90)


def make_window(**kwargs):
    w = wizard_mod.MainWindow(**kwargs)
    w.stack = mock.MagicMock()
    return w


def current_page(w):
    calls = w.stack.setCurrentWidget.call_args_list
    assert calls, "setCurrentWidget was never called"
    return calls[-1].args[0]


def _quiet():
    return (mock.patch.object(QMessageBox, "warning"),
            mock.patch.object(QMessageBox, "information"))


def test_full_wizard_flow():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "FastFoto_0158.jpg", (800, 600), "red")
        make_jpg(d / "FastFoto_0158_a.jpg", (800, 600), "green")
        make_jpg(d / "FastFoto_0158_b.jpg", (400, 300), "blue")
        make_jpg(d / "FastFoto_0160_b.jpg", (400, 300), "blue")
        make_jpg(d / "FastFoto_0161_a.jpg", (800, 600), "green")

        w = make_window()
        w.lbl_front_header = mock.MagicMock()  # capture header text
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert current_page(w) is w.page_summary
            assert [g.base for g in w.groups] == ["FastFoto_0158", "FastFoto_0160", "FastFoto_0161"]

            w.start_review()
            assert current_page(w) is w.page_front, current_page(w)
            header = w.lbl_front_header.setText.call_args.args[0]
            assert "front choice + back scan" in header, header
            w.choose_front("secondary")
            assert current_page(w) is w.page_stitch

            w.choose_stitch("bottom")
            assert current_page(w) is w.page_preview
            assert w.result_img.size == (800, 1200), w.result_img.size

            w.change_direction()
            assert current_page(w) is w.page_stitch
            assert w.result_img is None
            w.choose_stitch("right")
            assert w.result_img.size == (1600, 600), w.result_img.size

            w.save_stitched()
            assert current_page(w) is w.page_done

        completed = d / "completed"
        assert Image.open(completed / "FastFoto_0158.jpg").size == (1600, 600)
        assert (completed / "FastFoto_0161.jpg").read_bytes() == \
               (d / "FastFoto_0161_a.jpg").read_bytes()

        state_raw = json.loads((d / constants.STATE_FILENAME).read_text())
        assert state_raw["groups"]["FastFoto_0158"]["stitched"] == "right"
        assert state_raw["groups"]["FastFoto_0160"]["status"] == "skipped"

        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert w.groups == [], [g.base for g in w.groups]

        make_jpg(d / "FastFoto_0160.jpg", (800, 600), "red")
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert [g.base for g in w.groups] == ["FastFoto_0160"]

        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.start_review()
            assert current_page(w) is w.page_stitch
            w.skip_stitching()
            assert current_page(w) is w.page_done
            w._back_to_summary()
            # everything finished, but the originals are still in the folder,
            # so we land on the summary page (move-to-reviewed reachable)
            # instead of the welcome page
            assert current_page(w) is w.page_summary
            assert w.groups == []
    print("wizard flow (mock Qt): OK")


def test_skip_stitching_path():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "Pic.jpg", (800, 600), "red")
        make_jpg(d / "Pic_b.jpg", (400, 300), "blue")

        w = make_window()
        w.lbl_stitch_header = mock.MagicMock()  # capture header text
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.start_review()
            assert current_page(w) is w.page_stitch
            header = w.lbl_stitch_header.setText.call_args.args[0]
            assert "back scan" in header, header
            assert "front choice" not in header, header
            w.skip_stitching()
            assert current_page(w) is w.page_done
        assert (d / "completed" / "Pic.jpg").read_bytes() == (d / "Pic.jpg").read_bytes()
    print("skip stitching path: OK")


def test_empty_and_single_scans_dirs():
    w = make_window()
    w.btn_organize = mock.MagicMock()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "Solo.jpg", (100, 100), "red")
        with mock.patch.object(QMessageBox, "information") as info:
            w.load_directory(d)
            assert info.called
            # nothing to review, but the organize button stays reachable
            assert current_page(w) is w.page_summary
            w.btn_organize.setEnabled.assert_called_with(True)
    # truly empty dir -> welcome page
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        with mock.patch.object(QMessageBox, "information") as info:
            w.load_directory(d)
            assert info.called
            assert current_page(w) is w.page_welcome
    print("empty/single-scan dirs: OK")


def test_rotation_and_state_resume():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "A_b.jpg", (400, 300), "blue")

        w = make_window()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.start_review()
            assert current_page(w) is w.page_front

            w.rotate_candidate("primary")
            assert w.rotations == {"A.jpg": 1}
            state_raw = json.loads((d / constants.STATE_FILENAME).read_text())
            assert state_raw["rotations"] == {"A.jpg": 1}

            w.choose_front("primary")
            assert current_page(w) is w.page_stitch
            w.rotate_review_image("back")
            w.rotate_review_image("back")
            assert w.rotations == {"A.jpg": 1, "A_b.jpg": 2}

            w.choose_stitch("bottom")
            assert w.result_img.size == (600, 1250), w.result_img.size
            w.save_stitched()
            assert current_page(w) is w.page_done

        rec = json.loads((d / constants.STATE_FILENAME).read_text())["groups"]["A"]
        assert rec["status"] == "done"
        assert rec["best_front"] == "A.jpg"
        assert rec["front_rotations"] == 1
        assert rec["back_rotations"] == 2
        assert rec["stitched"] == "bottom"
        assert "finished_at" in rec
        assert Image.open(d / "completed" / "A.jpg").size == (600, 1250)

        w2 = make_window()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w2.load_directory(d)
            assert w2.groups == []
            assert w2.rotations == {"A.jpg": 1, "A_b.jpg": 2}
    print("rotation + state resume: OK")


def test_rotation_both_directions():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        img = Image.new("RGB", (100, 50))
        for x in range(100):
            for y in range(50):
                img.putpixel((x, y), (255, 0, 0) if x < 50 else (0, 0, 255))
        p = d / "T.png"
        img.save(p, "PNG")

        w = make_window()
        w.rotations = {"T.png": 1}  # 90° CW
        cw = w._load_oriented(p)
        assert cw.size == (50, 100), cw.size
        assert cw.getpixel((49, 0)) == (255, 0, 0)
        assert cw.getpixel((0, 99)) == (0, 0, 255)
        cw.close()

        w.rotations = {"T.png": 3}  # 90° CCW
        ccw = w._load_oriented(p)
        assert ccw.size == (50, 100), ccw.size
        assert ccw.getpixel((0, 99)) == (255, 0, 0)
        assert ccw.getpixel((0, 0)) == (0, 0, 255)
        ccw.close()

        w.rotations = {"T.png": 1}
        assert "⟳90°" in w._caption("X", p)
        w.rotations = {"T.png": 2}
        assert "⟳180°" in w._caption("X", p)
        w.rotations = {"T.png": 3}
        assert "⟲90°" in w._caption("X", p)

        make_jpg(d / "A.jpg", (100, 50), "red")
        make_jpg(d / "A_a.jpg", (100, 50), "green")
        w2 = make_window()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w2.load_directory(d)
            w2.start_review()
            assert current_page(w2) is w2.page_front
            w2.rotate_candidate("primary", -1)
            assert w2.rotations == {"A.jpg": 3}
            assert "⟲90°" in w2._caption("Primary scan", d / "A.jpg")
            w2.rotate_candidate("primary", -1)
            assert w2.rotations == {"A.jpg": 2}
    print("rotation directions: OK")


def test_front_only_rotated_save():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "B_b.jpg", (400, 300), "blue")

        w = make_window()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.start_review()
            assert current_page(w) is w.page_stitch
            w.rotate_review_image("front")
            w.skip_stitching()
            assert current_page(w) is w.page_done

        out = d / "completed" / "B.jpg"
        assert out.read_bytes() != (d / "B.jpg").read_bytes()
        assert Image.open(out).size == (600, 800)

        rec = json.loads((d / constants.STATE_FILENAME).read_text())["groups"]["B"]
        assert rec["front_rotations"] == 1
        assert rec["stitched"] is None
    print("front-only rotated save: OK")


def test_reset_progress():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "C.jpg", (800, 600), "red")
        make_jpg(d / "C_a.jpg", (800, 600), "green")

        w = make_window()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.start_review()
            w.choose_front("primary")
            assert current_page(w) is w.page_done
            assert (d / constants.STATE_FILENAME).exists()

            buttons = mock.MagicMock()
            with mock.patch.object(QMessageBox, "StandardButton", buttons), \
                 mock.patch.object(QMessageBox, "question", return_value=buttons.Yes):
                w.reset_progress()
            assert not (d / constants.STATE_FILENAME).exists()
            assert [g.base for g in w.groups] == ["C"]
            assert (d / "completed" / "C.jpg").exists()
    print("reset progress: OK")


def test_cli_flag_move_single_scans():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "B.jpg", (800, 600), "red")

        w = make_window(move_single_scans=True)
        w.btn_organize = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert current_page(w) is w.page_summary
            assert (d / "single_scans" / "B.jpg").exists()
            assert not (d / "B.jpg").exists()
            assert [g.base for g in w.groups] == ["A"]
            assert w.auto_move_single_scans is False
            w.btn_organize.setEnabled.assert_called_with(False)
    print("CLI flag move-single-scans: OK")


def test_organize_button():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "E.jpg", (800, 600), "red")

        w = make_window()
        w.btn_organize = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.btn_organize.setEnabled.assert_called_with(True)
            label = w.btn_organize.setText.call_args.args[0]
            assert "2" in label and "single_scans" in label, label

            buttons = mock.MagicMock()
            with mock.patch.object(QMessageBox, "StandardButton", buttons), \
                 mock.patch.object(QMessageBox, "question", return_value=buttons.Yes):
                w.organize_single_scans()

        assert (d / "single_scans" / "B.jpg").exists()
        assert (d / "single_scans" / "E.jpg").exists()
        assert [g.base for g in w.groups] == ["A"]
        w.btn_organize.setEnabled.assert_called_with(False)
    print("organize button: OK")


def test_cli_flag_move_reviewed_originals():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        (d / "completed").mkdir()
        make_jpg(d / "completed" / "A.jpg", (800, 600), "red")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "B_b.jpg", (400, 300), "blue")

        w = make_window(move_reviewed_originals=True)
        w.btn_reviewed = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert current_page(w) is w.page_summary
            assert (d / "reviewed_originals" / "A.jpg").exists()
            assert (d / "reviewed_originals" / "A_a.jpg").exists()
            assert not (d / "A.jpg").exists()
            assert [g.base for g in w.groups] == ["B"]
            assert w.auto_move_reviewed_originals is False
            w.btn_reviewed.setEnabled.assert_called_with(False)
    print("CLI flag move-reviewed-originals: OK")


def test_reviewed_button():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        (d / "completed").mkdir()
        make_jpg(d / "completed" / "A.jpg", (800, 600), "red")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "B_b.jpg", (400, 300), "blue")

        w = make_window()
        w.btn_reviewed = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.btn_reviewed.setEnabled.assert_called_with(True)
            label = w.btn_reviewed.setText.call_args.args[0]
            assert "2" in label and "reviewed_originals" in label, label

            buttons = mock.MagicMock()
            with mock.patch.object(QMessageBox, "StandardButton", buttons), \
                 mock.patch.object(QMessageBox, "question", return_value=buttons.Yes):
                w.move_reviewed_originals()

        assert (d / "reviewed_originals" / "A.jpg").exists()
        assert (d / "reviewed_originals" / "A_a.jpg").exists()
        assert [g.base for g in w.groups] == ["B"]
        w.btn_reviewed.setEnabled.assert_called_with(False)
    print("reviewed button: OK")


def test_queue_filter():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (10, 10), "red")
        make_jpg(d / "A_a.jpg", (10, 10), "red")
        make_jpg(d / "B.jpg", (10, 10), "red")
        make_jpg(d / "B_b.jpg", (10, 10), "red")
        make_jpg(d / "C.jpg", (10, 10), "red")
        make_jpg(d / "C_a.jpg", (10, 10), "red")
        make_jpg(d / "C_b.jpg", (10, 10), "red")
        make_jpg(d / "D_a.jpg", (10, 10), "red")

        w = make_window()
        w.btn_start = mock.MagicMock()
        w.filter_all = mock.MagicMock()
        w.filter_front = mock.MagicMock()
        w.filter_back = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            assert [g.base for g in w.groups] == ["A", "B", "C", "D"]
            assert "(4)" in w.filter_all.setText.call_args.args[0]
            assert "(2)" in w.filter_front.setText.call_args.args[0], \
                w.filter_front.setText.call_args.args[0]
            assert "(2)" in w.filter_back.setText.call_args.args[0]

            w._set_filter("front")
            assert [g.base for g in w.groups] == ["A", "C"]
            assert w.current_filter == "front"

            w._set_filter("back")
            assert [g.base for g in w.groups] == ["B", "C"]

            w._set_filter("all")
            assert [g.base for g in w.groups] == ["A", "B", "C", "D"]

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "B.jpg", (10, 10), "red")
        make_jpg(d / "B_b.jpg", (10, 10), "red")
        w = make_window()
        w.btn_start = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w._set_filter("front")
            assert w.groups == []
            w.btn_start.setEnabled.assert_called_with(False)
    print("queue filter: OK")


def test_progress_bar_updates():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "B_b.jpg", (400, 300), "blue")
        make_jpg(d / "C.jpg", (800, 600), "red")
        make_jpg(d / "C_b.jpg", (400, 300), "blue")

        w = make_window()
        assert len(w._progress_bars) == 3  # front, stitch, preview pages
        bars = [(mock.MagicMock(), mock.MagicMock()) for _ in range(3)]
        w._progress_bars = bars
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            w.start_review()  # group A at index 0
            for bar, label in bars:
                bar.setMaximum.assert_called_with(3)
                bar.setValue.assert_called_with(0)
                label.setText.assert_called_with("Group 1 of 3")

            # (group A has no _b, so choosing a front finishes it immediately)
            w.choose_front("primary")  # finish A -> group B at index 1
            for bar, label in bars:
                assert bar.setValue.call_args.args == (1,)
                assert label.setText.call_args.args == ("Group 2 of 3",)

            # empty queue -> graceful label
            w.groups = []
            w.index = 0
            w._update_progress()
            for bar, label in bars:
                assert label.setText.call_args.args == ("No groups",)
    print("progress bar updates: OK")


def test_busy_indicator():
    w = make_window()
    with mock.patch.object(wizard_mod, "QProgressDialog") as dlg_cls, \
         mock.patch.object(wizard_mod, "QApplication") as app_cls:
        dlg = dlg_cls.return_value
        with w._busy("Working…"):
            pass
        args = dlg_cls.call_args.args
        assert args[0] == "Working…"
        assert args[2] == 0 and args[3] == 0  # indeterminate range = busy spinner
        dlg.setMinimumDuration.assert_called_with(300)
        dlg.setCancelButton.assert_called_with(None)
        dlg.show.assert_called_once()
        app_cls.processEvents.assert_called_once()
        dlg.close.assert_called_once()

        # dialog is closed even if the work raises
        dlg.reset_mock()
        try:
            with w._busy("x"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        dlg.close.assert_called_once()
    print("busy indicator: OK")


def test_all_done_still_offers_move():
    # Regression: when every group is already finished, the app used to land
    # on the welcome page, hiding the "move reviewed originals" button.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "A_b.jpg", (400, 300), "blue")
        (d / "completed").mkdir()
        make_jpg(d / "completed" / "A.jpg", (800, 600), "red")  # A finished
        make_jpg(d / "B.jpg", (800, 600), "red")                # single-scan

        w = make_window()
        w.btn_reviewed = mock.MagicMock()
        w.btn_organize = mock.MagicMock()
        warn_patch, info_patch = _quiet()
        with warn_patch, info_patch:
            w.load_directory(d)
            # summary page (not welcome) so the move buttons are reachable
            assert current_page(w) is w.page_summary
            w.btn_reviewed.setEnabled.assert_called_with(True)
            label = w.btn_reviewed.setText.call_args.args[0]
            assert "3" in label, label  # A.jpg, A_a.jpg, A_b.jpg
            w.btn_organize.setEnabled.assert_called_with(True)

            buttons = mock.MagicMock()
            with mock.patch.object(QMessageBox, "StandardButton", buttons), \
                 mock.patch.object(QMessageBox, "question", return_value=buttons.Yes):
                w.move_reviewed_originals()
            # A's originals gone; B still single-scan -> summary again
            assert current_page(w) is w.page_summary
            assert not (d / "A.jpg").exists()
            with mock.patch.object(QMessageBox, "StandardButton", buttons), \
                 mock.patch.object(QMessageBox, "question", return_value=buttons.Yes):
                w.organize_single_scans()
            # truly nothing left -> welcome page
            assert current_page(w) is w.page_welcome
    print("all-done offers move: OK")


def test_worker_plumbing():
    from photo_stitcher.gui import workers as workers_mod
    results, errors = [], []
    wkr = workers_mod.PillowWorker(lambda a, b: a + b, 2, 3)
    wkr.signals.finished.connect(results.append)
    wkr.signals.error.connect(errors.append)
    wkr.run()
    assert results == [5] and not errors, (results, errors)

    results2, errors2 = [], []
    wkr2 = workers_mod.PillowWorker(lambda: 1 / 0)
    wkr2.signals.finished.connect(results2.append)
    wkr2.signals.error.connect(errors2.append)
    wkr2.run()
    assert results2 == [] and len(errors2) == 1
    assert "division by zero" in errors2[0], errors2
    print("worker plumbing: OK")


def test_run_in_background_wiring():
    w = make_window()
    with mock.patch.object(wizard_mod, "QProgressDialog") as dlg_cls:
        dlg = dlg_cls.return_value
        done: list = []
        w._run_in_background("Thinking…", lambda x: x * 2, done.append, 21)
        assert done == [42], done
        dlg.show.assert_called_once()
        dlg.close.assert_called_once()
        dlg.setCancelButton.assert_called_with(None)
        # error path: warning shown, dialog still closed, on_done not called
        with mock.patch.object(QMessageBox, "warning") as warn:
            w._run_in_background("Broken…", lambda: 1 / 0, done.append)
            warn.assert_called_once()
            assert done == [42]
            assert dlg.close.call_count == 2
    print("run_in_background wiring: OK")


if __name__ == "__main__":
    test_full_wizard_flow()
    test_skip_stitching_path()
    test_empty_and_single_scans_dirs()
    test_rotation_and_state_resume()
    test_rotation_both_directions()
    test_front_only_rotated_save()
    test_reset_progress()
    test_cli_flag_move_single_scans()
    test_organize_button()
    test_cli_flag_move_reviewed_originals()
    test_reviewed_button()
    test_queue_filter()
    test_progress_bar_updates()
    test_busy_indicator()
    test_all_done_still_offers_move()
    test_worker_plumbing()
    test_run_in_background_wiring()
    print("GUI FLOW TESTS PASSED")
