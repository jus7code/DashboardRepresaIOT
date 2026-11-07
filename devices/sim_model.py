"""Gemelo digital simplificado de la represa: balance hídrico + respuesta estructural.

Lluvia, sismos y demanda eléctrica dependen sólo de la fecha, de modo que el histórico
sembrado (seed_history.py) y la ejecución en vivo (twins.py) cuentan la misma historia.
Los comandos de retroceso (apertura de compuerta, potencia) cambian la física del embalse.
"""
import math
import random
import threading
from datetime import datetime, timedelta, timezone

AREA_M2 = 30e6      # espejo de agua efectivo
CREST = 312.0       # cota de cresta del vertedero (msnm)
NAMO = 330.0        # nivel máximo de operación normal (msnm)
TAILWATER = 165.0   # cota de descarga aguas abajo (msnm)
UNITS = 3           # unidades de generación con el mismo despacho
UTC_OFFSET = -5     # hora de Colombia


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def local_hour(t: datetime) -> float:
    return (t.timestamp() / 3600 + UTC_OFFSET) % 24


def local_day(t: datetime) -> int:
    return (t + timedelta(hours=UTC_OFFSET)).date().toordinal()


def rain_mm_h(t: datetime, station: int = 0) -> float:
    """Aguacero convectivo de la tarde (patrón típico de Santander), ~60 % de los días."""
    rng = random.Random(local_day(t) * 7919 + station * 104729)
    if rng.random() > 0.6:
        return 0.0
    start = 12.5 + rng.random() * 6
    dur = 0.8 + rng.random() * 3
    peak = 3 + rng.random() ** 2 * 45
    h = local_hour(t)
    if start <= h <= start + dur:
        return peak * math.sin(math.pi * (h - start) / dur)
    return 0.0


def quake_on(day: int):
    """Microsismo del nido de Bucaramanga en ~20 % de los días: (hora local, PGA en g)."""
    rng = random.Random(day * 31337)
    if rng.random() > 0.2:
        return None
    return rng.random() * 24, 0.015 + rng.random() ** 3 * 0.09


def demand_mw(h: float) -> float:
    p = (150 + 70 * math.exp(-((h - 19.5) / 2.0) ** 2) + 35 * math.exp(-((h - 11.5) / 3.0) ** 2)
         - 45 * math.exp(-((h - 3.5) / 2.5) ** 2))
    return clamp(p, 60, 280)


class DamModel:
    def __init__(self, level: float = 318.0, t: datetime | None = None):
        self.lock = threading.Lock()
        self.t = t or datetime.now(timezone.utc)
        self.level = level
        self.runoff = 0.0
        self.rain = 0.0
        self.pore = self._pore_eq(level)
        self.gate = self.gate_sp = 0.0
        self.gate_mode = "auto"
        self.gate_moving = False
        self.power = self.power_sp = demand_mw(local_hour(self.t))
        self.power_mode = "auto"
        self.bearing = 48 + 0.09 * self.power
        self.turbidity = 8.0
        self.creep = 0.0
        self.quake = 0.0
        self.q_in = self.q_turb = self.q_spill = 0.0
        self.step(0, self.t)   # caudales coherentes antes de la primera lectura

    @staticmethod
    def _pore_eq(level: float) -> float:
        return (level - 215) * 9.81 * 0.62

    # ---- retroceso
    def set_gate(self, value: float | None = None, mode: str | None = None):
        with self.lock:
            if mode:
                self.gate_mode = mode
            if value is not None:
                self.gate_sp, self.gate_mode = clamp(float(value), 0, 100), "manual"

    def set_power(self, value: float | None = None, mode: str | None = None):
        with self.lock:
            if mode:
                self.power_mode = mode
            if value is not None:
                self.power_sp, self.power_mode = clamp(float(value), 0, 280), "manual"

    # ---- física
    def step(self, dt: float, t: datetime | None = None):
        with self.lock:
            prev = self.t
            self.t = t or prev + timedelta(seconds=dt)
            h = local_hour(self.t)

            # Hidrología: lluvia -> escorrentía retardada (~4 h) -> caudal de entrada
            self.rain = rain_mm_h(self.t)
            self.runoff += (self.rain * 70 - self.runoff) * min(dt / (4 * 3600), 1)
            self.q_in = max(50.0, 420 + 35 * math.sin(2 * math.pi * (h - 6) / 24) + self.runoff)

            # Generación: sigue la demanda (auto) o la consigna del operador (manual)
            if self.power_mode == "auto":
                self.power_sp = demand_mw(h)
            self.power += clamp(self.power_sp - self.power, -0.5 * dt, 0.5 * dt)
            head = max(self.level - TAILWATER, 50)
            self.q_turb = UNITS * self.power / (0.008829 * head)   # P = ρ·g·Q·H·η
            self.bearing += (48 + 0.09 * self.power - self.bearing) * min(dt / 1800, 1)

            # Vertedero: apertura automática sobre 325 msnm, o consigna manual
            if self.gate_mode == "auto":
                self.gate_sp = clamp((self.level - 325) * 20, 0, 100)
            self.gate_moving = abs(self.gate_sp - self.gate) > 0.05
            self.gate += clamp(self.gate_sp - self.gate, -0.05 * dt, 0.05 * dt)
            self.q_spill = 4200 * self.gate / 100 * math.sqrt(max(self.level - CREST, 0) / (NAMO - CREST))

            # Balance hídrico y respuesta de la estructura
            self.level += (self.q_in - self.q_turb - self.q_spill) * dt / AREA_M2
            self.pore += (self._pore_eq(self.level) - self.pore) * min(dt / (12 * 3600), 1)
            self.turbidity += (6 + self.runoff * 0.11 - self.turbidity) * min(dt / (3 * 3600), 1)
            self.creep += dt * 0.015 / 86400

            self.quake *= math.exp(-dt / 600)
            for day in {local_day(prev), local_day(self.t)}:
                q = quake_on(day)
                if not q:
                    continue
                event = datetime.fromordinal(day).replace(tzinfo=timezone.utc) + timedelta(hours=q[0] - UTC_OFFSET)
                if prev < event <= self.t:
                    self.quake = max(self.quake, q[1])
                    self.creep += q[1] * 2

    def readings(self) -> dict[str, dict[str, float]]:
        g = random.gauss
        with self.lock:
            h, lv = local_hour(self.t), self.level
            daily = lambda shift: math.sin(2 * math.pi * (h - shift) / 24)  # noqa: E731
            return {
                "DT-NIV-01": {
                    "nivel_msnm": lv + g(0, 0.01),
                    "volumen_hm3": 4800 * ((lv - 200) / 130) ** 2.5,
                    "caudal_entrada_m3s": self.q_in + g(0, 5),
                },
                "DT-PZ-01": {
                    "presion_poro_kpa": self.pore + g(0, 1.5),
                    "temp_c": 16.2 + 0.3 * daily(16) + g(0, 0.05),
                },
                "DT-INC-01": {
                    "inclinacion_x_mm_m": 0.6 + 0.02 * (lv - 300) + 0.08 * daily(15) + 0.2 * self.creep + g(0, 0.01),
                    "inclinacion_y_mm_m": -0.3 + 0.01 * (lv - 300) + g(0, 0.01),
                    "desplazamiento_mm": 3.5 + 0.12 * (lv - 300) + 0.4 * daily(15) + self.creep + g(0, 0.03),
                },
                "DT-COMP-01": {
                    "apertura_pct": self.gate,
                    "setpoint_pct": self.gate_sp,
                    "corriente_motor_a": (32 if self.gate_moving else 1.5) + g(0, 0.4),
                    "caudal_vertido_m3s": self.q_spill,
                },
                "DT-TURB-01": {
                    "potencia_mw": max(self.power + g(0, 0.6), 0),
                    "caudal_planta_m3s": self.q_turb,
                    "rpm": 180 + g(0, 0.3) if self.power > 5 else 0.0,
                    "temp_rodamiento_c": self.bearing + g(0, 0.2),
                },
                "DT-SIS-01": {
                    "pga_g": 0.002 + abs(g(0, 0.0008)) + self.quake,
                    "frecuencia_hz": 4.8 + g(0, 0.25) + self.quake * 10,
                    "vibracion_mm_s": 0.8 + self.power * 0.006 + self.quake * 40 + abs(g(0, 0.08)),
                },
                "DT-CAL-01": {
                    "ph": 7.3 + 0.25 * daily(9) - 0.0006 * self.runoff + g(0, 0.02),
                    "turbidez_ntu": self.turbidity + abs(g(0, 0.8)),
                    "oxigeno_mg_l": 7.2 + 0.8 * daily(8) - 0.004 * self.turbidity + g(0, 0.05),
                    "temp_agua_c": 24.5 + 1.6 * daily(10) + g(0, 0.05),
                },
                "DT-FIL-01": {
                    "filtracion_l_s": 18 + 1.1 * (lv - 300) + self.quake * 80 + g(0, 0.4),
                    "turbiedad_filtracion_ntu": 1.2 + self.quake * 60 + abs(g(0, 0.2)),
                },
            }
