"""Cross-process, atomic storage for the agreed CSV log contract."""

from __future__ import annotations

import csv
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

PACKET_FIELDS = [
    "scheme", "scenario", "run", "seq", "block_id", "level",
    "payload_bytes", "send_time", "arrive_time", "recover_time",
]
BLOCK_FIELDS = [
    "block_id", "level", "k", "r", "parity_bytes", "send_time",
    "received_count", "recovered",
]
CONTROLLER_FIELDS = ["time", "measured_loss", "level", "true_loss"]


class CsvRunStore:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self, name: str, timeout: float = 10.0):
        lock_path = self.run_dir / f".{name}.lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for {lock_path}")
                time.sleep(0.005)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def _read(self, name: str) -> list[dict[str, str]]:
        path = self.run_dir / name
        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def _write(self, name: str, fields: list[str], rows: list[dict]) -> None:
        path = self.run_dir / name
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)

    def initialise(self) -> None:
        for name, fields in (
            ("packets.csv", PACKET_FIELDS),
            ("blocks.csv", BLOCK_FIELDS),
            ("controller.csv", CONTROLLER_FIELDS),
        ):
            with self._lock(name):
                if not (self.run_dir / name).exists():
                    self._write(name, fields, [])

    def has_packet_rows(self) -> bool:
        """Return True when a run directory already contains experiment data."""
        with self._lock("packets.csv"):
            return bool(self._read("packets.csv"))

    def append_rows(self, name: str, fields: list[str], new_rows: list[dict]) -> None:
        with self._lock(name):
            rows = self._read(name)
            rows.extend(new_rows)
            self._write(name, fields, rows)

    def update_rows(
        self, name: str, fields: list[str], predicate: Callable[[dict], bool], updates: dict
    ) -> None:
        with self._lock(name):
            rows = self._read(name)
            for row in rows:
                if predicate(row):
                    row.update(updates)
            self._write(name, fields, rows)
