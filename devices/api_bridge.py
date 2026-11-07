"""Dispositivos API: Azure Maps Weather (condiciones actuales y calidad del aire).

Consulta la API por HTTPS y envía las lecturas al backend por HTTP REST (/api/ingest).
El retroceso (encendido, intervalo de consulta, calibración) llega por MQTT como en los demás.
"""
import os
import time

import requests

from common import Device

AZURE_KEY = os.getenv("AZURE_MAPS_KEY", "")
LAT = os.getenv("AZURE_MAPS_LAT", "7.0170")
LON = os.getenv("AZURE_MAPS_LON", "-73.4160")
INTERVAL = float(os.getenv("API_INTERVAL", "300"))
BASE = "https://atlas.microsoft.com/weather"


def dig(d: dict, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


class AzureMapsDevice(Device):
    endpoint = ""
    api_version = "1.1"
    params: dict = {}

    def __init__(self, device_id: str):
        super().__init__(device_id, INTERVAL, transport="http")

    def fetch(self) -> dict:
        r = requests.get(f"{BASE}/{self.endpoint}/json", timeout=20, params={
            "api-version": self.api_version, "query": f"{LAT},{LON}", "language": "es-MX",
            "subscription-key": AZURE_KEY, **self.params})
        r.raise_for_status()
        return r.json()["results"][0]

    def extra_state(self):
        return {"source": f"atlas.microsoft.com/weather/{self.endpoint}", "query": f"{LAT},{LON}"}


class CurrentConditions(AzureMapsDevice):
    endpoint, params = "currentConditions", {"details": "true", "unit": "metric"}

    def read(self):
        r = self.fetch()
        return {
            "temp_c": dig(r, "temperature", "value"),
            "sensacion_c": dig(r, "realFeelTemperature", "value"),
            "humedad_pct": r.get("relativeHumidity"),
            "presion_mb": dig(r, "pressure", "value"),
            "viento_kmh": dig(r, "wind", "speed", "value"),
            "precip_1h_mm": dig(r, "precipitationSummary", "pastHour", "value"),
            "uv_index": r.get("uvIndex"),
            "nubosidad_pct": r.get("cloudCover"),
        }


class AirQuality(AzureMapsDevice):
    endpoint, params = "airQuality/current", {"pollutants": "true"}

    def read(self):
        r = self.fetch()
        values = {"ica": r.get("globalIndex", r.get("index"))}
        for p in r.get("pollutants", []):
            key = p.get("type", "").lower().replace(".", "_")
            if key in ("pm2_5", "pm10", "o3", "no2", "co"):
                values[key] = dig(p, "concentration", "value")
        return values


if __name__ == "__main__":
    if not AZURE_KEY:
        raise SystemExit("Falta AZURE_MAPS_KEY")
    CurrentConditions("API-WX-01").start()
    AirQuality("API-AQ-01").start()
    while True:
        time.sleep(3600)
