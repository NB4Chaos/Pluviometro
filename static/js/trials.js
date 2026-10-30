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
  dec: res => { if (!res) return 3; const t = String(res), i = t.indexOf('.'); return Math.min(3, Math.max(1, i < 0 ? 0 : t.length - i - 1)); },
  kv(l, v, u = '', tag = '') { return `<div class="rk"><span>${l}${tag ? ` <em class="t-${tag[0]}">${tag[1]}</em>` : ''}</span><b>${v}${u && v !== '—' ? ` <i>${u}</i>` : ''}</b></div>`; },
  fl(v, cfg) { return v == null ? null : Flow.convert(v, 'L/min', cfg.flow_unit, cfg.density_g_cm3); },
  cfgMs: t => t.duration_cfg_ms != null ? t.duration_cfg_ms : t.duration_cfg_s * 1000,
  // ensaio em andamento: tempo decorrido/restante (relógio do servidor) e tempo efetivo coberto por registros do datalogger
  timeRows(t, part) {
    const tm = part && part.timing, cfg = this.cfgMs(t);
    return this.kv('Tempo decorrido', this.dur(t.elapsed_s * 1000)) + this.kv('Tempo restante', `${this.dur(t.remaining_s * 1000)} de ${this.dur(cfg)}`)
      + (tm ? this.kv('Tempo efetivo (registros)', tm.eff_ms == null ? '—' : this.dur(tm.eff_ms), '', ['p', 'parcial']) : '');
  },
  bar(sel, x) {
    const el = $(sel); if (!el) return;
    el.hidden = !(x && x.run);
    if (!el.hidden) el.firstElementChild.style.width = Math.min(100, 100 * x.t.elapsed_s * 1000 / this.cfgMs(x.t)) + '%';
  },
  links: id => `<p class="grp"><a class="btn" href="/relatorio/${id}" target="_blank">Relatório (imprimir / PDF)</a><a class="btn" href="/api/trials/${id}/raw.csv">Amostras (CSV)</a><a class="btn" href="/api/trials/${id}/tips.csv">Basculadas (CSV)</a></p>`,
  kText: c => c.k_pulses_per_l == null ? 'não configurado' : `${Fmt.sig(c.k_pulses_per_l, 6)} pulsos/L`,

  // temporização do ensaio: carimbos do datalogger, configurado × efetivo, resolução (= Scan)
  timingHtml(res) {
    const t = res && res.timing; if (!t) return '';
    const K = this.kv.bind(this), d = this.dur.bind(this), stamp = t.resolution_ms < 1000 ? Fmt.dtms : Fmt.dt;   // ms só quando o Scan resolve ms
    const h = K('Início (datalogger)', stamp(t.start_ts)) + K('Fim previsto', stamp(t.end_ts)) + K('Duração configurada', d(t.cfg_ms))
      + K('Tempo efetivo (1º → último registro + Scan)', t.eff_ms == null ? '—' : d(t.eff_ms)) + K('Diferença efetivo − configurado', t.diff_ms == null ? '—' : `${t.diff_ms > 0 ? '+' : ''}${t.diff_ms} ms`, '', t.diff_ms ? ['p', 'lacuna'] : '')
      + K('Resolução (Scan do datalogger)', `${t.resolution_ms} ms`) + K('Registros no ensaio', t.samples)
      + K('Primeiro registro', stamp(t.first_sample_ts)) + K('Último registro', stamp(t.last_sample_ts)) + (t.wall_ms != null ? K('Tempo de parede (servidor, informativo)', d(t.wall_ms)) : '');
    return `<p class="lbl sec">Temporização</p><div class="rg">${h}</div>`;
  },
  cfgText(c) {
    const p = [];   // chaves do snapshot congelado pelo servidor (trials.start)
    if (c.duration_ms != null || c.duration_s != null) p.push(`duração = ${this.dur(c.duration_ms != null ? c.duration_ms : c.duration_s * 1000)}`);
    if (c.scan_ms != null) p.push(`Scan = ${c.scan_ms} ms`);
    if (c.density != null) p.push(`ρ = ${Fmt.num(c.density, 4)} g/cm³`);
    if (c.area_cm2 != null) p.push(`A = ${Fmt.num(c.area_cm2, 1)} cm²`);
    if (c.res_mm != null) p.push(`resolução = ${Fmt.any(c.res_mm)} mm/basculada`);
    if (c.flow_method) p.push(`método = ${c.flow_method === 'pulse' ? 'pulsos' : 'analógico'}`);
    if ('k_pulses_per_l' in c) p.push(`K = ${this.kText(c)}${c.k_unc_pct != null ? ` (u = ${Fmt.any(c.k_unc_pct)} %)` : ''}`);
    if (c.q4 != null && c.q20 != null) p.push(`4–20 mA = ${Fmt.sig(c.q4)}–${Fmt.sig(c.q20)} ${c.range_unit || ''}`);
    if (c.ma_tol != null) p.push(`tolerância = ${Fmt.num(c.ma_tol, 3)} mA`);
    return p.length ? p.join(' · ') : JSON.stringify(c);
  },

  flowHtml(res, cfg, part) {
    const f = res.flow, K = this.kv.bind(this), n = Fmt.num, dm = cfg.flow_decimals, p = part ? ['p', 'parcial'] : '', C = ['c', 'calculado'];
    if (!f) return '<p class="note">O programa do datalogger não fornece o medidor de vazão.</p>';
    const q = f.flow_l_min, fu = cfg.flow_unit, c = v => this.fl(v, cfg);
    const ML = { pulse: 'Pulsos', analog: 'Analógico 4–20 mA', misto: 'Misto (método mudou)' };
    let h = K('Método', ML[f.mode] || f.mode);
    if (f.mode === 'pulse') {   // o que foi adquirido vem antes do que foi calculado
      h += K('Pulsos brutos (N)', f.pulses_total == null ? '—' : f.pulses_total.toLocaleString('pt-BR'), '', p)
        + K('Tempo efetivo (Δt)', f.time_eff_ms == null ? '—' : this.dur(f.time_eff_ms), '', p) + K('Frequência média', n(f.freq_mean_hz, 1), 'Hz', p);
      if (f.count_method) h += K('Contagem', f.count_method === 'acumulado' ? 'diferença do contador acumulado' : 'soma dos registros', '', f.pulses_sum != null && f.pulses_sum !== f.pulses_total ? ['p', `Σ ${f.pulses_sum.toLocaleString('pt-BR')}`] : '');
      if (f.resolution_pct != null) h += K('Resolução (1 pulso)', Fmt.sig(f.resolution_pct, 2), '%');
      h += K('Fator K usado', f.k_pulses_per_l ? Fmt.sig(f.k_pulses_per_l, 6) : 'não configurado', f.k_pulses_per_l ? 'pulsos/L' : '');
    }
    h += K('Vazão média' + (f.mode === 'pulse' ? ' (N ÷ K ÷ Δt)' : ''), n(c(q && q.mean), dm), fu, p || C) + K('Vazão máxima', n(c(q && q.max), dm), fu, p || C) + K('Vazão mínima', n(c(q && q.min), dm), fu, p || C)
      + K('Volume no ensaio' + (f.mode === 'pulse' ? ' (N ÷ K)' : ''), n(f.volume_l, 3), 'L', p || C);
    const u = f.uncertainty;   // só componentes demonstráveis (±1 pulso, relógio do datalogger, K se informado), combinadas em quadratura
    if (u) {
      h += K('Incerteza da contagem (±1 pulso, retangular)', Fmt.sig(u.pulses_rel_pct, 2), '%') + K('Incerteza do relógio do datalogger (±3 min/ano)', Fmt.sig(u.clock_rel_pct, 2), '%')
        + K('Incerteza do fator K', u.k_included ? Fmt.sig(u.k_rel_pct, 2) : 'não informada (não entrou)', u.k_included ? '%' : '')
        + K('Incerteza-padrão combinada da vazão', Fmt.sig(u.flow_rel_pct, 2), '%', C);
      if (u.flow_u_l_min != null) h += K('Vazão média ± u', `${n(c(q && q.mean), dm)} ± ${Fmt.sig(c(u.flow_u_l_min), 2)}`, fu, C) + K('Volume ± u', `${n(f.volume_l, 3)} ± ${Fmt.sig(u.volume_u_l, 2)}`, 'L', C);
    }
    if (f.ma) h += K('Corrente média', n(f.ma.mean, 3), 'mA', p);
    if (f.n_clamped) h += K('Leituras no limite (4 ou 20 mA)', f.n_clamped);
    h += K('Leituras válidas', f.n_rows ? `${f.n_valid}/${f.n_rows} (${n(100 * f.valid_fraction, 0)} %)` : '—');
    const v = f.vs_reference;
    if (v) h += K('Volume pela balança (mesmo intervalo)', n(v.volume_ref_l, 3), 'L', ['r', 'ref.']) + K('Volume do medidor (mesmo intervalo)', n(v.volume_meter_l, 3), 'L')
      + K('Diferença do medidor', n(v.diff_l, 3), 'L') + K('Erro do medidor', v.error_pct == null ? '—' : n(v.error_pct, 2), '%');
    else h += K('Referência pela balança', '—') ;
    const o = f.other;
    if (o) h += K(`Outro canal (${o.method === 'pulse' ? 'pulsos' : 'analógico'}), mesmo intervalo`, n(o.volume_l, 3), 'L') + K('Diferença entre canais', o.diff_pct == null ? '—' : n(o.diff_pct, 2), '%');
    return `<div class="rg">${h}</div>` + (f.issues || []).map(i => `<p class="note err">${esc(i)}</p>`).join('');
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
    const html = (t.kind === 'flow' ? `<p class="lbl sec">Medidor de vazão</p>${this.flowHtml(t.result, d, false)}<hr>` : '') + this.pluvHtml(t.result, d, false) + this.timingHtml(t.result);
    return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}
      <p class="note">Configuração congelada no início: ${esc(this.cfgText(t.cfg))}.</p>${q.reasons.length ? `<p class="note err">${q.reasons.join('; ')}</p>` : ''}${html}</div>`;
  },
};
