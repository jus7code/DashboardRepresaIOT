"""Backend IoT de la represa.

- Suscriptor MQTT (telemetría, estado y acuses de los dispositivos) -> PostgreSQL
- Ingesta HTTP REST para dispositivos API y dataset
- API REST para el dashboard (series, estadísticas, alertas, reglas)
- Retroceso: publica comandos MQTT hacia los dispositivos
- WebSocket para datos en vivo
"""
import asyncio
import json
import logging
import math
import operator
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiomqtt
import asyncpg
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import generate_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("represa")

DATABASE_URL = os.environ["DATABASE_URL"]
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER") or None
MQTT_PASS = os.getenv("MQTT_PASS") or None
INGEST_KEY = os.getenv("INGEST_KEY", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ROOT = "represa"
ALERT_COOLDOWN = timedelta(minutes=10)
ACTIONS = {"power", "interval", "calibrate", "reset", "setpoint", "mode"}
OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}

pool: asyncpg.Pool
mqtt: aiomqtt.Client | None = None
sockets: set[WebSocket] = set()
rules: list[dict] = []
known_devices: set[str] = set()
last_alert: dict[int, datetime] = {}
analysis_cache: dict[str, tuple[datetime, dict]] = {}


# ---------------------------------------------------------------- utilidades
def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(v: Any) -> datetime:
    if v in (None, ""):
        return now()
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def numeric(values: dict) -> dict[str, float]:
    return {
        k: float(v) for k, v in (values or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    }


RANGE_RE = re.compile(r"^(\d+)([mhd])$")


def resolve_range(rng: str | None, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    if start:
        t0, t1 = parse_ts(start), parse_ts(end) if end else now()
        if t1 <= t0:
            raise HTTPException(400, "El inicio debe ser anterior al fin")
        return t0, t1
    m = RANGE_RE.match(rng or "24h")
    if not m:
        raise HTTPException(400, "Rango inválido (use 15m, 6h, 5d...)")
    n, unit = int(m[1]), m[2]
    delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    if delta > timedelta(days=31):
        raise HTTPException(400, "Rango máximo: 31 días")
    t1 = now()
    return t1 - delta, t1


def require_admin(token: str):
    if not ADMIN_TOKEN or not secrets.compare_digest(token or "", ADMIN_TOKEN):
        raise HTTPException(401, "Token de operador inválido")


async def broadcast(msg: dict):
    if not sockets:
        return
    data = json.dumps(msg, default=str)
    for ws in list(sockets):
        try:
            await ws.send_text(data)
        except Exception:
            sockets.discard(ws)


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def load_catalog():
    global rules, known_devices
    rules = [dict(r) for r in await pool.fetch("SELECT * FROM rules ORDER BY id")]
    known_devices = {r["id"] for r in await pool.fetch("SELECT id FROM devices")}


# ------------------------------------------------------------------- ingesta
def check_rules(device_id: str, ts: datetime, vals: dict[str, float]) -> list[dict]:
    out = []
    for r in rules:
        if not r["enabled"] or r["device_id"] != device_id or r["variable"] not in vals:
            continue
        v = vals[r["variable"]]
        if not OPS[r["op"]](v, r["threshold"]):
            continue
        last = last_alert.get(r["id"])
        if last and timedelta(0) <= ts - last < ALERT_COOLDOWN:
            continue
        last_alert[r["id"]] = ts
        out.append({"ts": ts, "device_id": device_id, "variable": r["variable"], "value": v,
                    "rule_id": r["id"], "severity": r["severity"], "message": r["message"]})
    return out


async def store(records: list[tuple[str, datetime, dict[str, float]]], live: bool):
    """Guarda lecturas [(device_id, ts, {var: valor})], evalúa reglas y notifica."""
    unknown = {d for d, _, _ in records} - known_devices
    if unknown:
        await load_catalog()
        unknown -= known_devices
        if unknown:
            raise HTTPException(404, f"Dispositivo desconocido: {', '.join(sorted(unknown))}")

    records = sorted((r for r in records if r[2]), key=lambda r: r[1])
    if not records:
        return
    rows, latest, new_alerts = [], {}, []
    for dev, ts, vals in records:
        rows.extend((ts, dev, k, v) for k, v in vals.items())
        prev = latest.get(dev, (ts, {}))[1]
        latest[dev] = (ts, {**prev, **vals})
        new_alerts.extend(check_rules(dev, ts, vals))

    async with pool.acquire() as c, c.transaction():
        await c.copy_records_to_table("telemetry", records=rows, columns=["ts", "device_id", "variable", "value"])
        for dev, (ts, vals) in latest.items():
            await c.execute(
                """UPDATE devices SET
                     last_values = CASE WHEN last_seen IS NULL OR $2 >= last_seen THEN last_values || $3::jsonb ELSE last_values END,
                     last_seen = GREATEST(COALESCE(last_seen, $2), $2)
                   WHERE id = $1""", dev, ts, vals)
        saved = []
        for a in new_alerts:
            a["id"] = await c.fetchval(
                """INSERT INTO alerts (ts, device_id, variable, value, rule_id, severity, message)
                   VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
                a["ts"], a["device_id"], a["variable"], a["value"], a["rule_id"], a["severity"], a["message"])
            saved.append(a)

    if live:
        for dev, (ts, vals) in latest.items():
            await broadcast({"type": "telemetry", "device_id": dev, "ts": ts, "values": vals})
        for a in saved:
            await broadcast({"type": "alert", **a})


# ---------------------------------------------------------------------- MQTT
async def handle_mqtt(topic: str, payload: bytes):
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != ROOT:
        return
    _, dev, kind = parts
    try:
        data = json.loads(payload or b"{}")
    except ValueError:
        log.warning("JSON inválido en %s", topic)
        return

    if kind == "telemetry":
        await store([(dev, parse_ts(data.get("ts")), numeric(data.get("values", {})))], live=True)
    elif kind == "status":
        online = bool(data.get("online", False))
        await pool.execute(
            "UPDATE devices SET online = $2, state = state || $3::jsonb WHERE id = $1", dev, online, data)
        await broadcast({"type": "status", "device_id": dev, "online": online, "state": data})
    elif kind == "ack":
        status = "ok" if data.get("ok") else "error"
        await pool.execute(
            "UPDATE commands SET status = $2, response = $3, acked_at = now() WHERE id = $1",
            str(data.get("cmd_id")), status, data)
        await broadcast({"type": "ack", "device_id": dev, **data})


async def mqtt_loop():
    global mqtt
    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST, MQTT_PORT, username=MQTT_USER, password=MQTT_PASS,
                                      identifier=f"backend-{uuid.uuid4().hex[:8]}") as client:
                mqtt = client
                for kind in ("telemetry", "status", "ack"):
                    await client.subscribe(f"{ROOT}/+/{kind}", qos=1)
                log.info("MQTT conectado a %s:%s", MQTT_HOST, MQTT_PORT)
                async for msg in client.messages:
                    try:
                        await handle_mqtt(msg.topic.value, msg.payload)
                    except HTTPException as e:
                        log.warning("Mensaje descartado (%s): %s", msg.topic.value, e.detail)
                    except Exception:
                        log.exception("Error procesando %s", msg.topic.value)
        except aiomqtt.MqttError as e:
            mqtt = None
            log.warning("MQTT desconectado (%s); reintentando en 3 s", e)
            await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10, init=_init_conn)
    await load_catalog()
    task = asyncio.create_task(mqtt_loop())
    yield
    task.cancel()
    await pool.close()


app = FastAPI(title="Represa IoT", version="1.0", lifespan=lifespan)


# ------------------------------------------------------------- API: ingesta
class Reading(BaseModel):
    device_id: str
    ts: str | float | None = None
    values: dict[str, Any]


class Batch(BaseModel):
    records: list[Reading]


def require_ingest(key: str):
    if not INGEST_KEY or not secrets.compare_digest(key or "", INGEST_KEY):
        raise HTTPException(401, "X-API-Key inválida")


@app.post("/api/ingest")
async def ingest(r: Reading, x_api_key: str = Header("")):
    require_ingest(x_api_key)
    await store([(r.device_id, parse_ts(r.ts), numeric(r.values))], live=True)
    return {"ok": True}


@app.post("/api/ingest/batch")
async def ingest_batch(b: Batch, x_api_key: str = Header("")):
    require_ingest(x_api_key)
    await store([(r.device_id, parse_ts(r.ts), numeric(r.values)) for r in b.records], live=False)
    return {"ok": True, "records": len(b.records)}


# ------------------------------------------------------------ API: consulta
@app.get("/api/health")
async def health():
    return {"ok": True, "mqtt": mqtt is not None, "ts": now()}


@app.get("/api/devices")
async def devices():
    return [dict(r) for r in await pool.fetch("SELECT * FROM devices ORDER BY kind, id")]


@app.get("/api/series")
async def series(device_id: str, variable: str, range: str = "24h", start: str | None = None,
                 end: str | None = None, points: int = 240):
    t0, t1 = resolve_range(range, start, end)
    bucket = max((t1 - t0).total_seconds() / max(min(points, 2000), 10), 1.0)
    rows = await pool.fetch(
        """SELECT date_bin(make_interval(secs => $4), ts, TIMESTAMPTZ '2000-01-01') AS t,
                  avg(value) AS avg, min(value) AS min, max(value) AS max
           FROM telemetry
           WHERE device_id = $1 AND variable = $2 AND ts BETWEEN $3 AND $5
           GROUP BY 1 ORDER BY 1""", device_id, variable, t0, bucket, t1)
    return {"from": t0, "to": t1, "bucket_s": bucket, "points": [dict(r) for r in rows]}


@app.get("/api/stats")
async def stats(range: str = "24h", start: str | None = None, end: str | None = None,
                device_id: str | None = None):
    t0, t1 = resolve_range(range, start, end)
    rows = await pool.fetch(
        """SELECT device_id, variable, avg(value) AS avg, min(value) AS min, max(value) AS max,
                  stddev_samp(value) AS std, count(*) AS n
           FROM telemetry
           WHERE ts BETWEEN $1 AND $2 AND ($3::text IS NULL OR device_id = $3)
           GROUP BY 1, 2 ORDER BY 1, 2""", t0, t1, device_id)
    return {"from": t0, "to": t1, "stats": [dict(r) for r in rows]}


@app.get("/api/alerts")
async def alerts(range: str = "24h", start: str | None = None, end: str | None = None,
                 limit: int = 50):
    t0, t1 = resolve_range(range, start, end)
    rows = await pool.fetch(
        "SELECT * FROM alerts WHERE ts BETWEEN $1 AND $2 ORDER BY ts DESC LIMIT $3", t0, t1, min(limit, 500))
    total = await pool.fetchval(
        "SELECT count(*) FROM alerts WHERE ts BETWEEN $1 AND $2 AND NOT acknowledged", t0, t1)
    return {"open": total, "alerts": [dict(r) for r in rows]}


@app.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int, x_admin_token: str = Header("")):
    require_admin(x_admin_token)
    await pool.execute("UPDATE alerts SET acknowledged = TRUE WHERE id = $1", alert_id)
    return {"ok": True}


@app.get("/api/export.csv", response_class=PlainTextResponse)
async def export_csv(device_id: str, range: str = "5d", start: str | None = None, end: str | None = None):
    t0, t1 = resolve_range(range, start, end)
    rows = await pool.fetch(
        "SELECT ts, variable, value FROM telemetry WHERE device_id = $1 AND ts BETWEEN $2 AND $3 ORDER BY ts",
        device_id, t0, t1)
    lines = ["ts,variable,value"] + [f"{r['ts'].isoformat()},{r['variable']},{r['value']}" for r in rows]
    return PlainTextResponse("\n".join(lines), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{device_id}.csv"'})


# ----------------------------------------------------------- API: retroceso
class Command(BaseModel):
    action: str
    value: Any = None


@app.post("/api/devices/{device_id}/command")
async def command(device_id: str, cmd: Command, x_admin_token: str = Header("")):
    require_admin(x_admin_token)
    if cmd.action not in ACTIONS:
        raise HTTPException(400, f"Acción no permitida: {cmd.action}")
    if device_id not in known_devices:
        raise HTTPException(404, "Dispositivo desconocido")
    if mqtt is None:
        raise HTTPException(503, "Bróker MQTT no disponible")
    cid = uuid.uuid4().hex
    await pool.execute(
        "INSERT INTO commands (id, device_id, action, payload) VALUES ($1, $2, $3, $4)",
        cid, device_id, cmd.action, {"value": cmd.value})
    msg = {"id": cid, "action": cmd.action, "value": cmd.value, "ts": now().isoformat()}
    await mqtt.publish(f"{ROOT}/{device_id}/cmd", json.dumps(msg), qos=1)
    return {"id": cid, "status": "sent"}


@app.get("/api/commands")
async def commands(device_id: str | None = None, limit: int = 20):
    rows = await pool.fetch(
        """SELECT * FROM commands WHERE ($1::text IS NULL OR device_id = $1)
           ORDER BY ts DESC LIMIT $2""", device_id, min(limit, 200))
    return [dict(r) for r in rows]


# --------------------------------------------------------------- API: reglas
class Rule(BaseModel):
    device_id: str
    variable: str
    op: str
    threshold: float
    severity: str = "warning"
    message: str
    enabled: bool = True


class RulePatch(BaseModel):
    threshold: float | None = None
    enabled: bool | None = None
    op: str | None = None
    severity: str | None = None
    message: str | None = None


@app.get("/api/rules")
async def list_rules():
    return rules


@app.post("/api/rules")
async def create_rule(r: Rule, x_admin_token: str = Header("")):
    require_admin(x_admin_token)
    if r.op not in OPS:
        raise HTTPException(400, "Operador inválido")
    rid = await pool.fetchval(
        """INSERT INTO rules (device_id, variable, op, threshold, severity, message, enabled)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
        r.device_id, r.variable, r.op, r.threshold, r.severity, r.message, r.enabled)
    await load_catalog()
    return {"id": rid}


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: int, p: RulePatch, x_admin_token: str = Header("")):
    require_admin(x_admin_token)
    fields = {k: v for k, v in p.model_dump().items() if v is not None}
    if "op" in fields and fields["op"] not in OPS:
        raise HTTPException(400, "Operador inválido")
    if fields:
        sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
        await pool.execute(f"UPDATE rules SET {sets} WHERE id = $1", rule_id, *fields.values())
        await load_catalog()
    return {"ok": True}


# ---------------------------------------------------------- API: análisis IA
@app.get("/api/analysis")
async def analysis(range: str = "24h", start: str | None = None, end: str | None = None,
                   refresh: bool = False, x_admin_token: str = Header("")):
    require_admin(x_admin_token)
    key = f"{range}|{start}|{end}"
    cached = analysis_cache.get(key)
    if cached and not refresh and now() - cached[0] < timedelta(minutes=10):
        return cached[1]
    t0, t1 = resolve_range(range, start, end)
    result = await generate_analysis(pool, t0, t1)
    analysis_cache[key] = (now(), result)
    return result


# ----------------------------------------------------------------- WebSocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    sockets.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sockets.discard(ws)


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="static")
