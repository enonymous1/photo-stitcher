"""Progress tracking: pause/resume review state in a JSON file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .constants import STATE_FILENAME


class ReviewState:
    """Persists review progress to a JSON file inside the source directory.

    Lets the user close the app mid-queue and resume later: finished groups
    are skipped on reload, image rotations are restored, and every finished
    group keeps a small audit record of the choices made.
    """

    def __init__(self, directory: Path) -> None:
        self.path = directory / STATE_FILENAME
        self.data: dict = {"version": 1, "groups": {}, "rotations": {}}
        self.corrupt: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError("unsupported state file version")
            groups = raw.get("groups", {})
            rotations = raw.get("rotations", {})
            if not isinstance(groups, dict) or not isinstance(rotations, dict):
                raise ValueError("malformed state file")
            self.data["groups"] = groups
            self.data["rotations"] = {
                str(name): int(turns) % 4
                for name, turns in rotations.items()
                if isinstance(turns, int)
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            backup = self.path.with_name(STATE_FILENAME + ".bak")
            try:
                if backup.exists():
                    backup.unlink()
                self.path.rename(backup)
            except OSError:
                pass
            self.corrupt = f"{exc} (backed up to {backup.name})"

    def save(self) -> None:
        tmp = self.path.with_name(STATE_FILENAME + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def status_of(self, base: str) -> str:
        entry = self.data["groups"].get(base)
        if isinstance(entry, dict):
            return str(entry.get("status", "pending"))
        return "pending"

    def mark_done(self, base: str, record: dict) -> None:
        self.data["groups"][base] = {"status": "done", **record}
        self.save()

    def mark_skipped(self, base: str, reason: str) -> None:
        self.data["groups"][base] = {"status": "skipped", "reason": reason}
        self.save()

    def mark_pending(self, base: str) -> None:
        if base in self.data["groups"]:
            del self.data["groups"][base]
            self.save()

    def persist_rotations(self, rotations: dict[str, int]) -> None:
        self.data["rotations"] = {
            name: turns % 4 for name, turns in rotations.items() if turns % 4
        }
        self.save()

