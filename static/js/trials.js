// Apresentação dos ensaios de calibração. O ESTADO vem sempre do servidor (nada aqui decide se um ensaio está em andamento).
// Distinções visuais: "parcial" (ensaio em andamento) · "congelado" (ensaio encerrado) · "ref." (valor de referência da balança)
// · sem etiqueta = medido pelo instrumento.
const Trials = {
  st: { running: null, last: null, history: [] },
  STATE: { running: ['Em andamento', 'warn'], completed: ['Concluído', 'ok'], incomplete: ['Incompleto', 'warn'], interrupted: ['Interrompido', 'err'] },
  KIND: { flow: 'Medidor de Vazão', pluv: 'Pluviômetro (gravimétrico)' },
  mmss: s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; },
  dec: res => { if (!res) return 3; const t = String(res), i = t.indexOf('.'); return Math.min(3, Math.max(1, i < 0 ? 0 : t.length - i - 1)); },
  kv(l, v, u = '', tag = '') { return `<div class="rk"><span>${l}${tag ? ` <em class="t-${tag[0]}">${tag[1]}</em>` : ''}</span><b>${v}${u && v !== '—' ? ` <i>${u}</i>` : ''}</b></div>`; },
  fl(v, cfg) { return v == null ? null : Flow.convert(v, 'L/min', cfg.flow_unit, cfg.density_g_cm3); },

  flowHtml(res, cfg, part) {
    const f = res.flow, K = this.kv.bind(this), n = Fmt.num, dm = cfg.flow_decimals, p = part ? ['p', 'parcial'] : '';
    if (!f) return '<p class="note">O programa do datalogger não fornece o medidor de vazão.</p>';
    const q = f.flow_l_min, fu = cfg.flow_unit, c = v => this.fl(v, cfg);
    let h = K('Vazão média', n(c(q && q.mean), dm), fu, p) + K('Vazão máxima', n(c(q && q.max), dm), fu, p) + K('Vazão mínima', n(c(q && q.min), dm), fu, p)
      + K('Volume no ensaio', n(f.volume_l, 3), 'L', p);
    if (f.mode === 'pulse') h += K('Pulsos brutos (total)', f.pulses_total == null ? '—' : f.pulses_total.toLocaleString('pt-BR'), '', p) + K('Frequência média', n(f.freq_mean_hz, 1), 'Hz', p);
    if (f.ma) h += K('Corrente média', n(f.ma.mean, 3), 'mA', p);
    h += K('Leituras válidas', f.n_rows ? `${f.n_valid}/${f.n_rows} (${n(100 * f.valid_fraction, 0)} %)` : '—');
    const v = f.vs_reference;
    if (v) h += K('Volume pela balança (mesmo intervalo)', n(v.volume_ref_l, 3), 'L', ['r', 'ref.']) + K('Volume do medidor (mesmo intervalo)', n(v.volume_meter_l, 3), 'L')
      + K('Diferença do medidor', n(v.diff_l, 3), 'L') + K('Erro do medidor', v.error_pct == null ? '—' : n(v.error_pct, 2), '%');
    else h += K('Referência pela balança', '—') ;
    return `<div class="rg">${h}</div>` + (f.issues || []).map(i => `<p class="note err">${i}</p>`).join('');
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
    const d = { ...cfg, density_g_cm3: t.cfg.density }, html = this.flowHtml(t.result, d, false) + '<hr>' + this.pluvHtml(t.result, d, false), q = t.result.quality;
    return `<div class="detail"><div class="hd"><h3>Ensaio ${t.id} · ${this.KIND[t.kind]}</h3><button class="btn" id="tr-close">Fechar</button></div>${this.summary(t)}
      <p class="note">Configuração congelada no início: ${JSON.stringify(t.cfg)}.</p>${q.reasons.length ? `<p class="note err">${q.reasons.join('; ')}</p>` : ''}${html}</div>`;
  },
};
