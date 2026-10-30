// Apresentação dos ensaios de calibração. O ESTADO vem sempre do servidor (nada aqui decide se um ensaio está em andamento).
// Distinções visuais: "parcial" (ensaio em andamento) · "congelado" (ensaio encerrado) · "ref." (valor de referência da balança)
// · sem etiqueta = medido pelo instrumento.
const Trials = {
  st: { running: null, last: null, history: [] },
  STATE: { running: ['Em andamento', 'warn'], completed: ['Concluído', 'ok'], incomplete: ['Incompleto', 'warn'], interrupted: ['Interrompido', 'err'] },
  KIND: { flow: 'Medidor de vazão', pluv: 'Pluviômetro (gravimétrico)' },
  METHOD: { analog: 'analógico 4–20 mA', pulse: 'pulsos' },
  mmss: s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; },
  // Tempo com as casas que a RESOLUÇÃO EFETIVA permite (Scan de 1000 ms → inteiro; 100 ms → 1 casa; 10 ms → 2; 1 ms → 3). Nunca arredonda a 0 ou 1 s.
  dec4res: res => (!res || res >= 1000) ? 0 : res >= 100 ? 1 : res >= 10 ? 2 : 3,
  dur(s, resMs = 1000) {
    if (s == null || isNaN(s)) return '—';
    const ms = Math.round(s * 1000), d = this.dec4res(resMs);
    if (ms < 1000) return `${Fmt.num(ms, 0)} ms`;
    if (ms >= 60000 && d === 0) return `${this.mmss(ms / 1000)} min`;
    return `${Fmt.num(ms / 1000, d)} s`;
  },
  durMs(ms, resMs = 1000) { return ms == null ? '—' : this.dur(ms / 1000, resMs); },
  dec: res => { if (!res) return 3; const t = String(res), i = t.indexOf('.'); return Math.min(3, Math.max(1, i < 0 ? 0 : t.length - i - 1)); },
  kv(l, v, u = '', tag = '') { return `<div class="rk"><span>${l}${tag ? ` <em class="t-${tag[0]}">${tag[1]}</em>` : ''}</span><b>${v}${u && v !== '—' ? ` <i>${u}</i>` : ''}</b></div>`; },
  fl(v, cfg) { return v == null ? null : Flow.convert(v, 'L/min', cfg.flow_unit, cfg.density_g_cm3); },
  kText: c => c.k_value == null ? '—' : `${Fmt.any(c.k_value)} ${c.k_unit || 'pulsos/L'}` + (c.k_unit && c.k_unit !== 'pulsos/L' && c.k_pulses_per_l != null ? ` (= ${Fmt.any(c.k_pulses_per_l)} pulsos/L)` : ''),

  flowHtml(res, cfg, part) {
    const f = res.flow, K = this.kv.bind(this), n = Fmt.num, dm = cfg.flow_decimals, p = part ? ['p', 'parcial'] : '';
    if (!f) return '<p class="note">O programa do datalogger não fornece o medidor de vazão.</p>';
    const q = f.flow_l_min, fu = cfg.flow_unit, c = v => this.fl(v, cfg), res_ms = f.time_resolution_ms || 1000;
    let h = '';
    if (f.mode === 'pulse') {
      h += K('Pulsos acumulados no ensaio (N)', f.pulses_total == null ? '—' : f.pulses_total.toLocaleString('pt-BR'), '', p)
        + K('Tempo efetivo (Δt, carimbos do datalogger)', this.durMs(f.time_eff_ms, res_ms), '', p)
        + K('Vazão média (N ÷ K ÷ Δt)', n(c(q && q.mean), dm), fu, p) + K('Volume (N ÷ K)', n(f.volume_l, 3), 'L', p)
        + K('Frequência média', n(f.freq_mean_hz, 1), 'Hz', p) + K('Fator K usado', this.kText(f))
        + K('Contagem', f.count_method === 'acumulado' ? 'diferença do contador do datalogger' : f.count_method === 'soma' ? 'soma dos registros' : '—')
        + K('Σ registros / Δ contador', `${f.pulses_sum == null ? '—' : f.pulses_sum.toLocaleString('pt-BR')} / ${f.pulses_delta_total == null ? '—' : f.pulses_delta_total.toLocaleString('pt-BR')}`)
        + K('Resolução temporal', `${res_ms} ms (Scan)`) + K('Vazão máx / mín por Scan', q ? `${n(c(q.max), dm)} / ${n(c(q.min), dm)}` : '—', q ? fu : '');
    } else {
      h += K('Vazão média', n(c(q && q.mean), dm), fu, p) + K('Vazão máxima', n(c(q && q.max), dm), fu, p) + K('Vazão mínima', n(c(q && q.min), dm), fu, p)
        + K('Volume no ensaio (∫Q dt)', n(f.volume_l, 3), 'L', p) + K('Tempo com sinal válido', this.durMs(f.time_eff_ms, res_ms), '', p);
      if (f.ma) h += K('Corrente média / mín / máx', `${n(f.ma.mean, 3)} / ${n(f.ma.min, 3)} / ${n(f.ma.max, 3)}`, 'mA');
      h += K('Tolerância nos limites', f.ma_tol == null ? '—' : n(f.ma_tol, 3), 'mA');
    }
    h += K('Leituras válidas', f.n_rows ? `${f.n_valid}/${f.n_rows} (${n(100 * f.valid_fraction, 0)} %)` : '—');
    const v = f.vs_reference;
    if (v) h += K('Volume pela balança (mesmo intervalo)', n(v.volume_ref_l, 3), 'L', ['r', 'ref.']) + K('Volume do medidor (mesmo intervalo)', n(v.volume_meter_l, 3), 'L')
      + K('Diferença do medidor', n(v.diff_l, 3), 'L') + K('Erro do medidor', v.error_pct == null ? '—' : n(v.error_pct, 2), '%');
    else h += K('Referência pela balança', '—');
    const o = f.other_channel;
    if (o) h += K(`Outro canal (${this.METHOD[o.channel] || o.channel}, só informação)`, o.channel === 'analog'
      ? `${o.ma_mean == null ? '—' : n(o.ma_mean, 3) + ' mA'} · ${o.flow_l_min_mean == null ? '—' : n(c(o.flow_l_min_mean), dm) + ' ' + fu}`
      : `${o.pulses_total == null ? '—' : o.pulses_total.toLocaleString('pt-BR')} pulsos · ${o.volume_l == null ? '—' : n(o.volume_l, 3) + ' L'}`);
    return `<div class="rg">${h}</div>` + (f.issues || []).map(i => `<p class="note err">${i}</p>`).join('') + (f.warnings || []).map(i => `<p class="note warn">${i}</p>`).join('');
  },

  // Temporização: três tempos separados (configurado, janela, efetivo pelos carimbos) + resolução. NÃO é uma calibração do temporizador.
  timingHtml(res) {
    const t = res.timing, K = this.kv.bind(this);
    if (!t) return '';
    const r = t.resolution_ms || 1000, s = ms => this.durMs(ms, r);
    const diff = t.diff_ms == null ? '—' : `${t.diff_ms > 0 ? '+' : ''}${Fmt.num(t.diff_ms, 0)} ms`;
    return `<p class="lbl sec">Temporização (carimbos do datalogger)</p><div class="rg">${K('Início (1ª amostra)', Fmt.dtms(t.first_sample_ts))}${K('Fim (última amostra)', Fmt.dtms(t.last_sample_ts))}
      ${K('Duração configurada', t.cfg_ms == null ? '—' : `${Fmt.num(t.cfg_ms, 0)} ms`)}${K('Tempo efetivamente medido', s(t.eff_ms))}${K('Diferença (medido − configurado)', diff)}
      ${K('Resolução efetiva', `${r} ms (Scan)`)}${K('Amostras', t.samples)}${K('Relógio do PC (informativo)', t.wall_ms == null ? '—' : `${Fmt.num(t.wall_ms / 1000, 1)} s`)}</div>
      <p class="note">A resolução efetiva é o intervalo do Scan do datalogger: início e fim ficam quantizados em ±1 Scan. Comparar com uma referência externa de tempo é o que permite avaliar o temporizador; este bloco só registra os valores necessários.</p>`;
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
    const [lab, cls] = this.STATE[t.state] || [t.state, ''], q = t.result && t.result.quality, n = Fmt.num, tm = t.result && t.result.timing, r = tm ? tm.resolution_ms : 1000;
    return `<p class="lbl"><b class="${cls}">${lab}</b> · início ${Fmt.dt(t.start_ts)} (hora do datalogger) · ${this.durMs(t.duration_cfg_ms, r)} configurados · coberto ${q ? n(q.covered_s, 0) : '—'} s de ${q ? n(q.window_s, 0) : '—'} s · ${q ? q.rows : '—'} amostras${t.reason ? ` · ${t.reason}` : ''}</p>`;
  },

  cfgText(c) {
    const n = Fmt.any, parts = [`duração ${c.duration_ms != null ? n(c.duration_ms) + ' ms' : n(c.duration_s) + ' s'}`, `Scan ${c.scan_ms || 1000} ms`];
    if (c.method) parts.push(`método ${this.METHOD[c.method] || c.method}`);
    if (c.k_value != null || c.k_pulses_per_l != null) parts.push(`K = ${this.kText(c)}`);
    if (c.q4 != null) parts.push(`faixa ${n(c.q4)} → ${n(c.q20)} ${c.range_unit} (4–20 mA, tolerância ${n(c.ma_tol)} mA)`);
    parts.push(`ρ = ${c.density == null ? '—' : n(c.density)} g/cm³`, `A = ${c.area_cm2 == null ? '—' : n(c.area_cm2)} cm²`, `resolução ${c.res_mm == null ? '—' : n(c.res_mm)} mm`);
    return parts.join(' · ');
  },

  detail(t, cfg) {
    if (!t.result) return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}<p class="note">Sem resultado (ensaio interrompido antes da primeira amostra).</p></div>`;
    const d = { ...cfg, density_g_cm3: t.cfg.density }, q = t.result.quality;
    const html = (t.kind === 'flow' ? this.flowHtml(t.result, d, false) + '<hr>' + this.pluvHtml(t.result, d, false, 'bal') : this.pluvHtml(t.result, d, false)) + '<hr>' + this.timingHtml(t.result);
    return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}
      <p class="note">Configuração congelada no início: ${this.cfgText(t.cfg)}.</p>${q.reasons.length ? `<p class="note err">${q.reasons.join('; ')}</p>` : ''}${html}</div>`;
  },
};
