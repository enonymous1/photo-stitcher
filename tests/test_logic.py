"""Logic tests: grouping, imaging, state, organizing (no Qt needed)."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from photo_stitcher import constants  # noqa: E402
from photo_stitcher import grouping  # noqa: E402
from photo_stitcher import imaging  # noqa: E402
from photo_stitcher import state as state_mod  # noqa: E402


def make_jpg(path: Path, size, color):
    Image.new("RGB", size, color).save(path, "JPEG", quality=90)


def test_scan_grouping():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "FastFoto_0158.jpg", (800, 600), "red")
        make_jpg(d / "FastFoto_0158_a.jpg", (800, 600), "green")
        make_jpg(d / "FastFoto_0158_b.jpg", (400, 300), "blue")
        make_jpg(d / "FastFoto_0159.jpg", (800, 600), "red")      # primary only -> excluded by default
        make_jpg(d / "FastFoto_0160_b.jpg", (400, 300), "blue")   # back only -> queued
        make_jpg(d / "FastFoto_0161_a.jpg", (800, 600), "green")  # secondary only -> queued
        make_jpg(d / "FastFoto_0162.JPG", (800, 600), "red")      # uppercase ext, primary only -> excluded
        (d / "notes.txt").write_text("not an image")
        (d / "completed").mkdir()                                 # subdir ignored

        groups = grouping.scan_directory(d)
        by_base = {g.base: g for g in groups}
        assert sorted(by_base) == ["FastFoto_0158", "FastFoto_0160", "FastFoto_0161"], sorted(by_base)

        # include_single_scans=True surfaces the single-scan groups too
        all_groups = {g.base: g for g in grouping.scan_directory(d, include_single_scans=True)}
        assert sorted(all_groups) == ["FastFoto_0158", "FastFoto_0159",
                                      "FastFoto_0160", "FastFoto_0161", "FastFoto_0162"]
    print("scan grouping: OK")


def test_stitch_geometry():
    front = Image.new("RGB", (100, 200), (255, 0, 0))
    back = Image.new("RGB", (50, 50), (0, 0, 255))

    out = imaging.stitch_images(front, back, "bottom")
    assert out.size == (100, 300), out.size
    assert out.getpixel((50, 50)) == (255, 0, 0)
    assert out.getpixel((50, 250)) == (0, 0, 255)

    out = imaging.stitch_images(front, back, "top")
    assert out.size == (100, 300), out.size
    assert out.getpixel((50, 50)) == (0, 0, 255)
    assert out.getpixel((50, 250)) == (255, 0, 0)

    out = imaging.stitch_images(front, back, "right")
    assert out.size == (300, 200), out.size
    assert out.getpixel((50, 100)) == (255, 0, 0)
    assert out.getpixel((250, 100)) == (0, 0, 255)

    out = imaging.stitch_images(front, back, "left")
    assert out.size == (300, 200), out.size
    assert out.getpixel((50, 100)) == (0, 0, 255)
    assert out.getpixel((250, 100)) == (255, 0, 0)

    same = Image.new("RGB", (100, 40), (0, 255, 0))
    out = imaging.stitch_images(front, same, "bottom")
    assert out.size == (100, 240), out.size
    assert out.getpixel((10, 10)) == (255, 0, 0)

    try:
        imaging.stitch_images(front, back, "diagonal")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bad direction")
    print("stitch geometry: OK")


def test_unique_output_path():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        p1 = grouping.unique_output_path(d, "FastFoto_0158")
        assert p1 == d / "FastFoto_0158.jpg"
        p1.touch()
        p2 = grouping.unique_output_path(d, "FastFoto_0158")
        assert p2 == d / "FastFoto_0158_2.jpg", p2
    print("unique output path: OK")


def test_load_image_exif():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "orient.jpg"
        img = Image.new("RGB", (100, 50), "red")
        exif = img.getexif()
        exif[0x0112] = 6  # rotate 90 CW
        img.save(p, "JPEG", exif=exif)
        loaded = imaging.load_image(p)
        assert loaded.size == (50, 100), loaded.size
    print("EXIF transpose: OK")


def test_review_state_unit():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        st = state_mod.ReviewState(d)
        assert st.status_of("X") == "pending"
        assert st.corrupt is None

        st.mark_done("A", {"best_front": "A.jpg"})
        st.persist_rotations({"A.jpg": 1, "B.jpg": 0, "C.jpg": 5})
        st2 = state_mod.ReviewState(d)
        assert st2.status_of("A") == "done"
        assert st2.data["groups"]["A"]["best_front"] == "A.jpg"
        assert st2.data["rotations"] == {"A.jpg": 1, "C.jpg": 1}, st2.data["rotations"]

        st2.mark_skipped("B", "no_front_scan")
        assert state_mod.ReviewState(d).status_of("B") == "skipped"
        st2.mark_pending("B")
        assert state_mod.ReviewState(d).status_of("B") == "pending"

        (d / constants.STATE_FILENAME).write_text("{not json")
        st3 = state_mod.ReviewState(d)
        assert st3.corrupt is not None
        assert (d / (constants.STATE_FILENAME + ".bak")).exists()
        assert st3.status_of("A") == "pending"
    print("ReviewState unit: OK")


def test_move_single_scans():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "C.jpg", (800, 600), "red")
        make_jpg(d / "C_b.jpg", (400, 300), "blue")
        make_jpg(d / "D.JPG", (800, 600), "red")

        moved = grouping.move_single_scans(d)
        assert len(moved) == 2, moved
        assert (d / "single_scans" / "B.jpg").exists()
        assert (d / "single_scans" / "D.JPG").exists()
        assert not (d / "B.jpg").exists() and not (d / "D.JPG").exists()
        assert (d / "A.jpg").exists() and (d / "C_b.jpg").exists()
        assert grouping.single_scan_groups(d) == []
        assert [g.base for g in grouping.scan_directory(d)] == ["A", "C"]
        assert grouping.move_single_scans(d) == []

        make_jpg(d / "E.jpg", (800, 600), "red")
        (d / "single_scans" / "E.jpg").write_bytes(b"existing")
        moved = grouping.move_single_scans(d)
        assert moved[0][1] == d / "single_scans" / "E_2.jpg", moved
        assert (d / "single_scans" / "E_2.jpg").exists()
    print("move single scans: OK")


def test_move_reviewed_originals():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_jpg(d / "A.jpg", (800, 600), "red")
        make_jpg(d / "A_a.jpg", (800, 600), "green")
        make_jpg(d / "A_b.jpg", (400, 300), "blue")
        (d / "completed").mkdir()
        make_jpg(d / "completed" / "A.jpg", (800, 600), "red")
        make_jpg(d / "B.jpg", (800, 600), "red")
        make_jpg(d / "B_b.jpg", (400, 300), "blue")
        make_jpg(d / "C.jpg", (800, 600), "red")
        make_jpg(d / "completed" / "C.jpg", (800, 600), "red")

        moved = grouping.move_reviewed_originals(d)
        assert len(moved) == 4, moved  # A:3 + C:1
        for name in ("A.jpg", "A_a.jpg", "A_b.jpg", "C.jpg"):
            assert (d / "reviewed_originals" / name).exists(), name
            assert not (d / name).exists(), name
        assert (d / "B.jpg").exists() and (d / "B_b.jpg").exists()
        assert [g.base for g in grouping.scan_directory(d)] == ["B"]
        assert grouping.move_reviewed_originals(d) == []

        make_jpg(d / "E.jpg", (800, 600), "red")
        make_jpg(d / "E_a.jpg", (800, 600), "green")
        st = state_mod.ReviewState(d)
        st.mark_done("E", {"best_front": "E.jpg"})
        moved = grouping.move_reviewed_originals(d, st)
        assert len(moved) == 2, moved
        assert (d / "reviewed_originals" / "E.jpg").exists()

        make_jpg(d / "F.jpg", (800, 600), "red")
        make_jpg(d / "F_b.jpg", (400, 300), "blue")
        make_jpg(d / "completed" / "F.jpg", (800, 600), "red")
        (d / "reviewed_originals" / "F.jpg").write_bytes(b"existing")
        moved = grouping.move_reviewed_originals(d)
        dsts = sorted(p[1].name for p in moved)
        assert dsts == ["F_2.jpg", "F_b.jpg"], dsts
    print("move reviewed: OK")


def test_orient_image():
    img = Image.new("RGB", (100, 50), "red")
    assert imaging.orient_image(img, 0).size == (100, 50)
    assert imaging.orient_image(img, 1).size == (50, 100)   # 90° CW
    assert imaging.orient_image(img, 2).size == (100, 50)   # 180°
    assert imaging.orient_image(img, 3).size == (50, 100)   # 90° CCW
    assert imaging.orient_image(img, 5).size == (50, 100)   # 5 % 4 == 1
    print("orient image: OK")


if __name__ == "__main__":
    test_scan_grouping()
    test_stitch_geometry()
    test_unique_output_path()
    test_load_image_exif()
    test_orient_image()
    test_review_state_unit()
    test_move_single_scans()
    test_move_reviewed_originals()
    print("LOGIC TESTS PASSED")
