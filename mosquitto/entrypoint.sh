#!/bin/sh
# Genera el archivo de contraseñas desde las variables de entorno y arranca el bróker.
set -e
mosquitto_passwd -c -b /mosquitto/data/passwd "$MQTT_USER" "$MQTT_PASS"
chown mosquitto:mosquitto /mosquitto/data/passwd
chmod 0700 /mosquitto/data/passwd
exec mosquitto -c /mosquitto/config/mosquitto.conf
