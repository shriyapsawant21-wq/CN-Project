"""Adaptive FEC threshold controller and feedback log writer."""

from __future__ import annotations

from config import HYSTERESIS, LOW_TO_MEDIUM, MEDIUM_TO_HIGH
from log_store import CONTROLLER_FIELDS, CsvRunStore


class AdaptiveController:
    def __init__(self, store: CsvRunStore, initial_level: int = 1):
        self.store = store
        self.level = initial_level

    def observe(self, timestamp: float, measured_loss: float, true_loss: float) -> int:
        # Hysteresis prevents rapid toggling close to either boundary.
        if self.level == 1 and measured_loss >= LOW_TO_MEDIUM:
            self.level = 2
        elif self.level == 2:
            if measured_loss >= MEDIUM_TO_HIGH:
                self.level = 3
            elif measured_loss < LOW_TO_MEDIUM - HYSTERESIS:
                self.level = 1
        elif self.level == 3 and measured_loss < MEDIUM_TO_HIGH - HYSTERESIS:
            self.level = 2
        self.store.append_rows(
            "controller.csv",
            CONTROLLER_FIELDS,
            [{
                "time": f"{timestamp:.9f}",
                "measured_loss": f"{measured_loss:.6f}",
                "level": self.level,
                "true_loss": f"{true_loss:.6f}",
            }],
        )
        return self.level
