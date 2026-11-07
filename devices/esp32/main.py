# Dispositivo REAL opcional: ESP32 (MicroPython) con HC-SR04 (nivel de una maqueta) y DHT22.
# Copiar a la placa con Thonny/mpremote junto con umqtt.simple (mip install umqtt.simple).
# Conexiones: HC-SR04 TRIG->GPIO5, ECHO->GPIO18 (con divisor 5V->3.3V), DHT22 DATA->GPIO4.
import json
import time

import dht
import machine
import network
from umqtt.simple import MQTTClient

WIFI_SSID = "TU_WIFI"
WIFI_PASS = "TU_CLAVE"
MQTT_HOST = "tu-dominio.eastus.cloudapp.azure.com"
MQTT_USER = "represa"
MQTT_PASS = "CAMBIAR"
DEVICE_ID = "RL-ESP-01"
TANK_CM = 40.0          # distancia del sensor al fondo de la maqueta

TOPIC = "represa/" + DEVICE_ID + "/"
trig = machine.Pin(5, machine.Pin.OUT)
echo = machine.Pin(18, machine.Pin.IN)
sensor = dht.DHT22(machine.Pin(4))
state = {"online": True, "power": "on", "interval": 10, "offsets": {}, "gains": {}, "transport": "mqtt"}


def distance_cm():
    trig.off(); time.sleep_us(2); trig.on(); time.sleep_us(10); trig.off()
    d = machine.time_pulse_us(echo, 1, 30000)
    return d * 0.0343 / 2 if d > 0 else None


def read():
    v = {}
    d = distance_cm()
    if d is not None:
        v["nivel_maqueta_cm"] = max(TANK_CM - d, 0)
    try:
        sensor.measure()
        v["temp_c"], v["humedad_pct"] = sensor.temperature(), sensor.humidity()
    except OSError:
        pass
    return {k: x * state["gains"].get(k, 1) + state["offsets"].get(k, 0) for k, x in v.items()}


def on_cmd(topic, msg):
    cmd = json.loads(msg)
    action, value, ok, info = cmd.get("action"), cmd.get("value"), True, "ok"
    try:
        if action == "power":
            state["power"] = "on" if str(value).lower() in ("on", "true", "1") else "off"
        elif action == "interval":
            state["interval"] = max(1, min(3600, float(value)))
        elif action == "calibrate":
            state["offsets"][value["variable"]] = float(value.get("offset", 0))
            state["gains"][value["variable"]] = float(value.get("gain", 1))
        elif action == "reset":
            state.update(power="on", interval=10, offsets={}, gains={})
        else:
            raise ValueError("acción no soportada")
    except Exception as e:
        ok, info = False, str(e)
    client.publish(TOPIC + "ack", json.dumps({"cmd_id": cmd.get("id"), "action": action, "ok": ok, "msg": info}))
    client.publish(TOPIC + "status", json.dumps(state), retain=True, qos=1)


wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASS)
while not wlan.isconnected():
    time.sleep(0.5)

client = MQTTClient(DEVICE_ID, MQTT_HOST, user=MQTT_USER, password=MQTT_PASS, keepalive=30)
client.set_last_will(TOPIC + "status", json.dumps({"online": False}), retain=True, qos=1)
client.set_callback(on_cmd)
client.connect()
client.subscribe(TOPIC + "cmd", qos=1)
client.publish(TOPIC + "status", json.dumps(state), retain=True, qos=1)

last = 0
while True:
    client.check_msg()
    if state["power"] == "on" and time.ticks_diff(time.ticks_ms(), last) >= state["interval"] * 1000:
        last = time.ticks_ms()
        client.publish(TOPIC + "telemetry", json.dumps({"values": read()}), qos=1)  # ts lo pone el backend
    time.sleep_ms(100)
