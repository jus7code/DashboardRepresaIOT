"""Genera data/dataset_hidrologico.csv: 6 días, una fila cada 10 min por estación.

Patrón de lluvias de tarde y respuesta del río aguas arriba. Puede reemplazarse por un CSV
real (p. ej. IDEAM en datos.gov.co) con las mismas columnas.
"""
import csv
import random
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sim_model import rain_mm_h

START = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)   # 00:00 hora Colombia
DAYS, STEP = 6, timedelta(minutes=10)
OUT = Path(__file__).parent / "data" / "dataset_hidrologico.csv"


def main():
    rng = random.Random(42)
    OUT.parent.mkdir(exist_ok=True)
    rows, window, runoff = [], deque(maxlen=144), 0.0
    t = START
    while t < START + timedelta(days=DAYS):
        rate = rain_mm_h(t, station=1)
        precip = max(rate * STEP.total_seconds() / 3600 + (rng.gauss(0, 0.05) if rate else 0), 0)
        window.append(precip)
        runoff += (rate * 60 - runoff) * (STEP.total_seconds() / (3 * 3600))
        caudal = 260 + 25 * rng.random() + runoff
        ts = t.isoformat().replace("+00:00", "Z")
        rows.append({"timestamp_utc": ts, "estacion": "DS-PLU-01", "precip_mm": round(precip, 2),
                     "precip_acum_24h_mm": round(sum(window), 2), "caudal_rio_m3s": "", "nivel_rio_m": ""})
        rows.append({"timestamp_utc": ts, "estacion": "DS-RIO-01", "precip_mm": "", "precip_acum_24h_mm": "",
                     "caudal_rio_m3s": round(caudal, 1), "nivel_rio_m": round(0.35 * caudal ** 0.42, 3)})
        t += STEP
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} filas -> {OUT}")


if __name__ == "__main__":
    main()
