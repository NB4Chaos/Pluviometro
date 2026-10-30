// Apresentação dos ensaios de calibração. O ESTADO vem sempre do servidor (nada aqui decide se um ensaio está em andamento).
// Distinções visuais: "parcial" (ensaio em andamento) · "congelado" (ensaio encerrado) · "ref." (valor de referência da balança)
// · sem etiqueta = medido pelo instrumento.
const Trials = {
  st: { running: null, last: null, history: [] },
  STATE: { running: ['Em andamento', 'warn'], completed: ['Concluído', 'ok'], incomplete: ['Incompleto', 'warn'], interrupted: ['Interrompido', 'err'] },
  KIND: { flow: 'Medidor de Vazão', pluv: 'Pluviômetro (gravimétrico)' },
  mmss: s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; },
  // duração em ms: "850 ms", "12,5 s", "1:30" (mm:ss) ou "1:30,5" quando não é inteira; nunca arredonda o que foi configurado
  dur(ms) {
    if (ms == null || isNaN(ms)) return '—';
    ms = Math.max(0, Math.round(ms));
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${Fmt.any(ms / 1000)} s`;
    const m = Math.floor(ms / 60000), s = (ms - m * 60000) / 1000, whole = Number.isInteger(s);
    return `${m}:${whole ? String(s).padStart(2, '0') : (s < 10 ? '0' : '') + Fmt.any(s)}`;
  },
  // casas decimais do tempo (s) para uma resolução em ms: 1000 → 0 · 100 → 1 · 10 → 2 · 1 → 3. Nunca mais casas que a resolução EFETIVA.
  durDec: resMs => resMs >= 1000 ? 0 : resMs >= 100 ? 1 : resMs >= 10 ? 2 : 3,
  durRes(ms, resMs) {
    if (ms == null || isNaN(ms)) return '—';
    const d = this.durDec(resMs || 1000), s = ms / 1000;
    if (s < 60) return `${s.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d })} s`;
    const m = Math.floor(s / 60), r = s - m * 60;
    return `${m}:${(r < 10 ? '0' : '') + r.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  },
  dec: res => { if (!res) return 3; const t = String(res), i = t.indexOf('.'); return Math.min(3, Math.max(1, i < 0 ? 0 : t.length - i - 1)); },
  kv(l, v, u = '', tag = '') { return `<div class="rk"><span>${l}${tag ? ` <em class="t-${tag[0]}">${tag[1]}</em>` : ''}</span><b>${v}${u && v !== '—' ? ` <i>${u}</i>` : ''}</b></div>`; },
  fl(v, cfg) { return v == null ? null : Flow.convert(v, 'L/min', cfg.flow_unit, cfg.density_g_cm3); },
  cfgMs: t => t.duration_cfg_ms != null ? t.duration_cfg_ms : t.duration_cfg_s * 1000,
  // ensaio em andamento: tempo decorrido/restante (relógio do servidor) e tempo efetivo coberto por registros do datalogger
  timeRows(t, part) {
    const tm = part && part.timing, cfg = this.cfgMs(t), f = part && part.flow, res = tm ? tm.display_res_ms : 1000;
    const eff = f && f.time_eff_ms != null ? f.time_eff_ms : tm && tm.eff_ms;
    return this.kv('Tempo decorrido', this.dur(t.elapsed_s * 1000)) + this.kv('Tempo restante', `${this.dur(t.remaining_s * 1000)} de ${this.dur(cfg)}`)
      + (tm ? this.kv(`Tempo efetivo (${tm.res_source === 'timer' ? 'Timer do datalogger' : 'registros'})`, eff == null ? '—' : this.durRes(eff, res), '', ['p', 'parcial']) : '');
  },
  standardHtml(s) {
    if (!s) return '';
    const K = this.kv.bind(this), id = [s.brand, s.model].filter(Boolean).map(esc).join(' | ');
    return `<p class="lbl sec">Padrão</p><div class="rg">${K('TAG', `<b>${esc(s.tag)}</b>`)}${id ? K('Marca | modelo', id) : ''}${s.sn ? K('Número de série', esc(s.sn)) : ''}${K('Aquisição', s.acq === 'pulse' ? 'Pulsos' : 'Corrente 4–20 mA')}</div>`;
  },
  bar(sel, x) {
    const el = $(sel); if (!el) return;
    el.hidden = !(x && x.run);
    if (!el.hidden) el.firstElementChild.style.width = Math.min(100, 100 * x.t.elapsed_s * 1000 / this.cfgMs(x.t)) + '%';
  },
  links: id => `<p class="grp"><a class="btn" href="/relatorio/${id}" target="_blank">Relatório (imprimir / PDF)</a><a class="btn" href="/api/trials/${id}/raw.csv">Amostras (CSV)</a><a class="btn" href="/api/trials/${id}/tips.csv">Basculadas (CSV)</a></p>`,
  kText: c => c.k_pulses_per_l == null ? 'não configurado' : `${Fmt.sig(c.k_pulses_per_l, 6)} pulsos/L`,

  // temporização do ensaio: carimbos do datalogger, configurado × efetivo, resolução (= Scan)
  // Temporização enxuta: o que o laboratório precisa levar para a planilha. kind 'flow' mostra o tempo dos pulsos (Timer) quando existe.
  timingHtml(res, kind) {
    const t = res && res.timing; if (!t) return '';
    const K = this.kv.bind(this), R = t.display_res_ms || t.resolution_ms || 1000, stamp = t.resolution_ms < 1000 ? Fmt.dtms : Fmt.dt, dr = ms => this.durRes(ms, R);
    // a janela começa 1 ms depois do último registro anterior ao ensaio: a borda real do datalogger é esse registro (sem o ",001" artificial)
    let h = K('Início (datalogger)', stamp(t.start_ts - 1)) + K('Fim', stamp(t.end_ts - 1)) + K('Duração configurada', this.dur(t.cfg_ms));
    if (kind === 'flow' && t.pulse_eff_ms != null) h += K('Tempo efetivo dos pulsos (1º → último, Timer)', dr(t.pulse_eff_ms), '', ['f', 'medido']) + K('Início dos pulsos', Fmt.dtms(t.first_pulse_ts)) + K('Fim dos pulsos', Fmt.dtms(t.last_pulse_ts));
    else h += K('Tempo efetivo (registros do datalogger)', t.eff_ms == null ? '—' : dr(t.eff_ms), '', ['f', 'medido']);
    h += K('Resolução efetiva', `${this.dur(t.resolution_ms)}${t.res_source === 'timer' ? ' (Timer, Scan rápido)' : ' (Scan do programa)'}`, '', t.requested_res_ms && t.requested_res_ms < t.resolution_ms ? ['p', `pedida ${this.dur(t.requested_res_ms)}`] : '')
      + K('Registros', t.samples);
    return `<p class="lbl sec">Tempo</p><div class="rg">${h}</div>`;
  },
  cfgText(c) {
    const p = [];   // chaves do snapshot congelado pelo servidor (trials.start)
    if (c.duration_ms != null || c.duration_s != null) p.push(`duração = ${this.dur(c.duration_ms != null ? c.duration_ms : c.duration_s * 1000)}`);
    if (c.scan_ms != null) p.push(`Scan = ${c.scan_ms} ms`);
    if (c.density != null) p.push(`ρ = ${Fmt.num(c.density, 4)} g/cm³`);
    if (c.area_cm2 != null) p.push(`A = ${Fmt.num(c.area_cm2, 1)} cm²`);
    if (c.res_mm != null) p.push(`resolução = ${Fmt.any(c.res_mm)} mm/basculada`);
    if (c.standard) p.push(`padrão = ${c.standard.tag}`);
    if (c.flow_method) p.push(`método = ${c.flow_method === 'pulse' ? 'pulsos' : 'analógico'}`);
    if (c.k_input != null) p.push(`K = ${Fmt.sig(c.k_input, 6)} ${c.k_unit || 'pulsos/L'}`); else if ('k_pulses_per_l' in c) p.push(`K = ${this.kText(c)}`);
    if (c.time_res_ms) p.push(`resolução de tempo pedida = ${this.dur(c.time_res_ms)}`);
    if (c.q4 != null && c.q20 != null) p.push(`4–20 mA = ${Fmt.sig(c.q4)}–${Fmt.sig(c.q20)} ${c.range_unit || ''}`);
    if (c.ma_tol != null) p.push(`tolerância = ${Fmt.num(c.ma_tol, 3)} mA`);
    return p.length ? p.join(' · ') : JSON.stringify(c);
  },

  // Detalhes do medidor no método Comparativo: só o que o padrão adquiriu e o que foi calculado dele. Nada da balança aqui.
  flowHtml(res, cfg, part) {
    const f = res.flow, K = this.kv.bind(this), n = Fmt.num, dm = cfg.flow_decimals, p = part ? ['p', 'parcial'] : '', C = ['c', 'calculado'];
    if (!f) return '<p class="note">O programa do datalogger não fornece o medidor de vazão.</p>';
    const q = f.flow_l_min, fu = cfg.flow_unit, c = v => this.fl(v, cfg), R = res.timing ? res.timing.display_res_ms : 1000, mass = f.k_basis === 'mass';
    let h = this.standardHtml(f.standard) + '<p class="lbl sec">Medidor</p><div class="rg">';
    h += K('Aquisição', { pulse: 'Pulsos', analog: 'Corrente 4–20 mA', misto: 'Mista (o método mudou)' }[f.mode] || f.mode);
    if (f.mode === 'pulse') {   // o que foi adquirido vem antes do que foi calculado
      h += K('Pulsos acumulados (N)', f.pulses_total == null ? '—' : f.pulses_total.toLocaleString('pt-BR'), '', p)
        + K('Tempo efetivo (Δt)', f.time_eff_ms == null ? '—' : this.durRes(f.time_eff_ms, R), '', p) + K('Frequência média (N ÷ Δt)', n(f.freq_mean_hz, 2), 'Hz', p || C)
        + K('Fator K', f.k_input != null ? Fmt.sig(f.k_input, 6) : f.k_pulses_per_l ? Fmt.sig(f.k_pulses_per_l, 6) : 'não configurado', f.k_input != null ? f.k_unit : f.k_pulses_per_l ? 'pulsos/L' : '', ['f', 'configurado']);
      if (mass) h += K('Massa calculada (N ÷ K)', n(f.mass_kg, 4), 'kg', p || C) + K('Vazão mássica (massa ÷ Δt)', n(f.mass_flow_kg_min, 4), 'kg/min', p || C);
      if (f.count_method === 'soma') h += K('Contagem', 'soma dos registros (contador do datalogger reiniciou)');
    } else {
      if (f.ma) h += K('Corrente média', n(f.ma.mean, 3), 'mA', p) + K('Corrente mín / máx', `${n(f.ma.min, 3)} / ${n(f.ma.max, 3)}`, 'mA');
      if (f.n_clamped) h += K('Leituras no limite (4 ou 20 mA)', f.n_clamped);
    }
    const vt = mass ? ['c', 'convertido (ρ)'] : (p || C);
    h += K(f.mode === 'pulse' ? (mass ? 'Volume (massa ÷ ρ)' : 'Volume (N ÷ K)') : 'Volume (∫ vazão)', n(f.volume_l, 3), 'L', vt)
      + K('Vazão média', n(c(q && q.mean), dm), fu, vt) + K('Vazão mín / máx', q ? `${n(c(q.min), dm)} / ${n(c(q.max), dm)}` : '—', fu, vt)
      + K('Leituras válidas', f.n_rows ? `${f.n_valid}/${f.n_rows} (${n(100 * f.valid_fraction, 0)} %)` : '—');
    return h + '</div>' + (f.issues || []).map(i => `<p class="note err">${esc(i)}</p>`).join('');
  },

  // Blocos separados por instrumento. `which`: 'bal' (balança + comparação), 'pluv' (pluviômetro) ou 'all' (histórico/relatório).
  pluvHtml(res, cfg, part, which = 'all') {
    const g = res.gravimetric, K = this.kv.bind(this), n = Fmt.num, p = part ? ['p', 'parcial'] : '', rd = this.dec(g.resolution_mm);
    const sec = (t, h) => `<p class="lbl sec">${t}</p><div class="rg">${h}</div>`;
    const bal = K('Massa inicial → final', g.mass_start_g == null ? '—' : `${n(g.mass_start_g, 1)} → ${n(g.mass_end_g, 1)}`, 'g')
      + K('Massa de água coletada (Δm)', n(g.delta_mass_g, 1), 'g', p) + K('Volume (Δm ÷ ρ)', n(g.volume_ml, 1), 'mL', p)
      + K('Precipitação equivalente', n(g.precip_ref_mm, 2), 'mm', p) + K('Intensidade equivalente', n(g.intensity_ref_mm_h, 1), 'mm/h', p)
      + K('Vazão equivalente', n(g.flow_ref_l_min, 4), 'L/min', p)
      + K('Intervalo (1ª → última leitura de massa)', n(g.duration_s, 1), 's') + K('Leituras de massa válidas', g.mass_valid_fraction == null ? '—' : `${n(100 * g.mass_valid_fraction, 0)} %`);
    const pl = K('Basculadas no intervalo', g.pluv_pulses == null ? '—' : g.pluv_pulses, '', p) + K('Precipitação indicada', n(g.pluv_precip_mm, rd), 'mm', p)
      + K('Intensidade indicada', n(g.pluv_intensity_mm_h, 1), 'mm/h', p) + K('Volume equivalente', n(g.pluv_precip_mm != null && g.area_cm2 ? g.pluv_precip_mm * g.area_cm2 / 10 : null, 1), 'mL', p)
      + K('Resolução usada', n(g.resolution_mm, rd), 'mm/basculada');
    const cmp = K('Diferença (pluviômetro − balança)', n(g.diff_mm, 2), 'mm') + K('Erro percentual', g.error_pct == null ? '—' : n(g.error_pct, 2), '%');
    const par = `<p class="note">Parâmetros usados: ρ = ${g.density_g_cm3 == null ? '—' : n(g.density_g_cm3, 4)} g/cm³ · A = ${g.area_cm2 == null ? '—' : n(g.area_cm2, 1)} cm² · resolução = ${g.resolution_mm == null ? '—' : n(g.resolution_mm, rd)} mm/basculada.</p>`;
    const iss = (g.issues || []).map(i => `<p class="note err">${i}</p>`).join('');
    if (which === 'pluv') return sec('Pluviômetro', pl);
    if (which === 'bal') return sec('Balança (referência)', bal) + sec('Comparação', cmp) + par + iss;
    return sec('Balança (referência)', bal) + sec('Pluviômetro', pl) + sec('Comparação', cmp) + par + iss;
  },

  summary(t) {
    const [lab, cls] = this.STATE[t.state] || [t.state, ''], q = t.result && t.result.quality, n = Fmt.num;
    return `<p class="lbl"><b class="${cls}">${lab}</b> · início ${Fmt.dt(t.start_ts)} (hora do datalogger) · coberto ${q ? n(q.covered_s, 0) : '—'} s de ${q ? n(q.window_s, 0) : '—'} s · ${q ? q.rows : '—'} amostras${t.reason ? ` · ${t.reason}` : ''}</p>`;
  },

  detail(t, cfg) {
    if (!t.result) return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}<p class="note">Sem resultado (ensaio interrompido antes da primeira amostra).</p></div>`;
    const d = { ...cfg, density_g_cm3: t.cfg.density }, q = t.result.quality;
    // contextual: comparativo = padrão + medidor + tempo (sem balança); gravimétrico = balança + pluviômetro + tempo
    const html = (t.kind === 'flow' ? this.flowHtml(t.result, d, false) : this.pluvHtml(t.result, d, false)) + this.timingHtml(t.result, t.kind);
    const std = t.kind === 'flow' && t.cfg.standard ? ` · ${esc(t.cfg.standard.tag)}` : '';
    return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}${std}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}
      <p class="note">Configuração congelada no início: ${esc(this.cfgText(t.cfg))}.</p>${q.reasons.length ? `<p class="note err">${q.reasons.join('; ')}</p>` : ''}${html}</div>`;
  },
};
