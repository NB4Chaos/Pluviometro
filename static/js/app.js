const RANGES = { '1m': 60, '15m': 900, '1h': 3600, '6h': 21600, '24h': 86400 };
const TITLES = { dashboard: 'Dashboard', graficos: 'Gráficos', historico: 'Histórico', padroes: 'Padrões', config: 'Configurações' };
const RLABEL = { '1m': '1 min', '15m': '15 min', '1h': '1 h', '6h': '6 h', '24h': '24 h', custom: 'período personalizado' };
const LAB = { no_comm: 'Sem comunicação', invalid: 'Leitura inválida', out_of_range: 'Fora da faixa', fault: 'Falha do sinal', unavailable: 'Canal indisponível' };
const PAGE = 50;
const STALE_MS = 8000; // sem amostra nova há mais que isso: a leitura deixa de ser tratada como atual
// Atualização do resumo do período (s) e recarga completa dos gráficos (s), conforme o período: períodos longos mudam devagar
const SUMMARY_EVERY = { '1m': 2, '15m': 2, '1h': 2, '6h': 5, '24h': 10, custom: 10 };
const CHART_RELOAD = { '1m': 15, '15m': 15, '1h': 30, '6h': 60, '24h': 60, custom: 0 };
const store = { get: k => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
// method = método de ensaio (qual instrumento é comparado com a balança); vmode = só a forma de EXIBIR os resultados (precipitação ou vazão)
const S = { link: null, sum: null, cfg: null, range: null, method: store.get('elus.method') === 'comp' ? 'comp' : 'grav', vmode: store.get('elus.vmode') === 'flow' ? 'flow' : 'precip',
  latest: null, lastRx: null, sock: false, spark: [], page: 0, events: [], evIds: new Set(), lastTotal: null, detKey: null, seen: store.get('elus.seen'),   // seen = último ensaio cujo resultado o operador já fechou
  lastSummary: 0, lastCharts: 0 };

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
const K = (l, v, u, tag) => Trials.kv(l, v, u, tag), PARC = ['p', 'parcial'], REF = ['r', 'ref.'], CALC = ['c', 'calculado'];
// valor principal: só reescreve quando muda e marca a troca com uma transição curta (opacidade; nada é reconsultado)
function setBig(sel, text) {
  const el = $(sel); if (!el || el.textContent === text) return;
  el.textContent = text;
  const big = el.closest('.big'); if (!big || reducedMotion()) return;
  big.classList.remove('tick'); void big.offsetWidth; big.classList.add('tick');
}
// duração do ensaio: guardada em ms; digitada na unidade escolhida pelo operador
const DU = { ms: 1, s: 1000, min: 60000 };
const durMsTyped = () => { const v = parseNum($('#bal-dur').value); return v == null || !isFinite(v) ? null : Math.round(v * DU[$('#bal-dur-u').value]); };
const durShow = (ms, u) => ms == null ? '' : String(Number((ms / DU[u]).toPrecision(12)));   // campo numérico: ponto decimal (o navegador exibe localizado)

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
  const mixed = cs.mixed ? ' · o método mudou no período' : '';
  if (cs.flow) {
    if (flowL(cs.flow.avg) == null) return 'Média — (informe a densidade)' + out;
    return statLine(cs.flow, S.cfg.flow_decimals, flowL, S.cfg.flow_unit) + out + mixed;
  }
  if (cs.mode === 'pulse') return (cs.pulses ? `${Fmt.num(cs.pulses.avg_hz, 1)} Hz em média · informe o fator K para ver a vazão` : 'Sem leituras válidas no período') + out;
  if (cs.ma.n) return statLine(cs.ma, 3, v => v, 'mA') + ' · faixa não configurada' + out;
  return 'Sem leituras válidas no período' + out;
}

// ---------- indicadores de comunicação ----------
const PILL = { ok: ['Comunicação OK', 'ok'], no_comm: ['Sem comunicação', 'err'], invalid: ['Leitura inválida', 'warn'], out_of_range: ['Fora da faixa', 'warn'],
  fault: ['Falha do sinal', 'err'], stale: ['Sem dados', ''], na: ['Aguardando integração', ''], unconfigured: ['Não configurado', 'warn'],
  unavailable: ['Indisponível', 'warn'], pending: ['Aguardando confirmação', 'warn'] };
function pill(sel, st) { const el = $(sel), m = PILL[st] || PILL.stale; el.className = 'pill ' + m[1]; el.lastElementChild.textContent = m[0]; }
function setPills() {
  if (!S.cfg) return;
  const stale = isStale(), s = S.latest || {}, l = S.link || {};
  pill('#p-mass', stale ? 'stale' : s.mass_status); pill('#p-temp', stale ? 'stale' : s.temp_status); pill('#p-tips', stale ? 'stale' : 'ok');
  const c = $('#conn');
  c.className = 'pill ' + (!S.sock ? 'err' : stale ? 'warn' : 'ok');
  c.lastElementChild.textContent = !S.sock ? 'Servidor desconectado' : stale ? (l.error ? 'Datalogger sem resposta' : 'Sem dados do datalogger') : 'Recebendo dados';
  c.title = l.error || '';
  document.body.classList.toggle('stale-data', stale);
  const sk = $('#skew'), k = l.clock_skew_s;
  sk.hidden = !(k != null && Math.abs(k) > 10);
  if (!sk.hidden) sk.textContent = `Atenção: o relógio do datalogger difere do deste computador em cerca de ${Fmt.num(Math.abs(k), 0)} s. Períodos relativos (“últimos 15 min”) podem ficar deslocados. Acerte o relógio do datalogger.`;
  setHtml($('#upd'), s.ts ? esc(Fmt.dt(s.ts)) + (stale ? ' (desatualizada)' : '<i class="beat" id="beat"></i>') : '—');
  if (stale) $('#temp-val').textContent = '—';   // leitura antiga NÃO fica na tela como atual
  FlowUI.renderMethod(); FlowUI.renderCard();
}
function beat() { const b = $('#beat'); if (!b) return; b.classList.remove('on'); void b.offsetWidth; b.classList.add('on'); }

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
    if (x.run) rows = Trials.timeRows(x.t) + rows;
    else if (x.t.state !== 'completed' && x.t.reason) notes.push(x.t.reason);
    if (x.g && !(x.run && x.g.duration_s == null)) notes.push(...(x.g.issues || []).filter(i => !(x.t.reason || '').includes(i)));   // nos primeiros segundos ainda não há 2 leituras: não é falha
  }
  setBig('#bal-val', Fmt.num(val, unit === 'mL' ? 1 : dm)); $('#bal-unit').textContent = unit; $('#bal-name').textContent = name;
  setHtml($('#bal-rows'), rows);
  setHtml($('#bal-notes'), notes.map(t => `<p class="note err">${esc(t)}</p>`).join(''));
  const tag = x ? tTag(x) : ['Sem ensaio', ''], el = $('#bal-state');
  el.textContent = tag[0]; el.className = 'tag ' + (tag[1] || '');
  Trials.bar('#bal-bar', x);
  const done = x && !x.run ? x.t : null, det = $('#bal-det'), key = done ? done.id : null;
  det.hidden = !done;
  if (done && key !== S.detKey) {   // só reescreve quando muda: não fecha nem rola o painel aberto
    const d = { ...S.cfg, density_g_cm3: done.cfg.density };
    $('#bal-det-body').innerHTML = Trials.summary(done) + (done.kind === 'flow' ? Trials.flowHtml(done.result, d, false) : Trials.pluvHtml(done.result, d, false, 'bal')) + Trials.timingHtml(done.result, done.kind) + Trials.links(done.id);
  }
  S.detKey = key;
  renderTrialCtl(x, done);
}
// controles do ensaio (dentro do card principal, seja ele a balança ou o medidor)
function renderTrialCtl(x, done) {
  const btn = $('#bal-go'), dur = $('#bal-dur'), u = $('#bal-dur-u');
  btn.textContent = x && x.run ? 'Encerrar ensaio' : done ? 'Voltar ao tempo real' : 'Iniciar ensaio'; btn.classList.toggle('stop', !!(x && x.run));
  btn.dataset.done = done ? done.id : '';
  $('#bal-dur-w').hidden = !!x;
  if (!S.durP && document.activeElement !== dur && document.activeElement !== u) { u.value = S.cfg.trial_duration_unit || 's'; dur.value = durShow(S.cfg.trial_duration_ms, u.value); }
  const lock = !!(Trials.st.running);   // o método de ensaio fica fixo enquanto um ensaio roda
  $$('#meth .seg button').forEach(b => { b.disabled = lock && b.dataset.m !== S.method; b.title = b.disabled ? 'O método fica fixo durante o ensaio.' : ''; });
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
  setBig('#pl-val', Fmt.num(val, unit === 'mL' ? 1 : rd)); $('#pl-unit').textContent = unit; $('#pl-name').textContent = name;
  $('#pl-tag').hidden = !part || val == null;
  const el = $('#pl-state'); el.hidden = !tag; if (tag) { el.textContent = tag[0]; el.className = 'tag ' + (tag[1] || ''); }
  setHtml($('#pl-rows'), rows);
  $('#pl-note').textContent = note; $('#pl-note').hidden = !note;
  const done = x && !x.run && x.t.kind === 'pluv' ? x.t : null, key = done ? done.id : null;   // detalhes do pluviômetro: só o que ele mediu
  $('#pl-det').hidden = !done;
  if (done && key !== S.plDetKey) $('#pl-det-body').innerHTML = Trials.pluvHtml(done.result, S.cfg, false, 'pluv');
  S.plDetKey = key;
}

// ---------- valores ao vivo ----------
function renderLatest() {
  const s = S.latest; if (!s) { setPills(); return; }
  $('#temp-val').textContent = isStale() ? '—' : Fmt.num(tempV(s.temp_c), S.cfg.temp_decimals); $('#temp-unit').textContent = TU().l;
  $('#tips-total').textContent = s.tips_total; $('#last-tip').textContent = Fmt.dt(s.last_tip_ts);
  if (s.temp_c != null && s.ts !== S.sparkTs) { S.sparkTs = s.ts; S.spark.push(s.temp_c); S.spark = S.spark.slice(-60); drawSpark(); }
  if (S.lastTotal !== s.tips_total) { S.lastTotal = s.tips_total; drawEvents(); }
  renderBal(); renderPluv(); setPills();
}
function drawSpark() {
  const v = S.spark, lo = Math.min(...v), hi = Math.max(...v), h = hi - lo || 1;
  $('#spark').setAttribute('points', v.map((y, i) => `${(i / Math.max(1, v.length - 1) * 290).toFixed(1)},${(52 - (y - lo) / h * 44).toFixed(1)}`).join(' '));
}
function onSample(s) {
  S.latest = s; S.lastRx = Date.now();
  FlowUI.fromSample(s.flow);
  pushEvents(s.new_tips || []);
  renderLatest(); beat();
  if (view() === 'graficos' && S.range && S.range.key !== 'custom') Charts.push(s, getRange(), S.cfg, S.method === 'comp');
  if ((s.new_tips || []).length) { refreshSummary(); if (view() === 'graficos') refreshCharts(); }   // basculada nova: período atualizado na hora
}
async function refreshSummary() {
  if (S.busyS) return; S.busyS = true;   // sem consultas sobrepostas (períodos longos podem passar de 2 s)
  try { await _refreshSummary(); S.lastSummary = Date.now(); } finally { S.busyS = false; }
}
async function _refreshSummary() {
  const r = getRange(), d = await Api.get('/api/summary', r), lbl = ` (${RLABEL[S.range.key]})`;
  if (r.from !== getRange().from && S.range.key === 'custom') return;
  S.link = d.link; S.sum = d;
  if (d.link.last_rx_ts) { const rx = Date.now() - (d.now - d.link.last_rx_ts); S.lastRx = Math.max(S.lastRx || 0, rx); } // o servidor sabe quando chegou a última amostra nova
  if (!S.latest && d.latest) S.latest = d.latest;
  if (d.flow) FlowUI.st = d.flow;
  if (!S.latest) { $('#tips-total').textContent = d.tips_total; $('#last-tip').textContent = Fmt.dt(d.last_tip_ts); }
  $('#temp-stats').textContent = 'Média do período' + lbl + ': ' + statLine(d.stats.temp, S.cfg.temp_decimals, TU().to, TU().l);
  $('#cor-stats').textContent = 'Média do período' + lbl + ': ' + corStatText(d.stats.cor);
  FlowUI.setStatus();
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

// ---------- gráficos: resultado do período em destaque, média do período discreta; pontos novos entram ao vivo ----------
function setRes(k, v, unit, name, sub) {
  $(`#r-${k}`).innerHTML = v + (v !== '—' && unit ? ` <small>${unit}</small>` : ''); $(`#r-${k}-n`).textContent = name; $(`#st-${k}`).textContent = sub;
}
async function refreshCharts() {
  if (S.busyC) return; S.busyC = true;
  try { await _refreshCharts(); S.lastCharts = Date.now(); } finally { S.busyC = false; }
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
const MSHORT = { analog: 'Analógico', pulse: 'Pulso' };
const estado = (r, sensor) => {
  const use = k => sensor === 'all' || sensor === k;
  const fs = r.flow_state === 'fault' ? 'fault' : r.cor_status;   // estado do medidor recalculado do dado bruto (distingue falha do sinal)
  const p = [[use('mass') ? r.mass_status : 'ok', 'balança'], [use('temp') ? r.temp_status : 'ok', 'termopar'], [use('cor') ? fs : 'ok', 'medidor de vazão']]
    .filter(x => x[0] && x[0] !== 'ok').map(x => `${LAB[x[0]] || x[0]} (${x[1]})`);
  return p.length ? [p.join('; '), p.some(t => t.startsWith('Leitura') || t.startsWith('Falha')) ? 'err' : 'warn'] : ['Válida', 'ok'];
};
async function loadHistory() {
  const r = getRange(), sensor = $('#f-sensor').value, state = $('#f-state').value, p = { ...r, sensor, state };
  const [d, ev] = await Promise.all([Api.get('/api/history', { ...p, limit: PAGE, offset: S.page * PAGE }), Api.get('/api/tips', { ...r, limit: 200 })]);
  const res = d.resolution, dm = S.cfg.mass_decimals, st = d.stats;
  $('#h-table').dataset.s = sensor; $('#h-unit').textContent = MU().l; $('#h-tunit').textContent = TU().l; $('#h-funit').textContent = S.cfg.flow_unit; $$('.h-mu').forEach(e => { e.textContent = MU().l; });
  const corCell = x => x.flow_state === 'ok' ? fnum(flowL(x.flow_lmin)) : '—';
  $('#h-body').innerHTML = d.rows.map(x => { const [lab, cls] = estado(x, sensor);
    return `<tr><td>${Fmt.dt(x.ts)}</td><td data-c="mass">${Fmt.num(massV(x.mass_g), dm)}</td><td data-c="temp">${Fmt.num(tempV(x.temp_c), S.cfg.temp_decimals)}</td><td data-c="cor">${Fmt.num(x.cor_ma, 3)}</td><td data-c="cor">${Fmt.num(x.flow_pulses, 0)}</td><td data-c="cor">${corCell(x)}</td><td data-c="cor">${MSHORT[x.flow_mode] || '—'}</td><td data-c="tips">${x.tips_total}</td><td data-c="tips">${res ? Fmt.num(x.tips_total * res, Trials.dec(res)) : '—'}</td><td class="${cls}">${lab}</td></tr>`; }).join('')
    || '<tr><td colspan="10" class="lbl">Nenhuma medição neste período e filtro.</td></tr>';
  const av = (s, conv, dec) => s && s.avg != null ? Fmt.num(conv(s.avg), dec) : '—', cf = st.cor.flow;
  $('#h-foot').innerHTML = `<td>Média do período</td><td data-c="mass">${av(st.mass, MU().to, dm)}</td><td data-c="temp">${av(st.temp, TU().to, S.cfg.temp_decimals)}</td><td data-c="cor">${av(st.cor.ma, v => v, 3)}</td><td data-c="cor">${st.cor.pulses ? Fmt.num(st.cor.pulses.avg_hz, 1) + ' Hz' : '—'}</td><td data-c="cor">${cf && flowL(cf.avg) != null ? av(cf, flowL, S.cfg.flow_decimals) : '—'}</td><td data-c="cor">${st.cor.mixed ? 'misto' : MSHORT[st.cor.mode] || '—'}</td><td data-c="tips">—</td><td data-c="tips">—</td><td class="lbl">Leituras válidas: massa ${st.mass.n.toLocaleString('pt-BR')}, temperatura ${st.temp.n.toLocaleString('pt-BR')}, medidor de vazão ${(st.cor.ma.n + (st.cor.pulses ? st.cor.pulses.n : 0)).toLocaleString('pt-BR')}</td>`;
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
  $('#tr-hist').innerHTML = h.map(t => { const [lab, cls] = Trials.STATE[t.state] || [t.state, '']; return `<tr><td>${Fmt.dt(t.start_ts)}</td><td>${Trials.KIND[t.kind] || t.kind}</td><td>${t.kind === 'flow' ? (t.standard_tag ? `<b>${esc(t.standard_tag)}</b>` : '<span class="lbl">sem padrão</span>') : '—'}</td><td class="${cls}">${lab}</td><td>${Trials.dur(t.end_ts - t.start_ts)} de ${Trials.dur(t.duration_cfg_ms != null ? t.duration_cfg_ms : t.duration_cfg_s * 1000)}</td><td>${esc(t.reason || '')}</td><td><button class="btn" data-id="${t.id}">Ver</button></td></tr>`; }).join('')
    || '<tr><td colspan="7" class="lbl">Nenhum ensaio realizado.</td></tr>';
  $$('#tr-hist button').forEach(b => b.onclick = async () => {
    const t = await Api.get('/api/trials/' + b.dataset.id), el = $('#tr-detail'); el.hidden = false;
    el.innerHTML = Trials.detail(t, S.cfg) + Trials.links(t.id);
    $('#tr-close').onclick = () => { el.hidden = true; };
  });
}
async function trialToggle() {
  const run = Trials.st.running, msg = $('#bal-msg'), done = $('#bal-go').dataset.done;
  msg.textContent = '';
  if (!run && done) { S.seen = done; store.set('elus.seen', done); S.corDetKey = null; renderBal(); renderPluv(); FlowUI.renderCard(); return; }   // fecha o resultado: o ensaio continua no Histórico
  try {
    if (run) { if (!confirm('Encerrar o ensaio agora? Ele ficará registrado como interrompido.')) return; await Api.post('/api/trials/stop'); }
    else {
      if (S.durP && !(await S.durP)) return;   // duração digitada: espera o salvamento terminar antes de iniciar
      if (durMsTyped() !== S.cfg.trial_duration_ms && !(await saveDuration())) return;
      await Api.post('/api/trials/start', { kind: S.method === 'comp' ? 'flow' : 'pluv' });
    }
    await loadTrials();
  } catch (e) { msg.textContent = e.message; await loadTrials().catch(() => {}); }
}

// ---------- configurações (atualização parcial: só os campos deste formulário vão ao servidor) ----------
const num = s => { s = String(s).trim().replace(',', '.'); return s === '' ? null : Number(s); };
// Duração do ensaio: o valor vai ao servidor em ms (inteiro), com a unidade escolhida; o mínimo é um Scan do datalogger.
async function saveDuration(unitOnly) {
  const el = $('#bal-dur'), u = $('#bal-dur-u').value, msg = $('#bal-msg'), ms = unitOnly ? S.cfg.trial_duration_ms : durMsTyped(), min = S.cfg.duration_min_ms || S.cfg.scan_ms || 1000;
  const back = () => { el.value = durShow(S.cfg.trial_duration_ms, u); };
  if (!unitOnly && (ms == null || ms < min || ms > 6 * 3600 * 1000)) { msg.textContent = `Duração: de ${Trials.dur(min)} (um Scan do datalogger) a 6 h.`; back(); return false; }
  try { S.cfg = await Api.post('/api/config', { trial_duration_ms: ms, trial_duration_unit: u }); msg.textContent = ''; back(); return true; }
  catch (e) { msg.textContent = 'Não foi possível salvar a duração: ' + e.message; back(); return false; }
}
function fillConfig() {
  const c = S.cfg, f = v => v == null ? '' : String(v).replace('.', ',');
  $('#cf-vmode').value = S.vmode;
  $('#cf-tres').value = String(c.time_resolution_ms || 100);
  const eff = c.timing_res_ms || c.scan_ms || 1000, sel = c.time_resolution_ms || 100;   // efetiva = a do programa do datalogger; nunca a escolhida sozinha
  $('#cf-tres-eff').textContent = eff > sel
    ? `Resolução efetiva do datalogger hoje: ${Trials.dur(eff)} (${eff === 1000 ? 'programa com Scan de 1 s, sem carimbos do Timer' : 'Scan rápido do programa'}). O tempo será exibido e registrado com essa resolução; a escolhida passa a valer quando o programa a fornecer.`
    : `Resolução efetiva do datalogger: ${Trials.dur(eff)}. O tempo é registrado com os carimbos do Timer do datalogger e exibido com ${Trials.durDec(sel)} casa(s) decimal(is).`;
  $('#cf-unit').value = c.mass_unit; $('#cf-tunit').value = c.temp_unit; $('#cf-funit').value = c.flow_unit;
  $('#cf-md').value = c.mass_decimals; $('#cf-td').value = c.temp_decimals; $('#cf-fd').value = c.flow_decimals;
  $('#cf-res').value = f(c.tip_resolution_mm); $('#cf-dens').value = f(c.density_g_cm3); $('#cf-area').value = f(c.catch_area_cm2);
  $('#cf-range').value = c.default_range_s;
  $('#cf-flow').hidden = !!S.link && S.link.flow_integrated === false;   // programa sem medidor de vazão: o card some
  FlowUI.renderSummary();
}
async function saveConfig() {
  try {
    S.cfg = await Api.post('/api/config', { mass_unit: $('#cf-unit').value, temp_unit: $('#cf-tunit').value, flow_unit: $('#cf-funit').value,
      mass_decimals: $('#cf-md').value, temp_decimals: $('#cf-td').value, flow_decimals: $('#cf-fd').value,
      tip_resolution_mm: $('#cf-res').value, density_g_cm3: $('#cf-dens').value, catch_area_cm2: $('#cf-area').value, default_range_s: $('#cf-range').value,
      time_resolution_ms: $('#cf-tres').value });
    S.vmode = $('#cf-vmode').value === 'flow' ? 'flow' : 'precip'; store.set('elus.vmode', S.vmode);   // preferência desta tela (não vai ao servidor)
    $('#cf-msg').textContent = 'Configurações salvas. Ensaios em andamento e já concluídos não mudam.';
    onConfigChanged();
  } catch (e) { $('#cf-msg').textContent = 'Não foi possível salvar: ' + e.message; }
}
// configuração nova (desta aba, do painel do medidor ou de outra aba via Socket.IO): tudo que depende dela é redesenhado
function onConfigChanged() {
  fillConfig(); S.detKey = S.plDetKey = S.corDetKey = null;   // painéis de detalhes são reconstruídos com as unidades novas
  FlowUI.setStatus(); Standards.renderHero(); renderLatest(); refreshSummary();
  if (view() === 'graficos') refreshCharts();
}

// ---------- método, visualização, período e navegação ----------
// Card principal (azul) conforme o método: gravimétrico = balança; comparativo = medidor de vazão, com o pluviômetro ao lado e a balança oculta
// (a referência da balança aparece dentro do card do medidor). Só classes e a posição dos controles mudam: nada é reconsultado.
function applyMethod() {
  const comp = S.method === 'comp', was = document.body.dataset.method, hero = comp ? $('#c-cor') : $('#c-mass');
  document.body.dataset.method = comp ? 'comp' : 'grav';
  $$('#meth .seg button').forEach(b => { const on = b.dataset.m === S.method; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  $('#c-cor').hidden = $('#g-cor').hidden = !comp; $('#c-mass').hidden = comp;
  $('#c-cor').classList.toggle('hero', comp); $('#c-mass').classList.toggle('hero', !comp);
  if ($('#trial-ctl').parentElement !== hero) hero.appendChild($('#trial-ctl'));
  if (was && was !== document.body.dataset.method && !reducedMotion()) { hero.classList.remove('swap'); void hero.offsetWidth; hero.classList.add('swap'); $('#c-pluv').classList.add('swap'); setTimeout(() => $$('.card.swap').forEach(c => c.classList.remove('swap')), 400); }
  renderBal(); FlowUI.renderMethod(); FlowUI.renderCard();
  requestAnimationFrame(() => FlowUI.thumb());
  Object.values(Charts.c).forEach(c => c.resize());
}
function setChips() {
  $$('.chip').forEach(b => { const on = b.dataset.r === S.range.key; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  $('#custom').hidden = S.range.key !== 'custom';
  if (S.range.key === 'custom') { const r = getRange(); $('#c-from').value = Fmt.local(r.from); $('#c-to').value = Fmt.local(r.to); }
}
function setRange(r) { S.range = r; S.page = 0; setChips(); refreshAll(); }
function refreshAll() { const v = view(); if (v === 'dashboard') refreshSummary(); if (v === 'graficos') refreshCharts(); if (v === 'historico') loadHistory(); if (v === 'config') fillConfig(); if (v === 'padroes') Standards.load().catch(() => {}); }
function route() {
  const v = view();
  $$('.view').forEach(e => { e.hidden = e.id !== 'v-' + v; });
  $$('.nav button').forEach(b => { const on = b.dataset.v === v; b.classList.toggle('on', on); if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  $('#title').textContent = TITLES[v]; $('#ctrl').hidden = v === 'config' || v === 'padroes'; $('#meth').hidden = v === 'historico';
  refreshAll();
  if (v === 'dashboard') requestAnimationFrame(() => FlowUI.thumb());
}

$$('.nav button').forEach(b => b.onclick = () => go(b.dataset.v));
$$('#meth .seg button').forEach(b => b.onclick = () => { if (b.dataset.m === S.method) return; S.method = b.dataset.m; store.set('elus.method', S.method); applyMethod(); if (view() === 'graficos') refreshCharts(); });
$$('.chip').forEach(b => b.onclick = () => b.dataset.r === 'custom' ? setRange({ key: 'custom', from: Date.now() - 9e5, to: Date.now() }) : setRange({ key: b.dataset.r }));
$('#c-apply').onclick = () => { const f = new Date($('#c-from').value).getTime(), t = new Date($('#c-to').value).getTime(); if (f < t) setRange({ key: 'custom', from: f, to: t }); };
$('#f-sensor').onchange = $('#f-state').onchange = () => { S.page = 0; loadHistory(); };
$('#h-prev').onclick = () => { S.page--; loadHistory(); }; $('#h-next').onclick = () => { S.page++; loadHistory(); };
$('#cf-save').onclick = saveConfig;
$('#bal-go').onclick = trialToggle;
$('#bal-dur').onchange = () => { S.durP = saveDuration().finally(() => { S.durP = null; }); };
$('#bal-dur-u').onchange = () => { S.durP = saveDuration(true).finally(() => { S.durP = null; }); };   // troca de unidade: o valor é convertido, não alterado
$('#reset').onclick = async () => { if (confirm('Zerar a contagem de basculadas? O histórico de medições e os ensaios são mantidos.')) { try { await Api.post('/api/reset-count'); } catch (e) { alert('Não foi possível zerar: ' + e.message); return; } S.events = []; S.evIds = new Set(); S.lastTotal = null; drawEvents(); refreshSummary(); } };
// medidor de vazão: seletor do método e acessos ao painel de parâmetros
$$('#flow-method button').forEach(b => b.onclick = () => FlowUI.request(b.dataset.method));
const openFlow = (e, tab) => Drawer.open(tab || (FlowUI.st && FlowUI.st.requested === 'analog' ? 'analog' : 'pulse'), e.currentTarget);
$('#flow-gear').onclick = e => openFlow(e); $('#cf-flow-open').onclick = e => openFlow(e);
$('#cor-note').addEventListener('click', e => { const b = e.target.closest('[data-open-flow]'); if (b) Drawer.open(b.dataset.openFlow, b); });
Drawer.bind(); Standards.bindHero(); Standards.bindTab();
window.addEventListener('hashchange', () => { try { const h = location.hash.slice(1); if (h in TITLES && h !== current) { current = h; route(); } } catch (e) {} });

(async () => {
  S.cfg = await Api.get('/api/config');
  FlowUI.st = await Api.get('/api/flow').catch(() => null);
  fillConfig();
  S.range = { key: Object.keys(RANGES).find(k => RANGES[k] === S.cfg.default_range_s) || '15m' };
  setChips(); applyMethod();
  Standards.load().catch(() => Standards.renderHero());
  Api.connect({
    sample: onSample,
    conn: ok => { S.sock = ok; setPills(); if (ok) { loadTrials().catch(() => {}); loadEvents().catch(() => {}); Api.get('/api/flow').then(st => FlowUI.setStatus(st)).catch(() => {}); } },   // reconectou: ressincroniza
    trial: t => { const was = Trials.st.running; Trials.st = { ...Trials.st, running: t.running, last: t.last }; renderBal(); renderPluv(); FlowUI.renderCard(); Standards.renderHero(); if (was && !t.running) loadTrials(); },
    flow: st => FlowUI.setStatus(st),
    config: c => { if (JSON.stringify(c) !== JSON.stringify(S.cfg) && (!Drawer.isOpen() || !Drawer.dirty())) { S.cfg = c; onConfigChanged(); } },   // não atropela um formulário sendo editado
  });
  await loadEvents().catch(() => {}); await loadTrials().catch(() => {}); route();
  setInterval(() => { setPills(); renderBal(); renderPluv(); }, 1000);
  setInterval(() => {   // só atualiza o que está na tela, no ritmo do período escolhido
    if (document.hidden || !S.range) return;
    const v = view(), k = S.range.key, now = Date.now();
    if (v === 'dashboard' && now - S.lastSummary >= SUMMARY_EVERY[k] * 1000) refreshSummary();
    if (v === 'graficos' && CHART_RELOAD[k] && now - S.lastCharts >= CHART_RELOAD[k] * 1000) refreshCharts();
  }, 1000);
})();
