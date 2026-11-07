"""Dispositivos DATASET: reproducen un CSV hidrológico como si fueran sensores en campo.

Cada tick envía la siguiente fila al backend por HTTP REST. Por defecto el CSV tiene una
fila cada 10 min y se reproduce cada 60 s (10x); el intervalo y la fila se ajustan por retroceso.
"""
import csv
import os
import time
from pathlib import Path

from common import Device

CSV_PATH = Path(os.getenv("DATASET_CSV", Path(__file__).parent / "data" / "dataset_hidrologico.csv"))
INTERVAL = float(os.getenv("DATASET_INTERVAL", "60"))
COLUMNS = {
    "DS-RIO-01": ["caudal_rio_m3s", "nivel_rio_m"],
    "DS-PLU-01": ["precip_mm", "precip_acum_24h_mm"],
}


def load_rows(device_id: str) -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["estacion"] == device_id]


class Player(Device):
    def __init__(self, device_id: str):
        super().__init__(device_id, INTERVAL, transport="http")
        self.rows = load_rows(device_id)
        self.i = int(time.time() // 600) % len(self.rows)   # continúa tras reinicios

    def read(self):
        row = self.rows[self.i]
        self.i = (self.i + 1) % len(self.rows)
        return {c: float(row[c]) for c in COLUMNS[self.id] if row.get(c)}

    def custom(self, action, value):
        if action == "setpoint":
            self.i = int(float(value)) % len(self.rows)
            return f"reproducción movida a la fila {self.i}"
        return super().custom(action, value)

    def extra_state(self):
        return {"file": CSV_PATH.name, "row": self.i, "rows": len(self.rows),
                "row_ts": self.rows[self.i]["timestamp_utc"]}


if __name__ == "__main__":
    for dev_id in COLUMNS:
        Player(dev_id).start()
    while True:
        time.sleep(3600)
