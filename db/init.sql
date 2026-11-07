-- Esquema de la plataforma IoT de monitoreo de la represa (PostgreSQL 16)

CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('real', 'twin', 'api', 'dataset')),
    sensor      TEXT NOT NULL,
    protocol    TEXT NOT NULL,
    location    TEXT,
    lat         DOUBLE PRECISION,
    lon         DOUBLE PRECISION,
    variables   JSONB NOT NULL DEFAULT '[]',   -- [{key,label,unit,min,max}]
    controls    JSONB NOT NULL DEFAULT '{}',   -- controles extra: setpoint / mode
    online      BOOLEAN NOT NULL DEFAULT FALSE,
    state       JSONB NOT NULL DEFAULT '{}',   -- último estado reportado (power, interval, offsets...)
    last_values JSONB NOT NULL DEFAULT '{}',
    last_seen   TIMESTAMPTZ
);

-- Formato "largo": una fila por (instante, dispositivo, variable). Ideal para agregaciones por ventana.
CREATE TABLE IF NOT EXISTS telemetry (
    ts        TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL REFERENCES devices(id),
    variable  TEXT NOT NULL,
    value     DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS telemetry_dev_var_ts ON telemetry (device_id, variable, ts DESC);
CREATE INDEX IF NOT EXISTS telemetry_ts ON telemetry (ts DESC);

CREATE TABLE IF NOT EXISTS rules (
    id        SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id),
    variable  TEXT NOT NULL,
    op        TEXT NOT NULL CHECK (op IN ('>', '<', '>=', '<=')),
    threshold DOUBLE PRECISION NOT NULL,
    severity  TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
    message   TEXT NOT NULL,
    enabled   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS alerts (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL,
    device_id    TEXT NOT NULL REFERENCES devices(id),
    variable     TEXT NOT NULL,
    value        DOUBLE PRECISION NOT NULL,
    rule_id      INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    severity     TEXT NOT NULL,
    message      TEXT NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS alerts_ts ON alerts (ts DESC);

-- Bitácora de comandos de retroceso (downlink)
CREATE TABLE IF NOT EXISTS commands (
    id        TEXT PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    device_id TEXT NOT NULL REFERENCES devices(id),
    action    TEXT NOT NULL,
    payload   JSONB NOT NULL DEFAULT '{}',
    status    TEXT NOT NULL DEFAULT 'sent',
    response  JSONB,
    acked_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS commands_dev_ts ON commands (device_id, ts DESC);

-- ---------------------------------------------------------------------------
-- Catálogo de dispositivos (14): 2 reales, 8 gemelos digitales, 2 API, 2 dataset
-- ---------------------------------------------------------------------------
INSERT INTO devices (id, name, kind, sensor, protocol, location, lat, lon, variables, controls) VALUES
('RL-GW-01', 'Gateway de borde', 'real', 'PC / Raspberry Pi con psutil (real_device.py)', 'MQTT', 'Sala de control', 7.0170, -73.4160,
 '[{"key":"cpu_pct","label":"CPU","unit":"%","min":0,"max":100},
   {"key":"ram_pct","label":"RAM","unit":"%","min":0,"max":100},
   {"key":"disco_pct","label":"Disco","unit":"%","min":0,"max":100},
   {"key":"red_kbps","label":"Tráfico de red","unit":"kB/s","min":0,"max":5000},
   {"key":"latencia_ms","label":"Latencia al bróker","unit":"ms","min":0,"max":500}]', '{}'),
('RL-ESP-01', 'Maqueta de vertedero', 'real', 'ESP32 + HC-SR04 + DHT22 (MicroPython)', 'MQTT', 'Laboratorio', 7.0170, -73.4160,
 '[{"key":"nivel_maqueta_cm","label":"Nivel maqueta","unit":"cm","min":0,"max":40},
   {"key":"temp_c","label":"Temperatura","unit":"°C","min":0,"max":50},
   {"key":"humedad_pct","label":"Humedad","unit":"%","min":0,"max":100}]', '{}'),
('DT-NIV-01', 'Nivel del embalse', 'twin', 'Sensor de nivel radar', 'MQTT', 'Torre de captación', 7.0180, -73.4170,
 '[{"key":"nivel_msnm","label":"Nivel","unit":"msnm","min":290,"max":335},
   {"key":"volumen_hm3","label":"Volumen","unit":"hm³","min":2500,"max":4800},
   {"key":"caudal_entrada_m3s","label":"Caudal de entrada","unit":"m³/s","min":100,"max":2500}]', '{}'),
('DT-PZ-01', 'Piezómetro de cimentación', 'twin', 'Piezómetro de cuerda vibrante', 'MQTT', 'Galería de inspección', 7.0165, -73.4155,
 '[{"key":"presion_poro_kpa","label":"Presión de poro","unit":"kPa","min":200,"max":1000},
   {"key":"temp_c","label":"Temperatura","unit":"°C","min":12,"max":25}]', '{}'),
('DT-INC-01', 'Inclinómetro de cortina', 'twin', 'Inclinómetro biaxial + extensómetro', 'MQTT', 'Cresta de la presa', 7.0168, -73.4158,
 '[{"key":"inclinacion_x_mm_m","label":"Inclinación X","unit":"mm/m","min":-5,"max":5},
   {"key":"inclinacion_y_mm_m","label":"Inclinación Y","unit":"mm/m","min":-5,"max":5},
   {"key":"desplazamiento_mm","label":"Desplazamiento","unit":"mm","min":0,"max":20}]', '{}'),
('DT-COMP-01', 'Compuerta radial del vertedero', 'twin', 'Actuador hidráulico + encoder', 'MQTT', 'Vertedero', 7.0175, -73.4150,
 '[{"key":"apertura_pct","label":"Apertura","unit":"%","min":0,"max":100},
   {"key":"setpoint_pct","label":"Apertura objetivo","unit":"%","min":0,"max":100},
   {"key":"corriente_motor_a","label":"Corriente motor","unit":"A","min":0,"max":60},
   {"key":"caudal_vertido_m3s","label":"Caudal vertido","unit":"m³/s","min":0,"max":4200}]',
 '{"setpoint":{"label":"Apertura objetivo","unit":"%","min":0,"max":100,"step":1},"mode":["auto","manual"]}'),
('DT-TURB-01', 'Unidad de generación 1', 'twin', 'Turbina Francis + generador', 'MQTT', 'Casa de máquinas', 7.0150, -73.4140,
 '[{"key":"potencia_mw","label":"Potencia","unit":"MW","min":0,"max":280},
   {"key":"caudal_planta_m3s","label":"Caudal turbinado (planta)","unit":"m³/s","min":0,"max":700},
   {"key":"rpm","label":"Velocidad","unit":"rpm","min":0,"max":200},
   {"key":"temp_rodamiento_c","label":"Temp. rodamiento","unit":"°C","min":30,"max":90}]',
 '{"setpoint":{"label":"Potencia objetivo","unit":"MW","min":0,"max":280,"step":5},"mode":["auto","manual"]}'),
('DT-SIS-01', 'Acelerógrafo de la presa', 'twin', 'Acelerógrafo triaxial MEMS', 'MQTT', 'Galería de inspección', 7.0166, -73.4156,
 '[{"key":"pga_g","label":"Aceleración pico (PGA)","unit":"g","min":0,"max":0.3},
   {"key":"frecuencia_hz","label":"Frecuencia dominante","unit":"Hz","min":0.5,"max":20},
   {"key":"vibracion_mm_s","label":"Velocidad de vibración","unit":"mm/s","min":0,"max":10}]', '{}'),
('DT-CAL-01', 'Calidad del agua', 'twin', 'Sonda multiparamétrica', 'MQTT', 'Captación', 7.0182, -73.4172,
 '[{"key":"ph","label":"pH","unit":"pH","min":6,"max":9},
   {"key":"turbidez_ntu","label":"Turbidez","unit":"NTU","min":0,"max":300},
   {"key":"oxigeno_mg_l","label":"Oxígeno disuelto","unit":"mg/L","min":2,"max":10},
   {"key":"temp_agua_c","label":"Temperatura del agua","unit":"°C","min":18,"max":30}]', '{}'),
('DT-FIL-01', 'Aforador de filtraciones', 'twin', 'Vertedero triangular con sensor ultrasónico', 'MQTT', 'Pie de presa', 7.0160, -73.4150,
 '[{"key":"filtracion_l_s","label":"Caudal de filtración","unit":"L/s","min":0,"max":100},
   {"key":"turbiedad_filtracion_ntu","label":"Turbiedad filtración","unit":"NTU","min":0,"max":50}]', '{}'),
('API-WX-01', 'Clima actual (Azure Maps)', 'api', 'Azure Maps Weather · Current Conditions', 'HTTPS REST', 'Coordenadas de la represa', 7.0170, -73.4160,
 '[{"key":"temp_c","label":"Temperatura","unit":"°C","min":10,"max":40},
   {"key":"sensacion_c","label":"Sensación térmica","unit":"°C","min":10,"max":45},
   {"key":"humedad_pct","label":"Humedad relativa","unit":"%","min":0,"max":100},
   {"key":"presion_mb","label":"Presión","unit":"mb","min":990,"max":1030},
   {"key":"viento_kmh","label":"Viento","unit":"km/h","min":0,"max":80},
   {"key":"precip_1h_mm","label":"Precipitación 1 h","unit":"mm","min":0,"max":60},
   {"key":"uv_index","label":"Índice UV","unit":"","min":0,"max":14},
   {"key":"nubosidad_pct","label":"Nubosidad","unit":"%","min":0,"max":100}]', '{}'),
('API-AQ-01', 'Calidad del aire (Azure Maps)', 'api', 'Azure Maps Weather · Air Quality', 'HTTPS REST', 'Coordenadas de la represa', 7.0170, -73.4160,
 '[{"key":"ica","label":"Índice de calidad del aire","unit":"","min":0,"max":300},
   {"key":"pm2_5","label":"PM2.5","unit":"µg/m³","min":0,"max":150},
   {"key":"pm10","label":"PM10","unit":"µg/m³","min":0,"max":200},
   {"key":"o3","label":"Ozono","unit":"µg/m³","min":0,"max":200},
   {"key":"no2","label":"NO₂","unit":"µg/m³","min":0,"max":200},
   {"key":"co","label":"CO","unit":"µg/m³","min":0,"max":2000}]', '{}'),
('DS-RIO-01', 'Estación hidrométrica aguas arriba', 'dataset', 'Dataset CSV · limnígrafo río Sogamoso', 'HTTPS REST', 'Río Sogamoso (afluente)', 7.0500, -73.3800,
 '[{"key":"caudal_rio_m3s","label":"Caudal del río","unit":"m³/s","min":100,"max":2000},
   {"key":"nivel_rio_m","label":"Nivel del río","unit":"m","min":0,"max":10}]',
 '{"setpoint":{"label":"Fila de reproducción","unit":"fila","min":0,"max":863,"step":1}}'),
('DS-PLU-01', 'Pluviómetro de la cuenca', 'dataset', 'Dataset CSV · pluviómetro de cubeta', 'HTTPS REST', 'Cuenca alta', 7.0600, -73.3700,
 '[{"key":"precip_mm","label":"Precipitación (10 min)","unit":"mm","min":0,"max":15},
   {"key":"precip_acum_24h_mm","label":"Acumulado 24 h","unit":"mm","min":0,"max":120}]',
 '{"setpoint":{"label":"Fila de reproducción","unit":"fila","min":0,"max":863,"step":1}}')
ON CONFLICT (id) DO NOTHING;

-- Reglas de alerta por umbral
INSERT INTO rules (device_id, variable, op, threshold, severity, message) VALUES
('DT-NIV-01',  'nivel_msnm',          '>',  326,   'warning',  'Nivel alto: se habilita apertura automática de compuertas'),
('DT-NIV-01',  'nivel_msnm',          '>',  329,   'critical', 'Nivel cercano al NAMO'),
('DT-NIV-01',  'nivel_msnm',          '<',  300,   'warning',  'Nivel bajo de operación'),
('DT-NIV-01',  'caudal_entrada_m3s',  '>',  1100,  'warning',  'Creciente: caudal de entrada elevado'),
('DT-PZ-01',   'presion_poro_kpa',    '>',  680,   'warning',  'Presión de poro sobre el umbral de diseño'),
('DT-INC-01',  'desplazamiento_mm',   '>',  8,     'warning',  'Desplazamiento de cortina anómalo'),
('DT-SIS-01',  'pga_g',               '>',  0.03,  'warning',  'Evento sísmico registrado'),
('DT-SIS-01',  'pga_g',               '>',  0.08,  'critical', 'Sismo fuerte: inspección obligatoria'),
('DT-TURB-01', 'temp_rodamiento_c',   '>',  70,    'warning',  'Temperatura de rodamiento elevada'),
('DT-CAL-01',  'turbidez_ntu',        '>',  60,    'warning',  'Turbidez alta por escorrentía'),
('DT-CAL-01',  'ph',                  '<',  6.5,   'warning',  'pH ácido fuera de norma'),
('DT-FIL-01',  'filtracion_l_s',      '>',  45,    'warning',  'Incremento de filtraciones'),
('API-WX-01',  'viento_kmh',          '>',  40,    'warning',  'Vientos fuertes en el embalse'),
('DS-PLU-01',  'precip_mm',           '>',  5,     'warning',  'Lluvia intensa en la cuenca'),
('DS-RIO-01',  'caudal_rio_m3s',      '>',  900,   'warning',  'Creciente del río aguas arriba'),
('RL-GW-01',   'cpu_pct',             '>',  90,    'warning',  'Gateway saturado'),
('RL-GW-01',   'latencia_ms',         '>',  300,   'warning',  'Latencia alta hacia el bróker');
