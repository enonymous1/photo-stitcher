"""File grouping and organizing for FastFoto-style scans.

Groups files like ``FastFoto_0158.jpg`` / ``_a.jpg`` / ``_b.jpg`` by base
name, and moves single-scan or already-reviewed originals aside.
Qt-free: usable without PyQt6 installed.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .constants import (
    COMPLETED_DIR_NAME,
    GROUP_PATTERN,
    IMAGE_EXTENSIONS,
    SINGLE_SCANS_DIR_NAME,
    REVIEWED_ORIGINALS_DIR_NAME,
)

if TYPE_CHECKING:
    from .state import ReviewState


@dataclass
class PhotoGroup:
    """One base name and the scan files that belong to it."""
    base: str
    primary: Path | None = None    # [Base].jpg
    secondary: Path | None = None  # [Base]_a.jpg
    back: Path | None = None       # [Base]_b.jpg



def scan_directory(directory: Path, *, include_single_scans: bool = False) -> list[PhotoGroup]:
    """Group scan files by base name.

    Only groups that contain an ``_a`` and/or ``_b`` file are queued;
    groups with just the primary front scan are ignored unless
    ``include_single_scans`` is set.
    """
    groups: dict[str, PhotoGroup] = {}
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        match = GROUP_PATTERN.match(entry.stem)
        if not match:
            continue
        base = match.group("base")
        suffix = (match.group("suffix") or "").lower()
        group = groups.setdefault(base, PhotoGroup(base=base))
        if suffix == "a":
            group.secondary = entry
        elif suffix == "b":
            group.back = entry
        else:
            group.primary = entry
    queued: list[PhotoGroup] = []
    for g in groups.values():
        needs_review = g.secondary is not None or g.back is not None
        single_scans = g.primary is not None and not needs_review
        if needs_review or (include_single_scans and single_scans):
            queued.append(g)
    queued.sort(key=lambda g: g.base.lower())
    return queued



def single_scan_groups(directory: Path) -> list[PhotoGroup]:
    """Groups that have only the primary front scan (no _a/_b files)."""
    return [
        g for g in scan_directory(directory, include_single_scans=True)
        if g.primary is not None and g.secondary is None and g.back is None
    ]



def move_single_scans(directory: Path) -> list[tuple[Path, Path]]:
    """Move single scans into a ``single_scans`` subfolder.

    Returns a list of ``(source, destination)`` pairs for the files moved.
    """
    target = directory / SINGLE_SCANS_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    for group in single_scan_groups(directory):
        assert group.primary is not None
        src = group.primary
        dst = target / src.name
        n = 2
        while dst.exists():
            dst = target / f"{src.stem}_{n}{src.suffix}"
            n += 1
        shutil.move(str(src), str(dst))
        moved.append((src, dst))
    return moved



def reviewed_groups(directory: Path, state: ReviewState | None = None) -> list[PhotoGroup]:
    """Groups considered finished: marked done in state or output exists.

    "Reviewed" means the group was reviewed and its final image saved —
    either recorded in the progress file or evidenced by an output file in
    ``completed/`` (covers runs from before the state file existed).
    """
    completed_dir = directory / COMPLETED_DIR_NAME
    result = []
    for group in scan_directory(directory, include_single_scans=True):
        done = (completed_dir / f"{group.base}.jpg").exists()
        if not done and state is not None and state.status_of(group.base) == "done":
            done = True
        if done:
            result.append(group)
    return result



def move_reviewed_originals(directory: Path, state: ReviewState | None = None) -> list[tuple[Path, Path]]:
    """Move originals of reviewed groups into a ``reviewed_originals`` subfolder.

    Moves every source scan (primary, _a, _b) belonging to a finished group.
    Returns a list of ``(source, destination)`` pairs for the files moved.
    """
    target = directory / REVIEWED_ORIGINALS_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    for group in reviewed_groups(directory, state):
        for src in (group.primary, group.secondary, group.back):
            if src is None:
                continue
            dst = target / src.name
            n = 2
            while dst.exists():
                dst = target / f"{src.stem}_{n}{src.suffix}"
                n += 1
            shutil.move(str(src), str(dst))
            moved.append((src, dst))
    return moved



def unique_output_path(completed_dir: Path, base: str) -> Path:
    """Return ``completed/[base].jpg``, adding a numeric suffix if taken."""
    completed_dir.mkdir(parents=True, exist_ok=True)
    candidate = completed_dir / f"{base}.jpg"
    n = 2
    while candidate.exists():
        candidate = completed_dir / f"{base}_{n}.jpg"
        n += 1
    return candidate

