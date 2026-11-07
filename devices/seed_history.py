"""Carga histórica opcional: N días de gemelos digitales y dataset hacia /api/ingest/batch.

Útil para probar el dashboard sin esperar; los datos reales (gateway y API de Azure Maps)
se acumulan solos desde el despliegue. Ejecutar una sola vez:
    docker compose run --rm twins python seed_history.py --days 5
"""
import argparse
from datetime import datetime, timedelta, timezone

import requests

from common import CFG
from dataset_player import COLUMNS, load_rows
from sim_model import DamModel


def post(batch: list[dict]):
    r = requests.post(f"{CFG['backend']}/api/ingest/batch", json={"records": batch},
                      headers={"X-API-Key": CFG["ingest_key"]}, timeout=300)
    r.raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=5)
    ap.add_argument("--step", type=int, default=120, help="segundos entre muestras de los gemelos")
    ap.add_argument("--level", type=float, default=317.5, help="nivel inicial del embalse (msnm)")
    args = ap.parse_args()

    end = datetime.now(timezone.utc).replace(microsecond=0)
    t = end - timedelta(days=args.days)
    model, batch, sent = DamModel(level=args.level, t=t), [], 0
    while t < end:
        t += timedelta(seconds=args.step)
        model.step(args.step, t)
        for dev, vals in model.readings().items():
            batch.append({"device_id": dev, "ts": t.isoformat(), "values": {k: round(v, 4) for k, v in vals.items()}})
        if len(batch) >= 2000:
            post(batch)
            sent += len(batch)
            batch = []
            print(f"gemelos: {sent} registros (hasta {t:%Y-%m-%d %H:%M} UTC)")

    # Dataset: las últimas filas del CSV se ubican en la línea de tiempo pasada (1 fila = 10 min)
    steps = int(args.days * 144)
    for dev, cols in COLUMNS.items():
        rows = load_rows(dev)[-steps:]
        for i, row in enumerate(rows):
            ts = end - timedelta(minutes=10 * (len(rows) - i))
            batch.append({"device_id": dev, "ts": ts.isoformat(), "values": {c: float(row[c]) for c in cols}})
    for i in range(0, len(batch), 2000):
        post(batch[i:i + 2000])
    print(f"Listo: {sent + len(batch)} registros. Nivel final del embalse {model.level:.2f} msnm")


if __name__ == "__main__":
    main()
