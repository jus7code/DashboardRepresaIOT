'use strict';

// ---------------------------------------------------------------- utilidades
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const TZ = 'America/Bogota';
const tFmt = new Intl.DateTimeFormat('es-CO', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
const dFmt = new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', timeZone: TZ });
const dtFmt = new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ });
const autoDec = (v) => { const a = Math.abs(v); return a < 1 ? 3 : a < 100 ? 2 : a < 1000 ? 1 : 0; };
const fmt = (v, d) => (v == null || Number.isNaN(Number(v)) ? '—'
  : Number(v).toLocaleString('es-CO', { maximumFractionDigits: d ?? autoDec(Number(v)) }));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* sin almacenamiento */ } },
};

const KIND = { real: 'Real', twin: 'Gemelo digital', api: 'API', dataset: 'Dataset' };
const RANGE_LABEL = { '1h': 'última hora', '6h': 'últimas 6 h', '24h': 'últimas 24 h', '3d': 'últimos 3 días', '5d': 'últimos 5 días' };
const ACTION_LABEL = { power: 'Encendido', interval: 'Intervalo', calibrate: 'Calibración', reset: 'Reinicio', setpoint: 'Consigna', mode: 'Modo' };
const KPIS = [
  { dev: 'DT-NIV-01', v: 'nivel_msnm', label: 'Nivel del embalse', dec: 2 },
  { dev: 'DT-NIV-01', v: 'caudal_entrada_m3s', label: 'Caudal de entrada', dec: 0 },
  { dev: 'DT-TURB-01', v: 'potencia_mw', label: 'Potencia unidad 1', dec: 1 },
  { dev: 'DT-COMP-01', v: 'caudal_vertido_m3s', label: 'Caudal vertido', dec: 0 },
];
const ICON_PATHS = {
  'DT-NIV-01': 'M3 17c2.5-1.6 5 1.6 7.5 0s5 1.6 7.5 0 2.5-1.6 3 0M3 12c2.5-1.6 5 1.6 7.5 0s5 1.6 7.5 0 2.5-1.6 3 0M12 3v5M9 5h6',
  'DT-PZ-01': 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 12l4-4M12 7v1M7 12h1M16 12h1',
  'DT-INC-01': 'M4 20h16M8 20l8-16M8 20a6 6 0 0 1 4-5',
  'DT-COMP-01': 'M3 20h18M5 20V9a7 7 0 0 1 14 0v11M5 13h14',
  'DT-TURB-01': 'M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 10c0-4 2-6 5-6M14 12c4 0 6 2 6 5M12 14c0 4-2 6-5 6M10 12c-4 0-6-2-6-5',
  'DT-SIS-01': 'M2 12h4l2-6 4 12 3-9 2 3h5',
  'DT-CAL-01': 'M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11zM9.5 14.5a2.5 2.5 0 0 0 2.5 2.5',
  'DT-FIL-01': 'M5 4h14l-7 9zM12 13v7M8 20h8',
  'API-WX-01': 'M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 18z',
  'API-AQ-01': 'M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h8',
  'DS-RIO-01': 'M3 7c3-2 6 2 9 0s6 2 9 0M3 12c3-2 6 2 9 0s6 2 9 0M3 17c3-2 6 2 9 0s6 2 9 0',
  'DS-PLU-01': 'M7 14h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 14zM8 18l-1 3M12 18l-1 3M16 18l-1 3',
  'RL-GW-01': 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
  'RL-ESP-01': 'M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19h.01',
};
const icon = (id) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_PATHS[id] || 'M4 4h16v16H4z'}"/></svg>`;

const S = {
  range: '24h', start: null, end: null, kind: 'all',
  devices: [], byId: {}, stats: {}, rules: [], alerts: [], openAlerts: 0,
  chart: { dev: 'DT-NIV-01', v: 'nivel_msnm' },
  modal: { dev: null, v: null },
  charts: {},
};

const rangeParams = () => (S.start ? { start: S.start, end: S.end } : { range: S.range });
const statOf = (dev, v) => S.stats[`${dev}|${v}`];
const varMeta = (dev, key) => (S.byId[dev]?.variables || []).find((v) => v.key === key) || { key, label: key, unit: '' };

function cssVars() {
  const cs = getComputedStyle(document.documentElement);
  const g = (n) => cs.getPropertyValue(n).trim();
  return { series: g('--series'), band: g('--series-band'), grid: g('--grid'), ink: g('--ink'), ink2: g('--ink-2'),
    ink3: g('--ink-3'), border: g('--line'), surface: g('--tooltip') };
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

function adminToken() {
  let t = store.get('adminToken');
  if (!t) {
    t = prompt('Token de operador (ADMIN_TOKEN) para enviar comandos:');
    if (t) store.set('adminToken', t.trim());
  }
  return t && t.trim();
}

async function api(path, { method = 'GET', body, admin = false, params } = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params || {})) if (v != null) url.searchParams.set(k, v);
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (admin) {
    const t = adminToken();
    if (!t) throw new Error('Se requiere el token de operador');
    headers['X-Admin-Token'] = t;
  }
  const r = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (r.status === 401 && admin) { store.del('adminToken'); throw new Error('Token de operador inválido'); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function deviceStatus(d) {
  if (!d.online) return { cls: 'off', text: 'Sin conexión' };
  if (d.state?.power === 'off') return { cls: 'paused', text: 'Apagado' };
  return { cls: 'on', text: 'En línea' };
}

// ------------------------------------------------------------------ gráficos
const crosshair = {
  id: 'crosshair',
  afterDatasetsDraw(chart) {
    const active = chart.tooltip?.getActiveElements?.();
    if (!active?.length) return;
    const { ctx, chartArea: { top, bottom } } = chart;
    ctx.save();
    ctx.strokeStyle = cssVars().ink3;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(active[0].element.x, top);
    ctx.lineTo(active[0].element.x, bottom);
    ctx.stroke();
    ctx.restore();
  },
};
const emptyState = {
  id: 'emptyState',
  afterDraw(chart) {
    if (chart.data.datasets.some((d) => d.data.length)) return;
    const { ctx, chartArea: a } = chart;
    ctx.save();
    ctx.fillStyle = cssVars().ink3;
    ctx.font = '14px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Sin datos en el rango seleccionado', (a.left + a.right) / 2, (a.top + a.bottom) / 2);
    ctx.restore();
  },
};

async function drawSeries(key, canvas, devId, v) {
  const res = await api('/api/series', { params: { device_id: devId, variable: v, points: 300, ...rangeParams() } });
  const meta = varMeta(devId, v);
  const c = cssVars();
  const pts = res.points.map((p) => ({ x: Date.parse(p.t), avg: p.avg, min: p.min, max: p.max }));
  const t0 = Date.parse(res.from);
  const t1 = Date.parse(res.to);
  const long = t1 - t0 > 36 * 3600e3;
  S.charts[key]?.destroy();
  S.charts[key] = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [
        { label: 'Mínimo', data: pts.map((p) => ({ x: p.x, y: p.min })), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, fill: false },
        { label: 'Máximo', data: pts.map((p) => ({ x: p.x, y: p.max })), borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, fill: '-1', backgroundColor: c.band },
        { label: 'Promedio', data: pts.map((p) => ({ x: p.x, y: p.avg })), borderColor: c.series, backgroundColor: c.series,
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: c.surface, tension: 0.25, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, normalized: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: c.surface, titleColor: c.ink, bodyColor: c.ink2, borderColor: c.border, borderWidth: 1,
          padding: 10, displayColors: false, itemSort: (a, b) => b.datasetIndex - a.datasetIndex,
          callbacks: {
            title: (items) => dtFmt.format(items[0].parsed.x),
            label: (it) => `${it.dataset.label}: ${fmt(it.parsed.y)} ${meta.unit}`,
          },
        },
      },
      scales: {
        x: { type: 'linear', min: t0, max: t1, grid: { display: false }, border: { color: c.border },
          ticks: { color: c.ink2, maxTicksLimit: 7, maxRotation: 0, callback: (val) => (long ? dFmt : tFmt).format(val) } },
        y: { grid: { color: c.grid }, border: { display: false },
          ticks: { color: c.ink2, maxTicksLimit: 6, callback: (val) => fmt(val) } },
      },
    },
    plugins: [crosshair, emptyState],
  });
  return res;
}

function appendLive(key, ts, value) {
  const chart = S.charts[key];
  if (!chart || S.start) return;
  const x = Date.parse(ts);
  chart.data.datasets.forEach((d) => d.data.push({ x, y: value }));
  const span = chart.options.scales.x.max - chart.options.scales.x.min;
  chart.options.scales.x.max = Math.max(chart.options.scales.x.max, x);
  chart.options.scales.x.min = chart.options.scales.x.max - span;
  chart.update('none');
}

function statTiles(dev, v) {
  const s = statOf(dev, v);
  const unit = varMeta(dev, v).unit;
  const last = S.byId[dev]?.last_values?.[v];
  const tile = (label, val) => `<div class="stat"><span>${label}</span><strong>${fmt(val)} <small>${esc(unit)}</small></strong></div>`;
  return tile('Promedio', s?.avg) + tile('Máximo', s?.max) + tile('Mínimo', s?.min) + tile('Último', last);
}

// ------------------------------------------------------------------- render
function renderSubtitle() {
  const online = S.devices.filter((d) => d.online).length;
  const label = S.start ? `${dtFmt.format(new Date(S.start))} – ${dtFmt.format(new Date(S.end))}` : RANGE_LABEL[S.range];
  $('#subtitle').textContent = `${S.devices.length} dispositivos · ${online} en línea · Rango: ${label}`;
}

function renderKpis() {
  const tiles = KPIS.map((k) => {
    const s = statOf(k.dev, k.v);
    const last = S.byId[k.dev]?.last_values?.[k.v];
    const unit = varMeta(k.dev, k.v).unit;
    return `<div class="kpi"><div class="label">${esc(k.label)}</div>
      <div class="value num">${fmt(last, k.dec)}<small>${esc(unit)}</small></div>
      <div class="range-line num">prom ${fmt(s?.avg, k.dec)} · mín ${fmt(s?.min, k.dec)} · máx ${fmt(s?.max, k.dec)}</div></div>`;
  });
  tiles.push(`<div class="kpi"><div class="label">Alertas sin reconocer</div>
    <div class="value num">${S.openAlerts}<small>en el rango</small></div>
    <div class="range-line">${S.alerts.filter((a) => a.severity === 'critical').length} críticas recientes</div></div>`);
  $('#kpis').innerHTML = tiles.join('');
}

function renderChartControls() {
  const sel = $('#chartDevice');
  sel.innerHTML = S.devices.map((d) => `<option value="${d.id}" ${d.id === S.chart.dev ? 'selected' : ''}>${esc(d.name)} (${d.id})</option>`).join('');
  const d = S.byId[S.chart.dev];
  if (!d.variables.some((v) => v.key === S.chart.v)) S.chart.v = d.variables[0].key;
  $('#chartVars').innerHTML = d.variables.map((v) =>
    `<button class="chip ${v.key === S.chart.v ? 'active' : ''}" data-var="${v.key}">${esc(v.label)}</button>`).join('');
  const meta = varMeta(S.chart.dev, S.chart.v);
  $('#chartTitle').textContent = `${meta.label}${meta.unit ? ` (${meta.unit})` : ''}`;
  $('#chartSub').textContent = `${d.name} · línea: promedio · banda: mínimo–máximo por ventana`;
}

async function loadMainChart() {
  renderChartControls();
  await drawSeries('main', $('#mainChart'), S.chart.dev, S.chart.v);
  $('#chartStats').innerHTML = statTiles(S.chart.dev, S.chart.v);
}

function deviceCard(d) {
  const st = deviceStatus(d);
  const rows = d.variables.slice(0, 3).map((v) =>
    `<div class="row"><span>${esc(v.label)}</span><strong class="num">${fmt(d.last_values?.[v.key])} ${esc(v.unit)} <span class="chev">›</span></strong></div>`).join('');
  return `<button class="device" data-id="${d.id}">
    <div class="dev-top"><div class="thumb">${icon(d.id)}</div>
      <div><strong>${esc(d.name)}</strong><span>${d.id} · ${esc(d.protocol)}</span></div></div>
    <div class="rows">${rows}</div>
    <div class="dev-foot"><span>${KIND[d.kind]}</span><span class="state ${st.cls}">${st.text}</span></div>
  </button>`;
}

function renderDevices() {
  const list = S.devices.filter((d) => S.kind === 'all' || d.kind === S.kind);
  $('#devices').innerHTML = list.map(deviceCard).join('') || '<p class="empty">Sin dispositivos.</p>';
}

function alertItem(a) {
  const d = S.byId[a.device_id];
  const unit = varMeta(a.device_id, a.variable).unit;
  const sev = a.severity === 'critical' ? '◆ Crítica' : '▲ Advertencia';
  return `<li><span class="sev ${a.severity}">${sev}</span><span class="msg">${esc(a.message)}</span>
    <span class="meta">${esc(d?.name || a.device_id)} · ${fmt(a.value)} ${esc(unit)} · ${dtFmt.format(new Date(a.ts))}</span></li>`;
}

function renderAlerts() {
  $('#alerts').innerHTML = S.alerts.map(alertItem).join('') || '<li class="empty">Sin alertas en el rango.</li>';
  const badge = $('#alertCount');
  badge.textContent = S.openAlerts;
  badge.classList.toggle('hot', S.openAlerts > 0);
}

function renderRules() {
  $('#rules').innerHTML = S.rules.map((r) => {
    const meta = varMeta(r.device_id, r.variable);
    return `<li class="${r.enabled ? '' : 'off'}">
      <span>${esc(S.byId[r.device_id]?.name || r.device_id)} · ${esc(meta.label)}</span>
      <span class="r-thr" data-rule="${r.id}" title="Editar umbral">${esc(r.op)} ${fmt(r.threshold)} ${esc(meta.unit)}</span>
      <span class="r-var">${esc(r.message)}</span>
      <label class="small"><input type="checkbox" data-toggle="${r.id}" ${r.enabled ? 'checked' : ''}> ${r.severity === 'critical' ? 'crítica' : 'advertencia'}</label>
    </li>`;
  }).join('');
}

async function loadAll() {
  const p = rangeParams();
  const [devices, stats, alerts, rules] = await Promise.all([
    api('/api/devices'), api('/api/stats', { params: p }), api('/api/alerts', { params: { ...p, limit: 60 } }), api('/api/rules'),
  ]);
  S.devices = devices;
  S.byId = Object.fromEntries(devices.map((d) => [d.id, d]));
  S.stats = Object.fromEntries(stats.stats.map((s) => [`${s.device_id}|${s.variable}`, s]));
  S.alerts = alerts.alerts;
  S.openAlerts = alerts.open;
  S.rules = rules;
  renderSubtitle();
  renderKpis();
  renderDevices();
  renderAlerts();
  renderRules();
  await loadMainChart();
  if (S.modal.dev) { renderModalSummary(); loadModalChart(); }
}

// --------------------------------------------------------------------- modal
function openModal(id) {
  const d = S.byId[id];
  S.modal = { dev: id, v: d.variables[0].key };
  $('#mAvatar').innerHTML = icon(id);
  $('#mThumb').innerHTML = icon(id);
  $('#mName').textContent = d.name;
  $('#mMeta').textContent = `${d.id} · ${KIND[d.kind]}`;
  $('#mTitle').textContent = d.name;
  renderControlForm();
  renderModalSummary();
  $('#modal').hidden = false;
  document.body.style.overflow = 'hidden';
  $('.close').focus();
  loadModalChart();
  loadAcks();
}

function closeModal() {
  $('#modal').hidden = true;
  document.body.style.overflow = '';
  S.charts.modal?.destroy();
  delete S.charts.modal;
  S.modal.dev = null;
  queueRender();
}

function renderModalSummary() {
  const d = S.byId[S.modal.dev];
  const st = deviceStatus(d);
  const row = (label, value) => `<div class="row"><span>${label}</span><strong>${value} <span class="chev">›</span></strong></div>`;
  $('#mLast').textContent = d.last_seen ? `Último dato: ${dtFmt.format(new Date(d.last_seen))}` : 'Sin datos todavía';
  $('#mRows').innerHTML = row('Tipo', KIND[d.kind]) + row('Sensor', esc(d.sensor)) + row('Protocolo', esc(d.protocol))
    + row('Muestreo', d.state?.interval ? `cada ${fmt(d.state.interval, 0)} s` : '—')
    + (d.state?.mode ? row('Modo', esc(d.state.mode)) : '');
  $('#mVars').innerHTML = d.variables.map((v) =>
    `<button class="chip ${v.key === S.modal.v ? 'active' : ''}" data-mvar="${v.key}">${esc(v.label)}</button>`).join('');
  $('#mStats').innerHTML = statTiles(d.id, S.modal.v);
  $('#mState').textContent = st.text;
}

async function loadModalChart() {
  if (!S.modal.dev) return;
  await drawSeries('modal', $('#mChart'), S.modal.dev, S.modal.v);
}

function renderControlForm() {
  const d = S.byId[S.modal.dev];
  const st = d.state || {};
  const on = st.power !== 'off';
  const ctl = d.controls || {};
  const sp = ctl.setpoint;
  const spValue = d.kind === 'dataset' ? (st.row ?? 0) : (st.setpoint ?? sp?.min ?? 0);
  const first = d.variables[0].key;
  $('#controlForm').innerHTML = `
    <label class="switch"><span>Sensor encendido</span><input type="checkbox" name="power" ${on ? 'checked' : ''}></label>
    <label class="field"><span>Intervalo de muestreo (s)</span>
      <input type="number" name="interval" min="1" max="3600" step="1" value="${st.interval ?? ''}"></label>
    <div class="field"><span>Calibración · valor × ganancia + offset</span>
      <div class="inline">
        <label class="mini"><small>Variable</small>
          <select name="calVar">${d.variables.map((v) => `<option value="${v.key}">${esc(v.label)}</option>`).join('')}</select></label>
        <label class="mini"><small>Ganancia</small><input type="number" name="gain" step="any" value="${st.gains?.[first] ?? 1}"></label>
        <label class="mini"><small>Offset</small><input type="number" name="offset" step="any" value="${st.offsets?.[first] ?? 0}"></label>
      </div></div>
    ${ctl.mode ? `<label class="field"><span>Modo de operación</span><select name="mode">
      ${ctl.mode.map((m) => `<option value="${m}" ${st.mode === m ? 'selected' : ''}>${m === 'auto' ? 'Automático' : 'Manual'}</option>`).join('')}
      </select></label>` : ''}
    ${sp ? `<label class="field"><span>${esc(sp.label)}: <b id="spOut">${fmt(spValue)}</b> ${esc(sp.unit)}</span>
      <input type="range" name="setpoint" min="${sp.min}" max="${sp.max}" step="${sp.step}" value="${spValue}"></label>` : ''}
    <button class="btn-primary" type="submit">Aplicar cambios</button>
    <button class="btn-link" type="button" id="resetBtn">Restablecer valores de fábrica</button>`;
}

function pendingCommands(form) {
  const d = S.byId[S.modal.dev];
  const st = d.state || {};
  const f = new FormData(form);
  const cmds = [];
  const power = form.power.checked ? 'on' : 'off';
  if (power !== (st.power || 'on')) cmds.push({ action: 'power', value: power });
  const interval = Number(f.get('interval'));
  if (interval && interval !== Number(st.interval)) cmds.push({ action: 'interval', value: interval });
  const calVar = f.get('calVar');
  const gain = Number(f.get('gain'));
  const offset = Number(f.get('offset'));
  if (gain !== (st.gains?.[calVar] ?? 1) || offset !== (st.offsets?.[calVar] ?? 0)) {
    cmds.push({ action: 'calibrate', value: { variable: calVar, gain, offset } });
  }
  const sp = f.get('setpoint');
  const spBefore = d.kind === 'dataset' ? st.row : st.setpoint;
  const spChanged = sp !== null && Number(sp) !== Number(spBefore);
  const mode = f.get('mode');
  const modeChanged = mode && mode !== st.mode;
  // Una consigna nueva pasa el equipo a manual; volver a automático descarta la consigna.
  if (modeChanged && mode === 'auto') cmds.push({ action: 'mode', value: 'auto' });
  else if (spChanged) cmds.push({ action: 'setpoint', value: Number(sp) });
  else if (modeChanged) cmds.push({ action: 'mode', value: mode });
  return cmds;
}

async function sendCommands(cmds) {
  const btn = $('#controlForm .btn-primary');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    for (const c of cmds) await api(`/api/devices/${S.modal.dev}/command`, { method: 'POST', admin: true, body: c });
    toast(`${cmds.length} comando(s) enviados a ${S.modal.dev}`);
    loadAcks();
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Aplicar cambios';
  }
}

async function loadAcks() {
  if (!S.modal.dev) return;
  const cmds = await api('/api/commands', { params: { device_id: S.modal.dev, limit: 8 } });
  $('#mAcks').innerHTML = cmds.map((c) => {
    const v = c.payload?.value;
    const val = v == null ? '' : typeof v === 'object' ? Object.values(v).join(' / ') : v;
    const label = { ok: '✓ aplicado', error: '✕ error', sent: '… enviado' }[c.status] || c.status;
    return `<li><span>${ACTION_LABEL[c.action] || c.action} ${esc(val)} · ${tFmt.format(new Date(c.ts))}</span>
      <span class="${c.status}" title="${esc(c.response?.msg || '')}">${label}</span></li>`;
  }).join('') || '<li class="empty">Sin comandos enviados.</li>';
}

// ---------------------------------------------------------------- IA
function md(text) {
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  let html = '';
  let list = false;
  for (const raw of esc(text).split('\n')) {
    const t = raw.trim();
    if (/^[-*] /.test(t)) {
      if (!list) { html += '<ul>'; list = true; }
      html += `<li>${inline(t.slice(2))}</li>`;
      continue;
    }
    if (list) { html += '</ul>'; list = false; }
    if (t.startsWith('#')) html += `<h3>${inline(t.replace(/^#+\s*/, ''))}</h3>`;
    else if (t) html += `<p>${inline(t)}</p>`;
  }
  return html + (list ? '</ul>' : '');
}

async function runAnalysis() {
  const btn = $('#aiBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Analizando…';
  try {
    const r = await api('/api/analysis', { admin: true, params: rangeParams() });
    $('#aiOut').innerHTML = md(r.text) + `<p class="src">Fuente: ${r.source === 'local' ? 'resumen estadístico local' : esc(r.source)}</p>`;
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generar análisis';
  }
}

// --------------------------------------------------------------- tiempo real
let renderQueued = false;
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  setTimeout(() => {
    renderQueued = false;
    if (S.modal.dev) {   // el tablero queda oculto tras el modal: sólo se actualiza el resumen
      renderModalSummary();
      return;
    }
    renderKpis();
    renderDevices();
    renderSubtitle();
  }, 800);
}

function onEvent(e) {
  const d = S.byId[e.device_id];
  if (!d) return;
  if (e.type === 'telemetry') {
    Object.assign(d.last_values, e.values);
    d.last_seen = e.ts;
    d.online = true;
    if (e.device_id === S.chart.dev && S.chart.v in e.values) appendLive('main', e.ts, e.values[S.chart.v]);
    if (e.device_id === S.modal.dev && S.modal.v in e.values) appendLive('modal', e.ts, e.values[S.modal.v]);
    queueRender();
  } else if (e.type === 'status') {
    d.online = e.online;
    d.state = { ...d.state, ...e.state };
    queueRender();
  } else if (e.type === 'alert') {
    S.alerts.unshift(e);
    S.alerts = S.alerts.slice(0, 60);
    S.openAlerts += 1;
    renderAlerts();
    queueRender();
  } else if (e.type === 'ack') {
    toast(`${d.name}: ${e.msg}`);
    if (e.device_id === S.modal.dev) loadAcks();
  }
}

function connectWS() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  const live = $('#live');
  let ping;
  ws.onopen = () => {
    live.classList.add('on');
    $('#liveText').textContent = 'En vivo';
    live.title = 'En vivo';
    ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000);
  };
  ws.onclose = () => {
    live.classList.remove('on');
    $('#liveText').textContent = 'Reconectando…';
    live.title = 'Reconectando…';
    clearInterval(ping);
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
}

// ------------------------------------------------------------------- eventos
function bind() {
  $('#range').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    document.querySelectorAll('#range button').forEach((x) => x.classList.toggle('active', x === b));
    if (b.dataset.range === 'custom') {
      $('#customRange').hidden = false;
      return;
    }
    $('#customRange').hidden = true;
    S.range = b.dataset.range;
    S.start = S.end = null;
    store.set('range', S.range);
    loadAll().catch((err) => toast(err.message));
  });
  $('#applyRange').addEventListener('click', () => {
    const from = $('#fromInput').value;
    const to = $('#toInput').value;
    if (!from) return toast('Seleccione la fecha inicial');
    S.start = new Date(from).toISOString();
    S.end = to ? new Date(to).toISOString() : new Date().toISOString();
    loadAll().catch((err) => toast(err.message));
  });
  $('#chartDevice').addEventListener('change', (e) => {
    S.chart = { dev: e.target.value, v: S.byId[e.target.value].variables[0].key };
    loadMainChart().catch((err) => toast(err.message));
  });
  $('#chartVars').addEventListener('click', (e) => {
    const b = e.target.closest('[data-var]');
    if (!b) return;
    S.chart.v = b.dataset.var;
    loadMainChart().catch((err) => toast(err.message));
  });
  $('#kindFilter').addEventListener('click', (e) => {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    S.kind = b.dataset.kind;
    document.querySelectorAll('#kindFilter .chip').forEach((x) => x.classList.toggle('active', x === b));
    renderDevices();
  });
  $('#devices').addEventListener('click', (e) => {
    const card = e.target.closest('.device');
    if (card) openModal(card.dataset.id);
  });
  $('#modal').addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) closeModal();
    const chip = e.target.closest('[data-mvar]');
    if (chip) {
      S.modal.v = chip.dataset.mvar;
      renderModalSummary();
      loadModalChart();
    }
    if (e.target.id === 'resetBtn') sendCommands([{ action: 'reset' }]);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.modal.dev) closeModal(); });
  $('#controlForm').addEventListener('input', (e) => {
    if (e.target.name === 'setpoint') $('#spOut').textContent = fmt(e.target.value);
    if (e.target.name === 'calVar') {
      const st = S.byId[S.modal.dev].state || {};
      e.target.form.gain.value = st.gains?.[e.target.value] ?? 1;
      e.target.form.offset.value = st.offsets?.[e.target.value] ?? 0;
    }
  });
  $('#controlForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const cmds = pendingCommands(e.target);
    if (!cmds.length) return toast('No hay cambios por aplicar');
    sendCommands(cmds);
  });
  $('#aiBtn').addEventListener('click', runAnalysis);
  $('#rules').addEventListener('click', async (e) => {
    const thr = e.target.closest('[data-rule]');
    if (!thr) return;
    const rule = S.rules.find((r) => r.id === Number(thr.dataset.rule));
    const v = prompt(`Nuevo umbral para "${rule.message}" (${rule.op})`, rule.threshold);
    if (v === null || v.trim() === '' || Number.isNaN(Number(v))) return;
    try {
      await api(`/api/rules/${rule.id}`, { method: 'PUT', admin: true, body: { threshold: Number(v) } });
      rule.threshold = Number(v);
      renderRules();
      toast('Umbral actualizado');
    } catch (err) { toast(err.message); }
  });
  $('#rules').addEventListener('change', async (e) => {
    const id = Number(e.target.dataset.toggle);
    if (!id) return;
    try {
      await api(`/api/rules/${id}`, { method: 'PUT', admin: true, body: { enabled: e.target.checked } });
      S.rules.find((r) => r.id === id).enabled = e.target.checked;
      renderRules();
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast(err.message);
    }
  });
  $('#themeBtn').addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    store.set('theme', next);
    applyTheme();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!document.documentElement.dataset.theme) applyTheme();
  });
}

// ------------------------------------------------------------------- tema
const isDark = () => {
  const t = document.documentElement.dataset.theme;
  return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
};

function syncThemeButton() {
  const dark = isDark();
  $('#themeBtn .i-sun').toggleAttribute('hidden', !dark);
  $('#themeBtn .i-moon').toggleAttribute('hidden', dark);
  $('#themeBtn').setAttribute('aria-label', dark ? 'Activar modo claro' : 'Activar modo oscuro');
  $('meta[name="theme-color"]').content = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
}

function applyTheme() {
  syncThemeButton();
  if (S.devices.length) loadMainChart().catch(() => {});
  loadModalChart().catch(() => {});
}

function init() {
  syncThemeButton();
  const saved = store.get('range');
  if (saved && RANGE_LABEL[saved]) {
    S.range = saved;
    document.querySelectorAll('#range button').forEach((b) => b.classList.toggle('active', b.dataset.range === saved));
  }
  bind();
  loadAll().catch((e) => {
    $('#subtitle').textContent = `No se pudo cargar la API: ${e.message}`;
  });
  connectWS();
  setInterval(() => { if (!S.start) loadAll().catch(() => {}); }, 120000);
}

init();
