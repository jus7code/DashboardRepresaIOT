"""Análisis del comportamiento de las gráficas.

Resume estadísticamente cada variable en el rango (promedio, mín., máx., tendencia y perfil)
y pide a Claude una descripción en lenguaje natural. Si no hay ANTHROPIC_API_KEY, o la
llamada falla, devuelve un análisis basado en reglas con los mismos datos.
"""
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger("represa.analysis")

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
LOCAL_TZ = timedelta(hours=-5)

SYSTEM = (
    "Eres ingeniero de instrumentación y seguridad de presas. Recibes estadísticas de los "
    "sensores IoT de una represa hidroeléctrica en Santander (Colombia). Escribe en español un "
    "análisis del comportamiento de las gráficas durante el periodo: tendencias, ciclos diarios, "
    "picos y su hora, correlaciones físicas entre variables (lluvia → caudal → nivel → presión "
    "de poro → desplazamiento; demanda → potencia → temperatura de rodamiento), eventos y alertas, "
    "y termina con recomendaciones operativas breves. Usa encabezados '## ' y viñetas '- '. "
    "No inventes datos que no estén en el resumen."
)


def _fmt(v: float) -> str:
    a = abs(v)
    return f"{v:.4f}" if a < 1 else f"{v:.2f}" if a < 100 else f"{v:.1f}" if a < 10000 else f"{v:.0f}"


def _local(ts: datetime) -> str:
    return (ts + LOCAL_TZ).strftime("%d/%m %H:%M")


async def collect(pool, t0: datetime, t1: datetime) -> dict:
    devices = await pool.fetch("SELECT id, name, kind, sensor, variables FROM devices ORDER BY id")
    bucket = max((t1 - t0).total_seconds() / 24, 60)
    rows = await pool.fetch(
        """SELECT device_id, variable,
                  date_bin(make_interval(secs => $3), ts, TIMESTAMPTZ '2000-01-01') AS b,
                  avg(value) AS a, min(value) AS mn, max(value) AS mx, count(*) AS n
           FROM telemetry WHERE ts BETWEEN $1 AND $2
           GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", t0, t1, bucket)
    alerts = await pool.fetch(
        """SELECT device_id, variable, severity, message, count(*) AS n, max(value) AS peak,
                  min(ts) AS first_ts, max(ts) AS last_ts
           FROM alerts WHERE ts BETWEEN $1 AND $2
           GROUP BY 1, 2, 3, 4 ORDER BY n DESC""", t0, t1)

    buckets: dict[tuple[str, str], list] = {}
    for r in rows:
        buckets.setdefault((r["device_id"], r["variable"]), []).append(r)

    out = []
    for d in devices:
        vars_out = []
        for v in d["variables"]:
            bs = buckets.get((d["id"], v["key"]))
            if not bs:
                continue
            n = sum(b["n"] for b in bs)
            peak = max(bs, key=lambda b: b["mx"])
            low = min(bs, key=lambda b: b["mn"])
            vars_out.append({
                "key": v["key"], "label": v["label"], "unit": v["unit"],
                "avg": sum(b["a"] * b["n"] for b in bs) / n, "min": low["mn"], "max": peak["mx"],
                "min_at": _local(low["b"]), "max_at": _local(peak["b"]),
                "first": bs[0]["a"], "last": bs[-1]["a"], "n": n,
                "profile": [round(b["a"], 3) for b in bs],
            })
        if vars_out:
            out.append({"id": d["id"], "name": d["name"], "kind": d["kind"], "sensor": d["sensor"], "variables": vars_out})
    return {"from": t0, "to": t1, "bucket_s": bucket, "devices": out, "alerts": [dict(a) for a in alerts]}


def to_prompt(data: dict) -> str:
    lines = [f"Periodo: {_local(data['from'])} a {_local(data['to'])} (hora Colombia). "
             f"Perfil = promedio en {len(data['devices'][0]['variables'][0]['profile']) if data['devices'] else 0} "
             f"ventanas de {data['bucket_s'] / 3600:.1f} h."]
    for d in data["devices"]:
        lines.append(f"\n### {d['id']} · {d['name']} ({d['kind']}, {d['sensor']})")
        for v in d["variables"]:
            lines.append(
                f"- {v['label']} [{v['unit']}]: prom {_fmt(v['avg'])}, mín {_fmt(v['min'])} ({v['min_at']}), "
                f"máx {_fmt(v['max'])} ({v['max_at']}), inicio {_fmt(v['first'])} → fin {_fmt(v['last'])}, "
                f"n={v['n']}; perfil: {', '.join(_fmt(p) for p in v['profile'])}")
    lines.append("\n### Alertas")
    if not data["alerts"]:
        lines.append("- Sin alertas en el periodo.")
    for a in data["alerts"]:
        lines.append(f"- {a['device_id']} {a['variable']} ({a['severity']}): {a['message']} — {a['n']} veces, "
                     f"pico {_fmt(a['peak'])}, entre {_local(a['first_ts'])} y {_local(a['last_ts'])}")
    return "\n".join(lines)


def local_summary(data: dict) -> str:
    out = ["## Resumen estadístico", "Análisis generado sin IA (configure ANTHROPIC_API_KEY para la descripción con IA)."]
    for d in data["devices"]:
        out.append(f"\n## {d['name']} ({d['id']})")
        for v in d["variables"]:
            delta = v["last"] - v["first"]
            span = (v["max"] - v["min"]) or 1
            trend = "estable" if abs(delta) < 0.05 * span else ("en ascenso" if delta > 0 else "en descenso")
            unit = f" {v['unit']}" if v["unit"] else ""
            out.append(f"- **{v['label']}**: promedio {_fmt(v['avg'])}{unit}, mínimo {_fmt(v['min'])} "
                       f"({v['min_at']}), máximo {_fmt(v['max'])} ({v['max_at']}); tendencia {trend} "
                       f"({'+' if delta >= 0 else ''}{_fmt(delta)}).")
    out.append("\n## Alertas")
    out += [f"- {a['message']} ({a['device_id']}): {a['n']} eventos, pico {_fmt(a['peak'])}." for a in data["alerts"]] \
        or ["- Sin alertas en el periodo."]
    return "\n".join(out)


async def generate_analysis(pool, t0: datetime, t1: datetime) -> dict:
    data = await collect(pool, t0, t1)
    base = {"from": t0, "to": t1, "devices": len(data["devices"]), "alerts": len(data["alerts"])}
    if not data["devices"]:
        return {**base, "source": "local", "text": "No hay datos en el rango seleccionado."}
    if not os.getenv("ANTHROPIC_API_KEY"):
        return {**base, "source": "local", "text": local_summary(data)}

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
        resp = await client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": to_prompt(data)}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("el modelo declinó la solicitud")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise RuntimeError("respuesta vacía")
        return {**base, "source": resp.model, "text": text}
    except Exception as e:
        log.warning("Análisis con IA no disponible: %s", e)
        return {**base, "source": "local", "text": local_summary(data), "error": str(e)}
