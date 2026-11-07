"""Dispositivo REAL (python.py): gateway de borde que mide su propio hardware y publica por MQTT.

Se ejecuta en un PC o Raspberry Pi fuera de la nube y se conecta al bróker del servidor:
    pip install paho-mqtt psutil requests
    python real_device.py --host <dominio-o-ip> --user <MQTT_USER> --password <MQTT_PASS>
"""
import argparse
import os
import socket
import time

import psutil

from common import CFG, Device


class Gateway(Device):
    def __init__(self, interval: float):
        super().__init__("RL-GW-01", interval)
        self._net = psutil.net_io_counters()
        self._t = time.monotonic()
        psutil.cpu_percent(interval=None)   # la primera lectura siempre es 0

    def latency_ms(self):
        t0 = time.perf_counter()
        try:
            with socket.create_connection((CFG["host"], CFG["port"]), timeout=3):
                return (time.perf_counter() - t0) * 1000
        except OSError:
            return None

    def read(self):
        net, t = psutil.net_io_counters(), time.monotonic()
        moved = (net.bytes_sent + net.bytes_recv) - (self._net.bytes_sent + self._net.bytes_recv)
        kbps = moved / 1024 / max(t - self._t, 1e-3)
        self._net, self._t = net, t
        return {
            "cpu_pct": psutil.cpu_percent(interval=None),
            "ram_pct": psutil.virtual_memory().percent,
            "disco_pct": psutil.disk_usage(os.path.abspath(os.sep)).percent,
            "red_kbps": kbps,
            "latencia_ms": self.latency_ms(),
        }

    def extra_state(self):
        return {"host": socket.gethostname(), "os": os.name}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=CFG["host"])
    ap.add_argument("--port", type=int, default=CFG["port"])
    ap.add_argument("--user", default=CFG["user"])
    ap.add_argument("--password", default=CFG["password"])
    ap.add_argument("--interval", type=float, default=10)
    a = ap.parse_args()
    CFG.update(host=a.host, port=a.port, user=a.user, password=a.password)
    Gateway(a.interval).run_forever()
