# photo-stitcher

A desktop wizard for reviewing, rotating, and stitching Epson FastFoto-style
photo scans.

## Origin

This started with an Epson FastFoto scanner and a pile of old family photos.
The scanner does a great job digitizing — front scans, plus back scans for
the handwritten notes on the reverse — but it leaves you with a folder of
files and no good way to pick the best front, pair each photo with its back,
or straighten the ones that came out sideways. This is the tool I wished
existed: a simple review pass over each photo, stitch the back on when you
want it, and end with a clean `completed/` folder.

It isn't affiliated with or endorsed by Epson; it just works with the
`[Base].jpg` / `[Base]_a.jpg` / `[Base]_b.jpg` naming the scanner produces,
and with any other scans renamed to match.

## Naming convention

```
FastFoto_0158.jpg      primary front scan
FastFoto_0158_a.jpg    optional second front scan
FastFoto_0158_b.jpg    optional back-of-photo scan
```

Files are grouped by base name. Groups with only a primary scan are ignored
by the review queue (they can be swept into `single_scans/` instead).

## Install

```bash
pip install -e .
```

This installs the `photo-stitch` command. Requires Python 3.10+.

## Run

```bash
photo-stitch [--move-single-scans] [--move-reviewed-originals]
# or
python -m photo_stitcher [--move-single-scans] [--move-reviewed-originals]
```

Workflow per group:

1. **Pick the best front** (side-by-side, when a `_a` scan exists).
2. **Optionally stitch the `_b` back scan** on (top / bottom / left / right),
   with a preview before committing. The back is scaled proportionally to
   match the shared edge; the front is never resampled.
3. **Save** the final full-resolution image to a `completed/` subfolder and
   move on automatically.

Every scan can be rotated 90° in either direction (lossless) from the button
under its preview. The summary screen can filter the queue to all groups,
groups needing a front choice, or groups with a back scan. A progress bar at
the top of each review step shows your position in the queue ("Group 3 of
12"). Image loading shows a brief busy indicator; stitching and saving run
on a worker thread behind a modal progress dialog, so the app stays
responsive even with large scans. When every group is finished, the summary
page stays available so the move-to-`reviewed_originals` / `single_scans` buttons
remain reachable.

Progress is tracked in `.photo_stitch_state.json` inside the source folder,
so you can close the app mid-queue and resume later: finished groups are
skipped, rotations are restored, and each finished group keeps an audit
record of your choices.

## Layout

```
src/photo_stitcher/
    constants.py   shared constants (folder names, patterns, quality)
    grouping.py    scan grouping + organizing (Qt-free)
    imaging.py     full-res loading + stitching via Pillow (Qt-free)
    state.py       progress tracking in JSON (Qt-free)
    cli.py         argparse + `photo-stitch` entry point
    gui/
        widgets.py Qt widgets (scalable image label, pixmap helpers)
        wizard.py   the review wizard (MainWindow)
        workers.py  QThreadPool workers: pure-Pillow stitch/save jobs
tests/
    test_logic.py       grouping / imaging / state / organizing tests
    test_guiflow_mock.py  full wizard flow with stubbed PyQt6 (headless)
```

The `grouping`, `imaging`, and `state` modules have no Qt dependency and can
be reused headlessly (e.g. batch-organizing scans from a script).

## Tests

```bash
python tests/test_logic.py
python tests/test_guiflow_mock.py
# or, with pytest installed:
python -m pytest tests/ -q
```

The GUI flow tests stub out PyQt6, so they run anywhere with Pillow
installed — no display or Qt system libraries needed.
