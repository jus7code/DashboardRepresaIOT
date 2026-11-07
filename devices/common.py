"""Clase base de los dispositivos IoT.

Cada dispositivo:
  - publica telemetría por MQTT (represa/<id>/telemetry) o por HTTP REST (/api/ingest)
  - publica su estado retenido en represa/<id>/status, con LWT {"online": false}
  - escucha comandos de retroceso en represa/<id>/cmd y responde en represa/<id>/ack
    acciones: power, interval, calibrate, reset (+ setpoint / mode según el dispositivo)
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

CFG = {
    "host": os.getenv("MQTT_HOST", "localhost"),
    "port": int(os.getenv("MQTT_PORT", "1883")),
    "user": os.getenv("MQTT_USER", ""),
    "password": os.getenv("MQTT_PASS", ""),
    "backend": os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/"),
    "ingest_key": os.getenv("INGEST_KEY", ""),
}
ROOT = "represa"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Device:
    def __init__(self, device_id: str, interval: float = 15, transport: str = "mqtt"):
        self.id = device_id
        self.interval = self.default_interval = interval
        self.transport = transport
        self.power = True
        self.offsets: dict[str, float] = {}
        self.gains: dict[str, float] = {}
        self.seq = 0
        self.log = logging.getLogger(device_id)
        self._wake = threading.Event()

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{device_id}-{uuid.uuid4().hex[:6]}")
        if CFG["user"]:
            self.client.username_pw_set(CFG["user"], CFG["password"])
        self.client.will_set(self.topic("status"), json.dumps({"online": False}), qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)

    # ---- MQTT
    def topic(self, kind: str) -> str:
        return f"{ROOT}/{self.id}/{kind}"

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self.log.error("Conexión MQTT rechazada: %s", reason_code)
            return
        client.subscribe(self.topic("cmd"), qos=1)
        self.publish_status()
        self.log.info("Conectado a %s:%s", CFG["host"], CFG["port"])

    def _on_message(self, client, userdata, msg):
        try:
            cmd = json.loads(msg.payload)
        except ValueError:
            return
        ok, info = True, "ok"
        try:
            info = self.apply(cmd.get("action"), cmd.get("value"))
        except Exception as e:  # el error se devuelve en el ack
            ok, info = False, str(e)
        self.log.info("Comando %s=%r -> %s", cmd.get("action"), cmd.get("value"), info)
        client.publish(self.topic("ack"), json.dumps({"cmd_id": cmd.get("id"), "action": cmd.get("action"),
                                                       "ok": ok, "msg": info, "ts": now_iso()}), qos=1)
        self.publish_status()
        self._wake.set()

    def state(self) -> dict:
        return {"online": True, "power": "on" if self.power else "off", "interval": self.interval,
                "offsets": self.offsets, "gains": self.gains, "transport": self.transport, **self.extra_state()}

    def publish_status(self):
        self.client.publish(self.topic("status"), json.dumps(self.state()), qos=1, retain=True)

    # ---- retroceso
    def apply(self, action: str, value) -> str:
        if action == "power":
            self.power = str(value).lower() in ("on", "true", "1")
            return f"sensor {'encendido' if self.power else 'apagado'}"
        if action == "interval":
            v = float(value)
            if not 1 <= v <= 3600:
                raise ValueError("el intervalo debe estar entre 1 y 3600 s")
            self.interval = v
            return f"intervalo de muestreo {v:g} s"
        if action == "calibrate":
            var = value["variable"]
            self.offsets[var] = float(value.get("offset", 0))
            self.gains[var] = float(value.get("gain", 1))
            return f"{var} calibrado: ganancia {self.gains[var]:g}, offset {self.offsets[var]:g}"
        if action == "reset":
            self.power, self.interval = True, self.default_interval
            self.offsets.clear()
            self.gains.clear()
            self.on_reset()
            return "valores de fábrica restablecidos"
        return self.custom(action, value)

    def custom(self, action: str, value) -> str:
        raise ValueError(f"acción no soportada por {self.id}: {action}")

    def extra_state(self) -> dict:
        return {}

    def on_reset(self):
        pass

    # ---- lectura y envío
    def read(self) -> dict:
        raise NotImplementedError

    def calibrated(self, values: dict) -> dict:
        return {k: round(v * self.gains.get(k, 1.0) + self.offsets.get(k, 0.0), 4)
                for k, v in values.items() if v is not None}

    def send(self, values: dict, ts: str | None = None):
        payload = {"ts": ts or now_iso(), "seq": self.seq, "values": values}
        self.seq += 1
        if self.transport == "http":
            r = requests.post(f"{CFG['backend']}/api/ingest", json={"device_id": self.id, **payload},
                              headers={"X-API-Key": CFG["ingest_key"]}, timeout=15)
            r.raise_for_status()
        else:
            self.client.publish(self.topic("telemetry"), json.dumps(payload), qos=1)

    def run_forever(self):
        self.client.connect_async(CFG["host"], CFG["port"], keepalive=30)
        self.client.loop_start()
        while True:
            self._wake.clear()
            if self.power:
                try:
                    values = self.read()
                    if values:
                        self.send(self.calibrated(values))
                except Exception as e:
                    self.log.warning("Lectura/envío fallido: %s", e)
            self._wake.wait(self.interval)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name=self.id, daemon=True)
        t.start()
        return t
