const RANGES = { '1m': 60, '15m': 900, '1h': 3600, '6h': 21600, '24h': 86400 };
const TITLES = { dashboard: 'Dashboard', graficos: 'Gráficos', historico: 'Histórico', config: 'Configurações' };
const RLABEL = { '1m': '1 min', '15m': '15 min', '1h': '1 h', '6h': '6 h', '24h': '24 h', custom: 'período personalizado' };
const LAB = { no_comm: 'Sem comunicação', invalid: 'Leitura inválida', out_of_range: 'Fora da faixa' };
const PAGE = 50;
const STALE_MS = 8000; // sem amostra nova há mais que isso: a leitura deixa de ser tratada como atual
const store = { get: k => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
// method = método de ensaio (qual instrumento é comparado com a balança); vmode = só a forma de EXIBIR os resultados (precipitação ou vazão)
const S = { link: null, sum: null, cfg: null, range: null, method: store.get('elus.method') === 'comp' ? 'comp' : 'grav', vmode: store.get('elus.vmode') === 'flow' ? 'flow' : 'precip',
  latest: null, lastRx: null, sock: false, spark: [], page: 0, events: [], evIds: new Set(), lastTotal: null, detKey: null, seen: store.get('elus.seen') };   // seen = último ensaio cujo resultado o operador já fechou

// A aba atual vive em memória: não depende da URL do documento (que muda quando a página é embutida num visualizador).
let current = (() => { try { const h = location.hash.slice(1); if (h in TITLES) return h; } catch (e) {} return 'dashboard'; })();
const view = () => current;
function go(v) { current = v; try { history.replaceState(null, '', '#' + v); } catch (e) {} route(); }

// ---------- unidades ----------
const MU = () => Units.mass[S.cfg.mass_unit] || Units.mass.g, TU = () => Units.temp[S.cfg.temp_unit] || Units.temp.C;
const massV = v => v == null ? null : MU().to(v), tempV = v => v == null ? null : TU().to(v);
const flowL = v => v == null ? null : Flow.convert(v, 'L/min', S.cfg.flow_unit, S.cfg.density_g_cm3); // toda vazão do servidor vem em L/min
const fnum = v => Fmt.num(v, S.cfg.flow_decimals);
// Pluviômetro em volume: P (mm) × A (cm²) ÷ 10 = V (mL); intensidade (mm/h) × A ÷ 10 = mL/h -> L/min -> unidade escolhida
const volEq = (mm, area) => mm == null || !area ? null : mm * area / 10;
const flowEq = (mmh, area) => mmh == null || !area ? null : flowL(mmh * area / 10 / 1000 / 60);
const DENS_MSG = 'Informe a densidade da água em Configurações.';
const isStale = () => !S.sock || S.lastRx == null || Date.now() - S.lastRx > STALE_MS;
const K = (l, v, u, tag) => Trials.kv(l, v, u, tag), PARC = ['p', 'parcial'], REF = ['r', 'ref.'];

function getRange() {
  if (S.range.key === 'custom' && S.range.from && S.range.to) return { from: S.range.from, to: S.range.to };
  const to = Date.now(); return { from: to - RANGES[S.range.key] * 1000, to };
}
function statLine(st, dec, conv, unit) {
  if (!st || st.avg == null) return 'Sem leituras válidas no período';
  const n = v => Fmt.num(conv(v), dec);
  return `${n(st.avg)} ${unit} · mín ${n(st.min)} · máx ${n(st.max)}`;
}
function corStatText(cs) {
  const n = cs.ma.n_out, out = n ? ` · ${n} ${n === 1 ? 'leitura' : 'leituras'} fora da faixa` : '';
  if (cs.flow) {
    if (flowL(cs.flow.avg) == null) return 'Média — (informe a densidade)' + out;
    return statLine(cs.flow, S.cfg.flow_decimals, flowL, S.cfg.flow_unit) + out;
  }
  if (cs.mode === 'pulse') return (cs.pulses ? `${Fmt.num(cs.pulses.avg_hz, 1)} Hz em média · informe o fator K para ver a vazão` : 'Sem leituras válidas no período') + out;
  if (cs.ma.n) return statLine(cs.ma, 3, v => v, 'mA') + ' · faixa não configurada' + out;
  return 'Sem leituras válidas no período' + out;
}

// ---------- indicadores de comunicação ----------
const PILL = { ok: ['Comunicação OK', 'ok'], no_comm: ['Sem comunicação', 'err'], invalid: ['Leitura inválida', 'warn'], out_of_range: ['Fora da faixa', 'warn'], stale: ['Sem dados', ''], na: ['Aguardando integração', ''], unconfigured: ['Não configurado', 'warn'] };
function pill(sel, st) { const el = $(sel), m = PILL[st] || PILL.stale; el.className = 'pill ' + m[1]; el.lastElementChild.textContent = m[0]; }
function setPills() {
  if (!S.cfg) return;
  const stale = isStale(), s = S.latest || {}, l = S.link || {};
  pill('#p-mass', stale ? 'stale' : s.mass_status); pill('#p-temp', stale ? 'stale' : s.temp_status); pill('#p-tips', stale ? 'stale' : 'ok');
  pill('#p-cor', l.flow_integrated === false || (!stale && s.flow_state === 'na') ? 'na' : stale ? 'stale' : s.flow_state === 'ok' ? 'ok' : s.flow_state || 'stale');
  const c = $('#conn');
  c.className = 'pill ' + (!S.sock ? 'err' : stale ? 'warn' : 'ok');
  c.lastElementChild.textContent = !S.sock ? 'Servidor desconectado' : stale ? 'Sem dados do datalogger' : 'Recebendo dados';
  const r = $('#real'), err = l.error;
  r.className = 'pill ' + (!S.sock ? 'err' : stale ? (err ? 'err' : 'warn') : 'ok');
  r.lastElementChild.textContent = !S.sock ? 'Servidor desconectado' : stale ? (err ? 'Datalogger sem resposta' : 'Aguardando dados novos') : 'Dados reais do datalogger';
  r.title = err || '';
  document.body.classList.toggle('stale-data', stale);
  const sk = $('#skew'), k = l.clock_skew_s;
  sk.hidden = !(k != null && Math.abs(k) > 10);
  if (!sk.hidden) sk.textContent = `Atenção: o relógio do datalogger difere do deste computador em cerca de ${Fmt.num(Math.abs(k), 0)} s. Períodos relativos (“últimos 15 min”) podem ficar deslocados. Acerte o relógio do datalogger.`;
  $('#upd').textContent = s.ts ? Fmt.dt(s.ts) + (stale ? ' (desatualizada)' : '') : '—';
  if (stale) { $('#temp-val').textContent = $('#cor-val').textContent = '—'; $('#cor-big').className = 'big sm'; } // leitura antiga NÃO fica na tela como atual
}

// ---------- ensaio: os dois cards entram em modo ensaio (parcial → congelado) até "Voltar ao tempo real" ----------
// trial(): {t, run} do ensaio que os cards devem mostrar, ou null (modo ao vivo / período)
function trial() {
  const { running: run, last } = Trials.st, kind = S.method === 'comp' ? 'flow' : 'pluv';
  if (run) return { t: run, run: true, g: run.partial && run.partial.gravimetric, f: run.partial && run.partial.flow };
  if (last && last.kind === kind && last.result && last.id !== S.seen) return { t: last, run: false, g: last.result.gravimetric, f: last.result.flow };
  return null;
}
const tTag = x => x.run ? Trials.STATE.running : Trials.STATE[x.t.state];
const tSpan = x => x.g && x.g.duration_s != null ? `intervalo ${Fmt.num(x.g.duration_s, 0)} s` : x.run ? 'aguardando leituras' : 'sem intervalo de referência';

// ---------- card da balança ----------
function renderBal() {
  if (!S.cfg || !S.range) return;
  const x = trial(), s = S.latest || {}, dm = S.cfg.mass_decimals, mu = MU().l, fu = S.cfg.flow_unit;
  const live = isStale() ? null : massV(s.mass_g), P = x && x.run ? PARC : '';
  let val = live, unit = mu, name = 'Massa atual', rows, notes = [];
  if (x && x.t.kind === 'flow') {   // método comparativo: a balança é a referência do medidor
    const g = x.g || {}, v = x.f && x.f.vs_reference;
    rows = K('Volume de referência', Fmt.num(g.volume_ml, 1), 'mL', P) + K('Vazão de referência', fnum(flowL(g.flow_ref_l_min)), fu, P)
      + K('Volume do medidor', Fmt.num(v && v.volume_meter_l != null ? v.volume_meter_l * 1000 : null, 1), 'mL', P);
    if (x.run) rows = K('Massa coletada (parcial)', Fmt.num(massV(g.delta_mass_g), dm), mu, P) + rows;   // ao vivo em destaque enquanto roda
    else { val = massV(g.delta_mass_g); name = `Massa coletada · ${tSpan(x)}`; rows += K('Massa atual', Fmt.num(live, dm), mu); }
  } else if (x) {
    const g = x.g || {};
    if (S.vmode === 'flow') rows = K('Vazão', fnum(flowL(g.flow_ref_l_min)), fu, P) + K('Massa coletada', Fmt.num(massV(g.delta_mass_g), dm), mu, P);
    else rows = K('Precipitação equivalente', Fmt.num(g.precip_ref_mm, 2), 'mm', P) + K('Intensidade equivalente', Fmt.num(g.intensity_ref_mm_h, 1), 'mm/h', P) + K('Volume', Fmt.num(g.volume_ml, 1), 'mL', P);
    if (x.run) rows = K(S.vmode === 'flow' ? 'Volume coletado (parcial)' : 'Massa coletada (parcial)', S.vmode === 'flow' ? Fmt.num(g.volume_ml, 1) : Fmt.num(massV(g.delta_mass_g), dm), S.vmode === 'flow' ? 'mL' : mu, P) + rows;   // massa ao vivo em destaque enquanto roda
    else if (S.vmode === 'flow') { val = g.volume_ml; unit = 'mL'; name = `Volume coletado · ${tSpan(x)}`; rows += K('Massa atual', Fmt.num(live, dm), mu); }
    else { val = massV(g.delta_mass_g); name = `Massa coletada · ${tSpan(x)}`; rows += K('Massa atual', Fmt.num(live, dm), mu); }
  } else {
    const st = S.sum && S.sum.stats.mass, g = S.sum && S.sum.grav, per = RLABEL[S.range.key];
    rows = S.vmode === 'flow'
      ? K(`Vazão pela balança · ${per}`, fnum(g && flowL(g.flow_ref_l_min)), fu) + K(`Volume coletado · ${per}`, Fmt.num(g && g.volume_ml, 1), 'mL')
      : K(`Média do período · ${per}`, Fmt.num(st && st.avg != null ? massV(st.avg) : null, dm), mu);
    if (S.vmode === 'flow' && g && g.volume_ml == null) notes.push(...g.issues);
  }
  if (x) {
    if (x.run) rows = K('Tempo decorrido', Trials.mmss(x.t.elapsed_s)) + K('Tempo restante', `${Trials.mmss(x.t.remaining_s)} de ${Trials.mmss(x.t.duration_cfg_s)}`) + rows;
    else if (x.t.state !== 'completed' && x.t.reason) notes.push(x.t.reason);
    if (x.g && !(x.run && x.g.duration_s == null)) notes.push(...(x.g.issues || []).filter(i => !(x.t.reason || '').includes(i)));   // nos primeiros segundos ainda não há 2 leituras: não é falha
  }
  $('#bal-val').textContent = Fmt.num(val, unit === 'mL' ? 1 : dm); $('#bal-unit').textContent = unit; $('#bal-name').textContent = name;
  setHtml($('#bal-rows'), rows);
  setHtml($('#bal-notes'), notes.map(t => `<p class="note err">${t}</p>`).join(''));
  const tag = x ? tTag(x) : ['Sem ensaio', ''], el = $('#bal-state');
  el.textContent = tag[0]; el.className = 'tag ' + (tag[1] || '');
  $('#bal-bar').hidden = !(x && x.run);
  if (x && x.run) $('#bal-bar i').style.width = Math.min(100, 100 * x.t.elapsed_s / x.t.duration_cfg_s) + '%';
  const done = x && !x.run ? x.t : null, det = $('#bal-det'), key = done ? done.id : null;
  det.hidden = !done;
  if (done && key !== S.detKey) {   // só reescreve quando muda: não fecha nem rola o painel aberto
    const d = { ...S.cfg, density_g_cm3: done.cfg.density };
    $('#bal-det-body').innerHTML = Trials.summary(done) + (done.kind === 'flow' ? Trials.flowHtml(done.result, d, false) : Trials.pluvHtml(done.result, d, false, 'bal'))
      + `<p class="grp"><a class="btn" href="/relatorio/${done.id}" target="_blank">Relatório (imprimir / PDF)</a><a class="btn" href="/api/trials/${done.id}/raw.csv">Amostras (CSV)</a><a class="btn" href="/api/trials/${done.id}/tips.csv">Basculadas (CSV)</a></p>`;
  }
  S.detKey = key;
  const btn = $('#bal-go'), dur = $('#bal-dur');
  btn.textContent = x && x.run ? 'Encerrar ensaio' : done ? 'Voltar ao tempo real' : 'Iniciar ensaio'; btn.classList.toggle('stop', !!(x && x.run));
  btn.dataset.done = done ? done.id : '';
  $('#bal-dur-w').hidden = !!x;
  if (document.activeElement !== dur && !S.durP) dur.value = S.cfg.trial_duration_s;
}

// ---------- card do pluviômetro: período selecionado, ou o ensaio (mesmo intervalo da balança) ----------
function renderPluv() {
  const d = S.sum, x = trial(); if (!d || !S.cfg) return;
  const res = d.resolution, rd = Trials.dec(res), fu = S.cfg.flow_unit;
  let val, unit, name, rows, note = '', part, tag;
  if (x && x.t.kind === 'pluv') {   // modo ensaio: as mesmas grandezas da balança, no mesmo intervalo (t0, t1]
    const g = x.g || {}, area = g.area_cm2, P = x.run ? PARC : '';
    part = x.run; tag = tTag(x);
    if (S.vmode === 'flow') { val = volEq(g.pluv_precip_mm, area); unit = 'mL'; name = `Volume equivalente · ${tSpan(x)}`;
      rows = K('Basculadas', g.pulses_window == null ? '—' : g.pulses_window, '', P) + K('Vazão equivalente', fnum(flowEq(g.pluv_intensity_mm_h, area)), fu, P) + K('Precipitação', Fmt.num(g.pluv_precip_mm, rd), 'mm', P); }
    else { val = g.pluv_precip_mm; unit = 'mm'; name = `Precipitação acumulada · ${tSpan(x)}`;
      rows = K('Basculadas', g.pulses_window == null ? '—' : g.pulses_window, '', P) + K('Intensidade', Fmt.num(g.pluv_intensity_mm_h, 1), 'mm/h', P) + K('Volume', Fmt.num(volEq(g.pluv_precip_mm, area), 1), 'mL', P); }
    if (!g.resolution_mm) note = 'Resolução do pluviômetro não configurada neste ensaio.';
  } else {
    const p = d.period, area = d.area_cm2, per = RLABEL[S.range.key];
    part = !p.complete && p.precip_mm != null; tag = null;
    if (S.vmode === 'flow') { val = volEq(p.precip_mm, area); unit = 'mL'; name = `Volume equivalente · ${per}`;
      rows = K('Basculadas', p.tips) + K('Vazão equivalente', fnum(flowEq(p.intensity_mm_h, area)), fu, part && p.intensity_mm_h != null ? PARC : '') + K('Precipitação', Fmt.num(p.precip_mm, rd), 'mm');
      if (!area) note = 'Informe a área de captação em Configurações.'; }
    else { val = p.precip_mm; unit = 'mm'; name = `Precipitação acumulada · ${per}`;
      rows = K('Basculadas', p.tips) + K('Intensidade média', Fmt.num(p.intensity_mm_h, 2), 'mm/h', part && p.intensity_mm_h != null ? PARC : ''); }
    if (!res) note = 'Informe a resolução do pluviômetro em Configurações.';
  }
  $('#pl-val').textContent = Fmt.num(val, unit === 'mL' ? 1 : rd); $('#pl-unit').textContent = unit; $('#pl-name').textContent = name;
  $('#pl-tag').hidden = !part || val == null;
  const el = $('#pl-state'); el.hidden = !tag; if (tag) { el.textContent = tag[0]; el.className = 'tag ' + (tag[1] || ''); }
  setHtml($('#pl-rows'), rows);
  $('#pl-note').textContent = note; $('#pl-note').hidden = !note;
  const done = x && !x.run && x.t.kind === 'pluv' ? x.t : null, key = done ? done.id : null;   // detalhes do pluviômetro: só o que ele mediu
  $('#pl-det').hidden = !done;
  if (done && key !== S.plDetKey) $('#pl-det-body').innerHTML = Trials.pluvHtml(done.result, S.cfg, false, 'pluv');
  S.plDetKey = key;
}

// ---------- medidor de vazão (só no método comparativo) ----------
function renderCor(s) {
  let txt = '—', unit = S.cfg.flow_unit, note = '', textual = false;
  const st = S.link && S.link.flow_integrated === false ? 'na' : (s.flow_state || 'na'), stale = isStale(), mode = s.flow_mode;
  if (stale && st !== 'na') { txt = '—'; }
  else if (st === 'ok') { const v = flowL(s.flow_lmin); if (v == null) note = DENS_MSG; else txt = fnum(v); }
  else if (st === 'unconfigured') note = mode === 'pulse' ? 'Informe o fator K em Configurações.' : 'Informe a vazão em 4 mA e em 20 mA em Configurações.';
  else if (st === 'out_of_range') { txt = 'Fora da faixa'; textual = true; unit = ''; }
  else if (st === 'invalid') { txt = 'Leitura inválida'; textual = true; unit = ''; }
  else if (st === 'na') { txt = 'Aguardando integração'; textual = true; unit = ''; }
  else { txt = 'Sem dados'; textual = true; unit = ''; }
  $('#cor-val').textContent = txt; $('#cor-unit').textContent = unit; $('#cor-big').className = 'big sm' + (textual ? ' txt' : '');
  $('#cor-sig').textContent = st === 'na' || stale ? '' : mode === 'pulse' ? `Sinal: ${s.flow_hz == null ? '—' : Fmt.num(s.flow_hz, 1)} Hz` : `Sinal: ${s.cor_ma == null ? '—' : Fmt.num(s.cor_ma, 3) + ' mA'}`;
  $('#cor-note').textContent = note;
}
function renderLatest() {
  const s = S.latest; if (!s) { setPills(); return; }
  $('#temp-val').textContent = isStale() ? '—' : Fmt.num(tempV(s.temp_c), S.cfg.temp_decimals); $('#temp-unit').textContent = TU().l;
  $('#tips-total').textContent = s.tips_total; $('#last-tip').textContent = Fmt.dt(s.last_tip_ts);
  renderCor(s);
  if (s.temp_c != null && s.ts !== S.sparkTs) { S.sparkTs = s.ts; S.spark.push(s.temp_c); S.spark = S.spark.slice(-60); drawSpark(); }
  if (S.lastTotal !== s.tips_total) { S.lastTotal = s.tips_total; drawEvents(); }
  renderBal(); renderPluv(); setPills();
}
function drawSpark() {
  const v = S.spark, lo = Math.min(...v), hi = Math.max(...v), h = hi - lo || 1;
  $('#spark').setAttribute('points', v.map((y, i) => `${(i / Math.max(1, v.length - 1) * 290).toFixed(1)},${(52 - (y - lo) / h * 44).toFixed(1)}`).join(' '));
}
async function refreshSummary() {
  if (S.busyS) return; S.busyS = true;   // sem consultas sobrepostas (períodos longos podem passar de 2 s)
  try { await _refreshSummary(); } finally { S.busyS = false; }
}
async function _refreshSummary() {
  const r = getRange(), d = await Api.get('/api/summary', r), lbl = ` (${RLABEL[S.range.key]})`;
  if (r.from !== getRange().from && S.range.key === 'custom') return;
  S.link = d.link; S.sum = d;
  if (d.link.last_rx_ts) { const rx = Date.now() - (d.now - d.link.last_rx_ts); S.lastRx = Math.max(S.lastRx || 0, rx); } // o servidor sabe quando chegou a última amostra nova
  if (!S.latest && d.latest) S.latest = d.latest;
  if (!S.latest) { $('#tips-total').textContent = d.tips_total; $('#last-tip').textContent = Fmt.dt(d.last_tip_ts); }
  $('#temp-stats').textContent = 'Média do período' + lbl + ': ' + statLine(d.stats.temp, S.cfg.temp_decimals, TU().to, TU().l);
  $('#cor-stats').textContent = 'Média do período' + lbl + ': ' + corStatText(d.stats.cor);
  renderLatest();   // renderLatest já chama renderBal e renderPluv
}

// ---------- eventos de basculamento (cada um com id único: sem contar em dobro nem perder) ----------
// Cada linha: nº, hora, massa ejetada desde a basculada anterior (barra proporcional) e massa na balança naquele instante.
// As conchas se alternam a cada basculada: as barras alternam a cor para os dois lados ficarem comparáveis à vista.
function evRows(list, total) {
  const dm = S.cfg.mass_decimals, mu = MU().l, max = Math.max(...list.map(e => e.dm_g == null ? 0 : Math.abs(e.dm_g)), 0);
  return list.map((e, i) => {
    const prev = list[i + 1], n = total == null ? null : total - i, side = n == null ? i % 2 : n % 2;
    const w = e.dm_g == null || max <= 0 ? 0 : Math.max(2, 100 * Math.abs(e.dm_g) / max);
    return `<li class="ev s${side}"><span class="n">${n == null ? '' : n}</span><span class="t">${Fmt.time(e.ts)}${prev ? `<small>+${Fmt.num((e.ts - prev.ts) / 1000, 1)} s</small>` : ''}</span>
      <span class="d"><b>${e.dm_g == null ? '—' : Fmt.num(massV(e.dm_g), dm) + ' ' + mu}</b><i style="width:${w}%"></i></span>
      <span class="m" title="${e.settled ? 'massa 3 s após a basculada' : 'massa no segundo da basculada (a próxima veio antes de 3 s)'}">${e.mass_g == null ? '—' : Fmt.num(massV(e.mass_g), dm) + ' ' + mu}${e.settled ? '' : '<small>*</small>'}</span></li>`;
  }).join('');
}
function drawEvents() {
  const total = S.latest ? S.latest.tips_total : null;
  setHtml($('#ev-list'), S.events.length ? `<li class="ev hd"><span class="n">nº</span><span class="t">hora</span><span class="d">massa ejetada</span><span class="m">na balança, 3 s depois</span></li>` + evRows(S.events, total)
    : '<li class="lbl">Nenhuma basculada registrada ainda.</li>');
}
function pushEvents(list) { // basculadas novas pelo socket: a massa do instante vem do servidor, então recarrega a lista (é raro e leve)
  if (list.some(e => !S.evIds.has(e.id))) loadEvents().catch(() => {});
}
async function loadEvents() { const d = await Api.get('/api/tips', { from: 0, to: Date.now() + 60000, limit: 10 }); S.events = d.events; S.evIds = new Set(d.events.map(e => e.id)); drawEvents(); }

// ---------- gráficos: resultado do período em destaque, média do período discreta ----------
function setRes(k, v, unit, name, sub) {
  $(`#r-${k}`).innerHTML = v + (v !== '—' && unit ? ` <small>${unit}</small>` : ''); $(`#r-${k}-n`).textContent = name; $(`#st-${k}`).textContent = sub;
}
async function refreshCharts() {
  if (S.busyC) return; S.busyC = true;
  try { await _refreshCharts(); } finally { S.busyC = false; }
}
async function _refreshCharts() {
  const r = getRange(), [d, sm] = await Promise.all([Api.get('/api/series', r), Api.get('/api/summary', r)]);
  S.link = sm.link; S.sum = sm;
  const comp = S.method === 'comp', per = RLABEL[S.range.key], st = d.stats, g = sm.grav, p = sm.period, fu = S.cfg.flow_unit, dm = S.cfg.mass_decimals;
  Charts.render(d, r, S.cfg, comp);
  const avgMass = 'Média do período: ' + statLine(st.mass, dm, MU().to, MU().l), issue = g.issues.length ? ' · ' + g.issues[0] : '';
  if (S.vmode === 'flow') setRes('mass', fnum(flowL(g.flow_ref_l_min)), fu, `Vazão pela balança · ${per}`, avgMass + (g.flow_ref_l_min == null ? issue : ''));
  else setRes('mass', Fmt.num(massV(g.delta_mass_g), dm), MU().l, `Massa coletada · ${per}`, avgMass + (g.delta_mass_g == null ? issue : ''));
  if (S.vmode === 'flow') setRes('pluv', Fmt.num(volEq(p.precip_mm, sm.area_cm2), 1), 'mL', `Volume equivalente · ${per}`, `Vazão equivalente: ${fnum(flowEq(p.intensity_mm_h, sm.area_cm2))} ${fu} · ${p.tips} basculadas`);
  else setRes('pluv', Fmt.num(p.precip_mm, Trials.dec(sm.resolution)), 'mm', `Precipitação acumulada · ${per}`, `Intensidade média: ${Fmt.num(p.intensity_mm_h, 2)} mm/h · ${p.tips} basculadas`);
  setRes('temp', Fmt.num(st.temp.avg == null ? null : tempV(st.temp.avg), S.cfg.temp_decimals), TU().l, `Média do período · ${per}`,
    st.temp.avg == null ? 'Sem leituras válidas no período' : `mín ${Fmt.num(tempV(st.temp.min), S.cfg.temp_decimals)} · máx ${Fmt.num(tempV(st.temp.max), S.cfg.temp_decimals)} · ${st.temp.n} leituras`);
  if (comp) setRes('cor', fnum(st.cor.flow && flowL(st.cor.flow.avg)), fu, `Vazão média · ${per}`, corStatText(st.cor));
}

// ---------- histórico ----------
const estado = (r, sensor) => {
  const use = k => sensor === 'all' || sensor === k;
  const p = [[use('mass') ? r.mass_status : 'ok', 'balança'], [use('temp') ? r.temp_status : 'ok', 'termopar'], [use('cor') ? r.cor_status : 'ok', 'medidor de vazão']]
    .filter(x => x[0] && x[0] !== 'ok').map(x => `${LAB[x[0]]} (${x[1]})`);
  return p.length ? [p.join('; '), p.some(t => t.startsWith('Leitura')) ? 'err' : 'warn'] : ['Válida', 'ok'];
};
async function loadHistory() {
  const r = getRange(), sensor = $('#f-sensor').value, state = $('#f-state').value, p = { ...r, sensor, state };
  const [d, ev] = await Promise.all([Api.get('/api/history', { ...p, limit: PAGE, offset: S.page * PAGE }), Api.get('/api/tips', { ...r, limit: 200 })]);
  const res = d.resolution, dm = S.cfg.mass_decimals, st = d.stats;
  $('#h-table').dataset.s = sensor; $('#h-unit').textContent = MU().l; $('#h-tunit').textContent = TU().l; $('#h-funit').textContent = S.cfg.flow_unit; $$('.h-mu').forEach(e => { e.textContent = MU().l; });
  const corCell = x => x.flow_state === 'ok' ? fnum(flowL(x.flow_lmin)) : '—';
  $('#h-body').innerHTML = d.rows.map(x => { const [lab, cls] = estado(x, sensor);
    return `<tr><td>${Fmt.dt(x.ts)}</td><td data-c="mass">${Fmt.num(massV(x.mass_g), dm)}</td><td data-c="temp">${Fmt.num(tempV(x.temp_c), S.cfg.temp_decimals)}</td><td data-c="cor">${Fmt.num(x.cor_ma, 3)}</td><td data-c="cor">${Fmt.num(x.flow_pulses, 0)}</td><td data-c="cor">${corCell(x)}</td><td data-c="tips">${x.tips_total}</td><td data-c="tips">${res ? Fmt.num(x.tips_total * res, Trials.dec(res)) : '—'}</td><td class="${cls}">${lab}</td></tr>`; }).join('')
    || '<tr><td colspan="9" class="lbl">Nenhuma medição neste período e filtro.</td></tr>';
  const av = (s, conv, dec) => s && s.avg != null ? Fmt.num(conv(s.avg), dec) : '—', cf = st.cor.flow;
  $('#h-foot').innerHTML = `<td>Média do período</td><td data-c="mass">${av(st.mass, MU().to, dm)}</td><td data-c="temp">${av(st.temp, TU().to, S.cfg.temp_decimals)}</td><td data-c="cor">${av(st.cor.ma, v => v, 3)}</td><td data-c="cor">${st.cor.pulses ? Fmt.num(st.cor.pulses.avg_hz, 1) + ' Hz' : '—'}</td><td data-c="cor">${cf && flowL(cf.avg) != null ? av(cf, flowL, S.cfg.flow_decimals) : '—'}</td><td data-c="tips">—</td><td data-c="tips">—</td><td class="lbl">Leituras válidas: massa ${st.mass.n.toLocaleString('pt-BR')}, temperatura ${st.temp.n.toLocaleString('pt-BR')}, medidor de vazão ${(st.cor.ma.n + (st.cor.pulses ? st.cor.pulses.n : 0)).toLocaleString('pt-BR')}</td>`;
  const a = S.page * PAGE;
  $('#h-count').textContent = d.total ? `Exibindo ${a + 1}–${Math.min(a + PAGE, d.total)} de ${d.total.toLocaleString('pt-BR')} registros` : '';
  $('#h-prev').disabled = S.page === 0; $('#h-next').disabled = a + PAGE >= d.total;
  const qs = new URLSearchParams(p).toString(); $('#x-csv').href = '/export.csv?' + qs; $('#x-xlsx').href = '/export.xlsx?' + qs;
  $('#x-ev').href = '/export-eventos.csv?' + new URLSearchParams(r).toString();
  $('#ev-count').textContent = ev.total > ev.events.length ? `Mostrando ${ev.events.length} de ${ev.total.toLocaleString('pt-BR')}` : `${ev.total.toLocaleString('pt-BR')} no período`;
  $('#ev-body').innerHTML = ev.events.map((e, i) => { const prev = ev.events[i + 1];
    return `<tr><td>${Fmt.dt(e.ts)}</td><td>${prev ? Fmt.num((e.ts - prev.ts) / 1000, 1) + ' s' : '—'}</td><td>${Fmt.num(massV(e.mass_g), dm)}</td><td>${Fmt.num(massV(e.dm_g), dm)}</td></tr>`; }).join('') || '<tr><td colspan="4" class="lbl">Nenhuma basculada neste período.</td></tr>';
  await loadTrials();
}

// ---------- ensaios ----------
async function loadTrials() { Trials.st = await Api.get('/api/trials'); renderBal(); renderPluv(); renderTrialHistory(); }
function renderTrialHistory() {
  const h = Trials.st.history || [];
  $('#tr-hist').innerHTML = h.map(t => { const [lab, cls] = Trials.STATE[t.state] || [t.state, '']; return `<tr><td>${Fmt.dt(t.start_ts)}</td><td>${Trials.KIND[t.kind] || t.kind}</td><td class="${cls}">${lab}</td><td>${Trials.mmss((t.end_ts - t.start_ts) / 1000)} de ${Trials.mmss(t.duration_cfg_s)}</td><td>${t.reason || ''}</td><td><button class="btn" data-id="${t.id}">Ver</button></td></tr>`; }).join('')
    || '<tr><td colspan="6" class="lbl">Nenhum ensaio realizado.</td></tr>';
  $$('#tr-hist button').forEach(b => b.onclick = async () => {
    const t = await Api.get('/api/trials/' + b.dataset.id), el = $('#tr-detail'); el.hidden = false;
    el.innerHTML = Trials.detail(t, S.cfg) + `<p class="grp"><a class="btn" href="/relatorio/${t.id}" target="_blank">Relatório (imprimir / PDF)</a><a class="btn" href="/api/trials/${t.id}/raw.csv">Amostras (CSV)</a><a class="btn" href="/api/trials/${t.id}/tips.csv">Basculadas (CSV)</a></p>`;
    $('#tr-close').onclick = () => { el.hidden = true; };
  });
}
async function trialToggle() {
  const run = Trials.st.running, msg = $('#bal-msg'), done = $('#bal-go').dataset.done;
  msg.textContent = '';
  if (!run && done) { S.seen = done; store.set('elus.seen', done); renderBal(); renderPluv(); return; }   // fecha o resultado: o ensaio continua no Histórico
  try {
    if (run) { if (!confirm('Encerrar o ensaio agora? Ele ficará registrado como interrompido.')) return; await Api.post('/api/trials/stop'); }
    else {
      if (S.durP && !(await S.durP)) return;   // duração digitada: espera o salvamento terminar antes de iniciar
      if (Number($('#bal-dur').value) !== S.cfg.trial_duration_s && !(await saveDuration())) return;
      await Api.post('/api/trials/start', { kind: S.method === 'comp' ? 'flow' : 'pluv' });
    }
    await loadTrials();
  } catch (e) { msg.textContent = e.message; await loadTrials().catch(() => {}); }
}

// ---------- configurações ----------
const num = s => { s = String(s).trim().replace(',', '.'); return s === '' ? null : Number(s); };
// corpo completo do POST /api/config a partir da configuração atual (o servidor zera campos numéricos ausentes)
const cfgBody = c => ({ mass_unit: c.mass_unit, temp_unit: c.temp_unit, flow_unit: c.flow_unit, mass_decimals: c.mass_decimals, temp_decimals: c.temp_decimals,
  flow_decimals: c.flow_decimals, tip_resolution_mm: c.tip_resolution_mm, density_g_cm3: c.density_g_cm3, catch_area_cm2: c.catch_area_cm2,
  flow_k_pulses_per_l: c.flow_k_pulses_per_l, default_range_s: c.default_range_s, trial_duration_s: c.trial_duration_s, cor: c.cor });
async function saveDuration() {
  const el = $('#bal-dur'), v = Number(el.value), msg = $('#bal-msg');
  if (!Number.isInteger(v) || v < 10 || v > 21600) { msg.textContent = 'Duração: use um número inteiro de 10 a 21600 s.'; el.value = S.cfg.trial_duration_s; return false; }
  try { S.cfg = await Api.post('/api/config', { ...cfgBody(S.cfg), trial_duration_s: v }); msg.textContent = ''; return true; }
  catch (e) { msg.textContent = 'Não foi possível salvar a duração: ' + e.message; el.value = S.cfg.trial_duration_s; return false; }
}
function corError(q4, q20) {
  if ((q4 === null) !== (q20 === null)) return 'Informe a vazão em 4 mA e em 20 mA, ou deixe as duas vazias.';
  if (q4 !== null && (!isFinite(q4) || !isFinite(q20))) return 'Use apenas números nas vazões da faixa.';
  if (q4 !== null && q4 === q20) return 'A vazão em 20 mA não pode ser igual à vazão em 4 mA.';
  return '';
}
function checkCor() {
  const err = corError(num($('#cf-q4').value), num($('#cf-q20').value));
  $('#cf-cor-msg').textContent = err; $('#cf-save').disabled = !!err; return !err;
}
// Medidor de Vazão: some se o programa do datalogger não tem a variável; mostra só os campos do modo em uso (desconhecido: os dois)
function flowCfgVis() {
  const mode = S.latest && S.latest.flow_state !== 'na' ? S.latest.flow_mode : null;
  $('#cf-flow').hidden = !!S.link && S.link.flow_integrated === false;
  $('#cf-k-w').hidden = mode === 'analog'; $('#cf-an-w').hidden = mode === 'pulse';
}
function fillConfig() {
  const c = S.cfg, f = v => v == null ? '' : String(v).replace('.', ',');
  $('#cf-unit').value = c.mass_unit; $('#cf-tunit').value = c.temp_unit; $('#cf-funit').value = c.flow_unit;
  $('#cf-md').value = c.mass_decimals; $('#cf-td').value = c.temp_decimals; $('#cf-fd').value = c.flow_decimals;
  $('#cf-res').value = f(c.tip_resolution_mm); $('#cf-dens').value = f(c.density_g_cm3); $('#cf-area').value = f(c.catch_area_cm2); $('#cf-k').value = f(c.flow_k_pulses_per_l);
  $('#cf-q4').value = f(c.cor.q4); $('#cf-q20').value = f(c.cor.q20); $('#cf-cunit').value = c.cor.unit;
  $('#cf-range').value = c.default_range_s;
  checkCor(); flowCfgVis();
}
async function saveConfig() {
  if (!checkCor()) return;
  try {
    S.cfg = await Api.post('/api/config', { ...cfgBody(S.cfg), mass_unit: $('#cf-unit').value, temp_unit: $('#cf-tunit').value, flow_unit: $('#cf-funit').value,
      mass_decimals: $('#cf-md').value, temp_decimals: $('#cf-td').value, flow_decimals: $('#cf-fd').value,
      tip_resolution_mm: $('#cf-res').value, density_g_cm3: $('#cf-dens').value, catch_area_cm2: $('#cf-area').value, flow_k_pulses_per_l: $('#cf-k').value,
      default_range_s: $('#cf-range').value, cor: { q4: $('#cf-q4').value, q20: $('#cf-q20').value, unit: $('#cf-cunit').value } });
    fillConfig(); S.detKey = S.plDetKey = null;   // painéis de detalhes são reconstruídos com as unidades novas
    $('#cf-msg').textContent = 'Configurações salvas. Ensaios em andamento e já concluídos não mudam.';
    renderLatest(); refreshSummary();
  } catch (e) { $('#cf-msg').textContent = 'Não foi possível salvar: ' + e.message; }
}

// ---------- método, visualização, período e navegação ----------
function applyMethod() {
  const comp = S.method === 'comp';
  $$('#meth .seg button').forEach(b => { const on = b.dataset.m === S.method; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  $('#c-cor').hidden = $('#g-cor').hidden = !comp;
  renderBal();
  Object.values(Charts.c).forEach(c => c.resize());
}
function applyVmode() {
  $$('#vm .seg button').forEach(b => { const on = b.dataset.x === S.vmode; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  renderBal(); renderPluv();
}
function setChips() {
  $$('.chip').forEach(b => b.classList.toggle('on', b.dataset.r === S.range.key));
  $('#custom').hidden = S.range.key !== 'custom';
  if (S.range.key === 'custom') { const r = getRange(); $('#c-from').value = Fmt.local(r.from); $('#c-to').value = Fmt.local(r.to); }
}
function setRange(r) { S.range = r; S.page = 0; setChips(); refreshAll(); }
function refreshAll() { const v = view(); if (v === 'dashboard') refreshSummary(); if (v === 'graficos') refreshCharts(); if (v === 'historico') loadHistory(); if (v === 'config') flowCfgVis(); }
function route() {
  const v = view();
  $$('.view').forEach(e => { e.hidden = e.id !== 'v-' + v; });
  $$('.nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  $('#title').textContent = TITLES[v]; $('#ctrl').hidden = v === 'config'; $('#meth').hidden = $('#vm').hidden = v === 'historico';
  refreshAll();
}

$$('.nav button').forEach(b => b.onclick = () => go(b.dataset.v));
$$('#meth .seg button').forEach(b => b.onclick = () => { S.method = b.dataset.m; store.set('elus.method', S.method); applyMethod(); if (view() === 'graficos') refreshCharts(); });
$$('#vm .seg button').forEach(b => b.onclick = () => { S.vmode = b.dataset.x; store.set('elus.vmode', S.vmode); applyVmode(); if (view() === 'graficos') refreshCharts(); });
$$('.chip').forEach(b => b.onclick = () => b.dataset.r === 'custom' ? setRange({ key: 'custom', from: Date.now() - 9e5, to: Date.now() }) : setRange({ key: b.dataset.r }));
$('#c-apply').onclick = () => { const f = new Date($('#c-from').value).getTime(), t = new Date($('#c-to').value).getTime(); if (f < t) setRange({ key: 'custom', from: f, to: t }); };
$('#f-sensor').onchange = $('#f-state').onchange = () => { S.page = 0; loadHistory(); };
$('#h-prev').onclick = () => { S.page--; loadHistory(); }; $('#h-next').onclick = () => { S.page++; loadHistory(); };
$('#cf-save').onclick = saveConfig;
$('#bal-go').onclick = trialToggle;
$('#bal-dur').onchange = () => { S.durP = saveDuration().finally(() => { S.durP = null; }); };
['#cf-q4', '#cf-q20'].forEach(s => $(s).oninput = checkCor);
$('#reset').onclick = async () => { if (confirm('Zerar a contagem de basculadas? O histórico de medições e os ensaios são mantidos.')) { try { await Api.post('/api/reset-count'); } catch (e) { alert('Não foi possível zerar: ' + e.message); return; } S.events = []; S.evIds = new Set(); S.lastTotal = null; drawEvents(); refreshSummary(); } };
window.addEventListener('hashchange', () => { try { const h = location.hash.slice(1); if (h in TITLES && h !== current) { current = h; route(); } } catch (e) {} });

(async () => {
  S.cfg = await Api.get('/api/config'); fillConfig();
  S.range = { key: Object.keys(RANGES).find(k => RANGES[k] === S.cfg.default_range_s) || '15m' };
  setChips(); applyMethod(); applyVmode();
  Api.connect(s => { S.latest = s; S.lastRx = Date.now(); pushEvents(s.new_tips || []); renderLatest(); },
    ok => { S.sock = ok; setPills(); if (ok) { loadTrials().catch(() => {}); loadEvents().catch(() => {}); } },   // reconectou: ressincroniza ensaio e basculadas
    t => { const was = Trials.st.running; Trials.st = { ...Trials.st, running: t.running, last: t.last }; renderBal(); renderPluv(); if (was && !t.running) loadTrials(); });
  await loadEvents().catch(() => {}); await loadTrials().catch(() => {}); route();
  setInterval(() => { setPills(); renderBal(); renderPluv(); }, 1000);
  setInterval(() => { if (document.hidden) return; const v = view(); if (v === 'dashboard') refreshSummary(); if (v === 'graficos') refreshCharts(); }, 2000); // só atualiza o que está na tela
})();
