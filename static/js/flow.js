// Medidor de vazão na interface: card ao vivo, seletor Analógico/Pulso e painel de parâmetros (Método Comparativo).
// Regra de integridade: um método só aparece como ATIVO depois que o servidor calculou uma amostra do datalogger com ele.
// Antes disso a tela mostra "solicitado · aguardando", nunca o valor do método anterior como se fosse do novo.
const MLABEL = { analog: 'Analógico', pulse: 'Pulso' };
const MLONG = { analog: 'pelo canal 4–20 mA', pulse: 'por pulsos' };
const MA_FAULT = 3.6;
// espelho de calc.classify_ma só para PRÉ-VISUALIZAR no painel; o servidor é quem classifica as leituras
const classifyMa = (ma, tol) => ma == null ? 'invalid' : ma < MA_FAULT ? 'fault' : ma < 4 - tol ? 'under' : ma < 4 ? 'low' : ma <= 20 ? 'ok' : ma <= 20 + tol ? 'high' : 'over';
const CLASS_TXT = { invalid: 'sem leitura', fault: 'falha do sinal', under: 'abaixo da faixa', over: 'acima da faixa', low: 'no limite de 4 mA', high: 'no limite de 20 mA', ok: 'na faixa' };
const dtdd = (k, v, cls = '') => `<dt>${k}</dt><dd${cls ? ` class="${cls}"` : ''}>${v}</dd>`;
const fmtIn = v => v == null ? '' : String(Number(Number(v).toPrecision(12))).replace('.', ',');

const FlowUI = {
  st: null,      // estado do servidor (/api/flow, evento 'flow' ou bloco 'flow' do /api/summary)
  busy: null,    // método sendo solicitado agora
  msg: '',       // motivo da última recusa do servidor

  setStatus(st) {
    if (st) this.st = st;
    this.renderMethod(); this.renderCard(); this.renderSummary();
    if (Drawer.isOpen()) { Drawer.renderDiag(); Drawer.derive(); $('#fd-trial').hidden = !(this.st && this.st.locked); }
  },
  // a amostra ao vivo também diz o método confirmado (chega antes do evento 'flow' em alguns casos)
  fromSample(f) {
    if (!f || !this.st) return;
    const changed = this.st.active !== f.active || this.st.requested !== f.requested || this.st.locked !== f.locked;
    if (f.integrated && f.has) this.st.has = f.has;
    Object.assign(this.st, { requested: f.requested, active: f.active, confirmed: f.confirmed, locked: f.locked });
    if (changed) this.renderMethod();
  },

  // ---------- seletor Analógico | Pulso ----------
  renderMethod() {
    const st = this.st, box = $('#flow-method'), line = $('#flow-mstate');
    if (!st || !box) return;
    const has = st.has || [], integ = st.integrated, req = st.requested, act = st.active, locked = st.locked;
    const shown = this.busy || req, stale = isStale();
    box.classList.toggle('pending', !!integ && (!!this.busy || req !== act));
    box.classList.toggle('locked', !!locked);
    box.classList.toggle('none', !integ);
    $$('#flow-method button').forEach(b => {
      const m = b.dataset.method, avail = has.includes(m);
      b.setAttribute('aria-pressed', String(!!integ && m === shown));
      b.disabled = !integ || !!locked || !!this.busy || !has.length || (!avail && m !== req);
      b.classList.toggle('na', has.length > 0 && !avail);
      b.title = !integ ? 'O programa do datalogger não tem o medidor de vazão.'
        : locked ? 'O método fica fixo durante o ensaio.'
        : has.length && !avail ? (m === 'pulse' ? 'O programa carregado no datalogger não tem o canal de pulsos (P2). Carregue a versão v4 do programa.' : 'O programa carregado no datalogger não tem o canal 4–20 mA.')
        : `Calcular a vazão ${MLONG[m]}`;
    });
    this.thumb();
    let cls = '', txt, icon = '';
    if (!integ) txt = 'O programa do datalogger não tem o medidor de vazão';
    else if (this.busy) { cls = 'pending'; txt = `Solicitando o método ${MLABEL[this.busy].toLowerCase()}…`; }
    else if (this.msg) { cls = 'err'; txt = this.msg; }
    else if (locked) { cls = 'lock'; icon = 'i-lock'; txt = `Método fixo durante o ensaio: ${MLABEL[act || req]}`; }
    else if (!has.length) { cls = 'pending'; txt = 'Aguardando o datalogger informar os canais disponíveis'; }
    else if (req !== act && !has.includes(req)) { cls = 'err'; txt = `${MLABEL[req]} indisponível no programa carregado`; }
    else if (req !== act) {
      cls = stale ? 'err' : 'pending';
      txt = stale ? `${MLABEL[req]} solicitado · sem dados do datalogger para confirmar` : `${MLABEL[req]} solicitado · aguardando a primeira leitura calculada com ele`;
    } else { cls = 'ok'; txt = `${MLABEL[act]} ativo · confirmado por dado do datalogger${st.confirmed_at ? ' às ' + Fmt.time(st.confirmed_at) : ''}`; }
    line.className = 'mstate ' + cls;
    setHtml(line, (icon ? `<svg class="ic" aria-hidden="true"><use href="#${icon}"/></svg>` : '<i class="dot" aria-hidden="true"></i>') + `<span>${esc(txt)}</span>`);
  },
  thumb() {
    const box = $('#flow-method'), t = box && box.querySelector('.thumb'), on = box && box.querySelector('button[aria-pressed=true]');
    if (!t) return;
    if (!on || !box.offsetParent) { t.style.width = '0px'; return; }
    t.style.width = on.offsetWidth + 'px';
    t.style.transform = `translateX(${on.offsetLeft}px)`;
  },
  async request(m) {
    if (!this.st || this.busy || m === this.st.requested) return;
    this.busy = m; this.msg = ''; this.renderMethod(); this.renderCard();
    try { this.st = await Api.post('/api/flow/method', { method: m }); }
    catch (e) { this.msg = String(e.message || e); if (e.data && e.data.flow) this.st = e.data.flow; setTimeout(() => { this.msg = ''; this.renderMethod(); }, 8000); }
    finally { this.busy = null; this.setStatus(); }
  },

  // ---------- card ----------
  renderCard() {
    const st = this.st, cfg = S.cfg;
    if (!cfg || !st) return;
    const s = S.latest, f = s && s.flow, fu = cfg.flow_unit;
    let val = '—', unit = fu, textual = false, note = '', pst = 'stale', sig = '', xc = null;
    if (!st.integrated) { val = 'Aguardando integração'; textual = true; unit = ''; pst = 'na'; }
    else if (isStale() || !f || !f.integrated) pst = 'stale';                        // leitura antiga não fica na tela como atual
    else if (this.busy || f.method !== st.requested) { pst = 'pending'; note = `Aguardando a primeira leitura ${MLONG[this.busy || st.requested]}.`; }
    else {
      pst = f.state; sig = this.signal(f); xc = this.cross(f);
      if (f.state === 'ok') {
        const v = flowL(f.lmin);
        if (v == null) note = esc(DENS_MSG); else val = fnum(v);
        if (f.clamp) note = `No limite de ${f.clamp === 'low' ? 4 : 20} mA: ${Fmt.num(f.ma, 3)} mA está dentro da tolerância de ${Fmt.num(cfg.flow_ma_tol, 3)} mA e foi tratado como ${f.clamp === 'low' ? 4 : 20} mA.`;
      } else {
        textual = true; unit = '';
        val = { unconfigured: 'Não configurado', out_of_range: 'Fora da faixa', fault: 'Falha do sinal', invalid: 'Leitura inválida', unavailable: 'Indisponível', no_comm: 'Sem comunicação' }[f.state] || 'Sem dados';
        note = esc(f.reason ? f.reason.charAt(0).toUpperCase() + f.reason.slice(1) + '.' : '');
        if (f.state === 'unconfigured') note += ` <button type="button" class="btn sm" data-open-flow="${f.method}">Configurar</button>`;
        if (f.state === 'fault') note += ' No modo “4–20 mA + alarme” o MAG 5000 sinaliza erro com 1,3, 2 ou 3 mA.';
      }
    }
    $('#cor-val').textContent = val; $('#cor-unit').textContent = unit;
    $('#cor-big').className = 'big sm' + (textual ? ' txt' : '');
    pill('#p-cor', pst);
    setHtml($('#cor-sig'), sig);
    setHtml($('#cor-note'), note);
    const x = $('#cor-x');
    x.hidden = !xc;
    if (xc) { x.className = 'xcheck' + (xc.warn ? ' warn' : ''); setHtml(x, `<svg class="ic" aria-hidden="true"><use href="#${xc.warn ? 'i-alert' : 'i-info'}"/></svg><span>${xc.html}</span>`); }
  },
  signal(f) {
    const p = [], c = S.cfg.cor;
    if (f.method === 'analog') {
      p.push(`<span>${f.ma == null ? '— mA' : Fmt.num(f.ma, 3) + ' mA'}</span>`);
      if (f.clamp) p.push(`<span class="flag">no limite de ${f.clamp === 'low' ? 4 : 20} mA</span>`);
      if (c.q4 != null && c.q20 != null) p.push(`<span>4–20 mA → ${Fmt.sig(c.q4)}–${Fmt.sig(c.q20)} ${esc(c.unit)}</span>`);
    } else {
      p.push(`<span>${f.pulses == null ? '—' : Fmt.int(f.pulses)} pulsos em ${Fmt.num(f.window_s, 2)} s</span>`);
      if (f.hz != null) p.push(`<span>= ${Fmt.num(f.hz, 1)} Hz</span>`);
      if (f.window_assumed) p.push('<span class="flag" title="Sem registro anterior contíguo: a janela de contagem foi considerada igual ao Scan nominal de 1 s.">janela presumida</span>');
      const r = flowL(f.resolution_lmin);
      if (r != null) p.push(`<span>±${Fmt.sig(r, 2)} ${esc(S.cfg.flow_unit)} por pulso</span>`);
    }
    return p.join('');
  },
  cross(f) {
    const x = f.crosscheck;
    if (!x) return null;
    if (x.suspect === 'no_pulses')
      return { warn: true, html: 'A corrente indica vazão, mas nenhum pulso chegou em P2 nas últimas leituras. Confira a ligação da saída digital, a saída de pulsos do MAG 5000 e o fator K.' };
    const other = f.method === 'pulse' ? 'analog' : 'pulse', o = f.channels && f.channels[other];
    if (!o || o.state !== 'ok' || o.lmin == null) return null;
    const v = flowL(o.lmin);
    return { warn: false, html: `Canal ${other === 'pulse' ? 'de pulsos' : 'analógico'}: ${fnum(v)} ${esc(S.cfg.flow_unit)}` +
      (x.diff_pct == null ? '' : ` · diferença pulsos − analógico: ${Fmt.num(x.diff_pct, 1)} %`) };
  },
  renderSummary() {
    const c = S.cfg, st = this.st, el = $('#cf-flow-sum');
    if (!c || !el) return;
    const K = c.flow_k_pulses_per_l == null ? 'não configurado' : `${Fmt.sig(c.flow_k_value, 6)} <i>${esc(c.flow_k_unit)}</i>`;
    const R = c.cor.q4 == null ? 'não configurada' : `${Fmt.sig(c.cor.q4)} → ${Fmt.sig(c.cor.q20)} <i>${esc(c.cor.unit)}</i>`;
    const M = !st ? '—' : !st.integrated ? 'sem medidor no programa' : MLABEL[st.requested] + (st.active === st.requested ? '' : ' (aguardando confirmação)');
    setHtml(el, Trials.kv('Método', M) + Trials.kv('Fator K', K) + Trials.kv('Faixa 4–20 mA', R) + Trials.kv('Tolerância nos limites', Fmt.num(c.flow_ma_tol, 3), 'mA'));
  },
};

// ---------- painel lateral de parâmetros ----------
const Drawer = {
  opener: null, tab: 'pulse', snap: null,
  isOpen() { return !$('#fd').hidden; },
  open(tab, opener) {
    const w = $('#fd');
    this.opener = opener || document.activeElement;
    this.fill();
    this.select(tab || this.tab, false);
    w.hidden = false;
    document.body.classList.add('dr-open');
    requestAnimationFrame(() => { w.classList.add('open'); this.ink(); });
    setTimeout(() => { const f = this.first(); (f || $('#tab-' + this.tab)).focus(); }, 40);
  },
  close(force) {
    if (!this.isOpen()) return;
    if (!force && this.dirty()) { $('#fd-discard').hidden = false; $('#fd-discard-no').focus(); return; }
    const w = $('#fd');
    w.classList.remove('open'); w.classList.add('closing');
    const done = () => {
      w.hidden = true; w.classList.remove('closing'); document.body.classList.remove('dr-open'); $('#fd-discard').hidden = true;
      if (this.opener && document.contains(this.opener)) this.opener.focus();
    };
    if (reducedMotion()) done(); else setTimeout(done, 200);
  },
  first() { const p = $(`#pan-${this.tab}`); return p && p.querySelector('input,select'); },
  fill() {
    const c = S.cfg;
    $('#fk-val').value = fmtIn(c.flow_k_value); $('#fk-unit').value = c.flow_k_unit;
    $('#fa-q4').value = fmtIn(c.cor.q4); $('#fa-q20').value = fmtIn(c.cor.q20); $('#fa-unit').value = c.cor.unit; $('#fa-tol').value = fmtIn(c.flow_ma_tol);
    $('#fd-funit').value = c.flow_unit; $('#fd-fdec').value = c.flow_decimals;
    ['#fk-val', '#fa-q4', '#fa-q20', '#fa-tol', '#fd-fdec'].forEach(s => $(s).removeAttribute('aria-invalid'));
    ['#fk-err', '#fa-err', '#fa-tol-err'].forEach(s => { $(s).hidden = true; $(s).textContent = ''; });
    $('#fd-msg').textContent = ''; $('#fd-discard').hidden = true;
    $('#fd-trial').hidden = !(FlowUI.st && FlowUI.st.locked);
    this.snap = this.values();
    this.derive(); this.renderDiag();
  },
  values() {
    return { k: $('#fk-val').value.trim(), ku: $('#fk-unit').value, q4: $('#fa-q4').value.trim(), q20: $('#fa-q20').value.trim(), cu: $('#fa-unit').value,
             tol: $('#fa-tol').value.trim(), fu: $('#fd-funit').value, fd: String($('#fd-fdec').value).trim() };
  },
  dirty() { return JSON.stringify(this.values()) !== JSON.stringify(this.snap); },
  select(tab, focus) {
    this.tab = tab;
    $$('#fd [role=tab]').forEach(b => { const on = b.id === 'tab-' + tab; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
    $$('#fd [role=tabpanel]').forEach(p => { p.hidden = p.id !== 'pan-' + tab; });
    $('#fd-disp').hidden = tab === 'diag';
    this.ink();
    if (focus) $('#tab-' + tab).focus();
  },
  ink() {
    const on = $(`#tab-${this.tab}`), ink = $('#fd .tab-ink');
    if (!on || !ink || !on.offsetParent) return;
    ink.style.width = on.offsetWidth + 'px'; ink.style.transform = `translateX(${on.offsetLeft}px)`;
  },
  err(input, box, msg) {
    if (input) input.setAttribute('aria-invalid', msg ? 'true' : 'false');
    const b = $(box);
    b.hidden = !msg;
    b.innerHTML = msg ? `<svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>${esc(msg)}` : '';
    return msg ? input : null;
  },
  // valida um campo (ao sair dele) ou todos (ao salvar); devolve o primeiro campo inválido
  validate(which = 'all') {
    let bad = null;
    const pick = x => { bad = bad || x; };
    if (which === 'all' || which === 'k') {
      const v = parseNum($('#fk-val').value);
      pick(this.err($('#fk-val'), '#fk-err', v === null ? '' : !isFinite(v) ? 'Use só números no fator K (ex.: 1000 ou 2,5).' : v <= 0 ? 'O fator K precisa ser maior que zero. Vazio = não configurado.' : ''));
    }
    if (which === 'all' || which === 'range') {
      const a = parseNum($('#fa-q4').value), b = parseNum($('#fa-q20').value);
      const m = (a === null) !== (b === null) ? 'Informe a vazão em 4 mA e em 20 mA, ou deixe as duas vazias.'
        : a !== null && (!isFinite(a) || !isFinite(b)) ? 'Use só números nas vazões da faixa.'
        : a !== null && a === b ? 'A vazão em 20 mA precisa ser diferente da vazão em 4 mA.' : '';
      $('#fa-q20').setAttribute('aria-invalid', m ? 'true' : 'false');
      pick(this.err($('#fa-q4'), '#fa-err', m));
    }
    if (which === 'all' || which === 'tol') {
      const t = parseNum($('#fa-tol').value);
      pick(this.err($('#fa-tol'), '#fa-tol-err', t === null || !isFinite(t) || t < 0 || t > 0.2 ? 'Use um valor de 0 a 0,2 mA.' : ''));
    }
    if (which === 'all') {
      const d = Number($('#fd-fdec').value), ok = Number.isInteger(d) && d >= 0 && d <= 6;
      $('#fd-fdec').setAttribute('aria-invalid', String(!ok));
      if (!ok) { pick($('#fd-fdec')); $('#fd-msg').textContent = 'Casas decimais da vazão: use um inteiro de 0 a 6.'; }
    }
    return bad;
  },
  // pré-visualização com os valores DIGITADOS (ainda não salvos): equivalências, resolução e leitura atual
  derive() {
    const c = S.cfg, s = S.latest, ch = (s && s.flow && s.flow.channels) || {}, fu = $('#fd-funit').value || c.flow_unit;
    const conv = v => v == null ? null : Flow.convert(v, 'L/min', fu, c.density_g_cm3);
    const n = (v, d) => v == null ? '—' : Fmt.num(v, d);
    const kv = parseNum($('#fk-val').value), kl = KUnits.toL(kv, $('#fk-unit').value);
    let h = '';
    if (kl) {
      const vol = 1 / kl;
      h += dtdd('Em pulsos por litro', `${Fmt.sig(kl, 6)} pulsos/L`) + dtdd('Volume de 1 pulso', vol < 1 ? `${Fmt.sig(vol * 1000, 4)} mL` : `${Fmt.sig(vol, 4)} L`);
      h += dtdd('Degrau da leitura instantânea (janela de 1 s)', `±${Fmt.sig(conv(60 / kl), 3)} ${esc(fu)}`);
      const p = ch.pulse;
      if (p && p.hz != null) h += dtdd(`Com este K, os ${n(p.hz, 1)} Hz atuais dão`, `${Fmt.sig(conv(p.hz / kl * 60), 4)} ${esc(fu)}`);
      const a = ch.analog, qa = a && a.state === 'ok' ? a.lmin : null;
      if (qa != null && qa > 0) {
        const hz = qa / 60 * kl, np = hz * c.trial_duration_s;
        h += dtdd(`Canal analógico agora (${Fmt.sig(conv(qa), 4)} ${esc(fu)}): pulsos esperados`, `${n(hz, 1)} Hz`, hz > 10000 ? 'warn' : '');
        h += dtdd(`Pulsos num ensaio de ${c.trial_duration_s} s`, `${Fmt.int(np)} · 1 pulso = ${Fmt.sig(100 / np, 2)} %`, np < 200 ? 'warn' : '');
        if (hz > 10000) h += dtdd('Atenção', 'acima de 10 kHz, o máximo da saída do MAG 5000', 'warn');
      }
    } else if (kv === null) h = dtdd('Fator K', 'não configurado: a vazão por pulsos fica indisponível');
    setHtml($('#fk-derived'), h);
    const a = parseNum($('#fa-q4').value), b = parseNum($('#fa-q20').value), cu = $('#fa-unit').value, tol = parseNum($('#fa-tol').value);
    let g = '';
    if (a !== null && b !== null && isFinite(a) && isFinite(b) && a !== b) {
      const t = tol !== null && isFinite(tol) && tol >= 0 && tol <= 0.2 ? tol : c.flow_ma_tol;
      g += dtdd('Sensibilidade', `${Fmt.sig((b - a) / 16, 4)} ${esc(cu)} por mA`) + dtdd('Faixa aceita', `${Fmt.num(4 - t, 3)} a ${Fmt.num(20 + t, 3)} mA`);
      const an = ch.analog;
      if (an && an.ma != null) {
        const cls = classifyMa(an.ma, t), eff = cls === 'low' ? 4 : cls === 'high' ? 20 : cls === 'ok' ? an.ma : null;
        g += dtdd(`Agora: ${Fmt.num(an.ma, 3)} mA (${CLASS_TXT[cls]})`, eff == null ? 'sem vazão' : `${Fmt.sig(a + (eff - 4) / 16 * (b - a), 5)} ${esc(cu)}`, eff == null ? 'warn' : '');
      }
    }
    setHtml($('#fa-derived'), g);
  },
  renderDiag() {
    const st = FlowUI.st || {}, s = S.latest, f = s && s.flow, ch = (f && f.channels) || {}, has = st.has || [];
    const chTxt = has.length ? has.map(h => h === 'analog' ? '4–20 mA (RG1)' : 'pulsos (P2)').join(' + ') + (has.includes('pulse') ? '' : ' · programa v3') : 'aguardando leitura';
    const an = ch.analog, pu = ch.pulse;
    let h = dtdd('Canais no programa do datalogger', chTxt) + dtdd('Método solicitado', st.requested ? MLABEL[st.requested] : '—')
      + dtdd('Método ativo (confirmado)', st.active ? MLABEL[st.active] : 'nenhum, aguardando dado') + dtdd('Confirmado em', st.confirmed_at ? Fmt.dt(st.confirmed_at) : '—')
      + dtdd('Corrente no último registro', an ? `${an.ma == null ? '—' : Fmt.num(an.ma, 3) + ' mA'} · ${CLASS_TXT[an.ma_class] || an.state}` : '—')
      + dtdd('Pulsos no último registro', pu ? (pu.pulses == null ? (pu.reason || '—') : `${Fmt.int(pu.pulses)} em ${Fmt.num(pu.window_s, 2)} s${pu.window_assumed ? ' (presumida)' : ''}`) : '—')
      + dtdd('Contador acumulado do datalogger', s && s.pulses_total != null ? Fmt.int(s.pulses_total) : '—')
      + dtdd('Diferença pulsos − analógico', f && f.crosscheck && f.crosscheck.diff_pct != null ? Fmt.num(f.crosscheck.diff_pct, 2) + ' %' : '—')
      + dtdd('Ensaio em andamento', st.locked ? 'sim: método fixo' : 'não');
    setHtml($('#fd-diag'), h);
  },
  async save(e) {
    e.preventDefault();
    $('#fd-msg').textContent = '';
    const bad = this.validate('all');
    if (bad) { const p = bad.closest('[role=tabpanel]'); if (p && p.hidden) this.select(p.id.slice(4), false); bad.focus(); return; }
    const v = this.values(), btn = $('#fd-save');
    btn.disabled = true;
    try {
      S.cfg = await Api.post('/api/config', { flow_k: { value: v.k, unit: v.ku }, cor: { q4: v.q4, q20: v.q20, unit: v.cu }, flow_ma_tol: v.tol,
                                              flow_unit: v.fu, flow_decimals: v.fd });
      FlowUI.st = await Api.get('/api/flow').catch(() => FlowUI.st);
      this.fill();
      $('#fd-msg').textContent = `Parâmetros salvos às ${Fmt.time(Date.now())}. Ensaios em andamento e já concluídos não mudam.`;
      onConfigChanged();
    } catch (err) { $('#fd-msg').textContent = 'Não foi possível salvar: ' + (err.message || err); }
    finally { btn.disabled = false; }
  },
  keydown(e) {
    if (e.key === 'Escape') { e.preventDefault(); if (!$('#fd-discard').hidden) $('#fd-discard').hidden = true; else this.close(); return; }
    if (e.key !== 'Tab') return;
    const f = $$('#fd .drawer button:not([disabled]), #fd .drawer input, #fd .drawer select, #fd .drawer [tabindex="0"]').filter(x => x.offsetParent);
    if (!f.length) return;
    if (!$('#fd .drawer').contains(document.activeElement)) { e.preventDefault(); f[0].focus(); return; }   // foco nunca sai do painel aberto
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  },
  bind() {
    document.addEventListener('keydown', e => { if (this.isOpen()) this.keydown(e); });   // Esc e Tab valem mesmo com o foco fora do painel
    $$('#fd [data-close]').forEach(b => b.addEventListener('click', () => this.close()));
    $('#fd-discard-yes').onclick = () => this.close(true);
    $('#fd-discard-no').onclick = () => { $('#fd-discard').hidden = true; (this.first() || $('#tab-' + this.tab)).focus(); };
    $('#fd-form').addEventListener('submit', e => this.save(e));
    $$('#fd [role=tab]').forEach(b => b.addEventListener('click', () => this.select(b.id.slice(4), false)));
    $('#fd .tabs').addEventListener('keydown', e => {
      const tabs = ['pulse', 'analog', 'diag'], i = tabs.indexOf(this.tab);
      const j = { ArrowRight: (i + 1) % 3, ArrowLeft: (i + 2) % 3, Home: 0, End: 2 }[e.key];
      if (j !== undefined) { e.preventDefault(); this.select(tabs[j], true); }
    });
    $('#fk-val').addEventListener('blur', () => this.validate('k'));
    ['#fa-q4', '#fa-q20'].forEach(s => $(s).addEventListener('blur', () => this.validate('range')));
    $('#fa-tol').addEventListener('blur', () => this.validate('tol'));
    $('#fd-form').addEventListener('input', () => { $('#fd-msg').textContent = ''; this.derive(); });
    $('#fd-form').addEventListener('change', () => this.derive());
    window.addEventListener('resize', () => { this.ink(); FlowUI.thumb(); });
  },
};
