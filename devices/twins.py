"""Gemelos digitales (8 dispositivos MQTT) sobre un modelo físico compartido de la represa."""
import logging
import os
import time
from datetime import datetime, timezone

import requests

from common import CFG, Device
from sim_model import DamModel

log = logging.getLogger("twins")
INTERVAL = float(os.getenv("TWIN_INTERVAL", "15"))


class Twin(Device):
    def __init__(self, device_id: str, model: DamModel):
        super().__init__(device_id, INTERVAL)
        self.model = model

    def read(self):
        return self.model.readings()[self.id]


class GateTwin(Twin):
    """Compuerta radial: consigna de apertura (%) y modo auto/manual."""

    def custom(self, action, value):
        if action == "setpoint":
            self.model.set_gate(value=float(value))
            return f"apertura objetivo {float(value):g} % (modo manual)"
        if action == "mode":
            self.model.set_gate(mode=str(value))
            return f"modo {value}"
        return super().custom(action, value)

    def extra_state(self):
        return {"mode": self.model.gate_mode, "setpoint": round(self.model.gate_sp, 1)}

    def on_reset(self):
        self.model.set_gate(mode="auto")


class TurbineTwin(Twin):
    """Unidad de generación: consigna de potencia (MW) y modo auto (sigue demanda) / manual."""

    def custom(self, action, value):
        if action == "setpoint":
            self.model.set_power(value=float(value))
            return f"potencia objetivo {float(value):g} MW (modo manual)"
        if action == "mode":
            self.model.set_power(mode=str(value))
            return f"modo {value}"
        return super().custom(action, value)

    def extra_state(self):
        return {"mode": self.model.power_mode, "setpoint": round(self.model.power_sp, 1)}

    def on_reset(self):
        self.model.set_power(mode="auto")


def initial_level() -> float:
    """Continúa desde el último nivel guardado para no romper la serie histórica."""
    try:
        devs = requests.get(f"{CFG['backend']}/api/devices", timeout=10).json()
        lv = next(d for d in devs if d["id"] == "DT-NIV-01")["last_values"].get("nivel_msnm")
        if lv:
            return float(lv)
    except Exception as e:
        log.info("Sin nivel previo (%s); se usa 318 msnm", e)
    return 318.0


def main():
    model = DamModel(level=initial_level())
    classes = {"DT-COMP-01": GateTwin, "DT-TURB-01": TurbineTwin}
    for dev_id in model.readings():
        classes.get(dev_id, Twin)(dev_id, model).start()

    last = time.monotonic()
    while True:  # física en tiempo real, independiente de que los sensores estén encendidos
        time.sleep(1)
        t = time.monotonic()
        model.step(t - last, datetime.now(timezone.utc))
        last = t


if __name__ == "__main__":
    main()
