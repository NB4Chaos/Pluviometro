// Cada gráfico mostra o valor medido ao longo do período selecionado e, discreta, a média do período (linha tracejada).
// O resultado do período (número em destaque) fica no cabeçalho do card, fora do gráfico.
const Charts = {
  c: {}, span: 0,
  opts(extra = {}) {
    return {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false, resizeDelay: 150,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      layout: { padding: { right: 8 } },
      plugins: { legend: { display: true, position: 'bottom' }, tooltip: { callbacks: { title: i => Fmt.dt(i[0].parsed.x) } } },
      scales: { x: { type: 'linear', ticks: { maxTicksLimit: 7, callback: v => Fmt.tick(v, Charts.span) } }, y: { title: { display: true, text: '' } }, ...extra },
    };
  },
  chart(id, datasets, extra) {
    return this.c[id] || (this.c[id] = new Chart(document.getElementById(id), { type: 'line', data: { datasets }, options: this.opts(extra), plugins: [this.valueTag] }));
  },
  // escreve o valor numérico junto à linha tracejada da média do período (e à média móvel), com a unidade
  valueTag: {
    id: 'valueTag',
    afterDatasetsDraw(ch) {
      const { ctx, chartArea: a, scales: { y } } = ch;
      ch.data.datasets.forEach((ds, i) => {
        if (!ds.tag || ds.tag.v == null || !ch.isDatasetVisible(i) || !y) return;
        const py = y.getPixelForValue(ds.tag.v);
        if (py < a.top || py > a.bottom) return;
        ctx.save(); ctx.font = '500 11px Urbanist, system-ui, sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
        const txt = ds.tag.text, w = ctx.measureText(txt).width;
        ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.fillRect(a.right - w - 8, py - 17, w + 8, 16);
        ctx.fillStyle = ds.borderColor; ctx.fillText(txt, a.right - 4, py - 3); ctx.restore();
      });
    },
  },
  // data: série medida; avg: média do período (só leituras válidas do período, calculada no servidor)
  line(id, data, o) {
    const { label, color, avg, r, dec, unit } = o;
    const n = v => v == null ? '—' : `${Fmt.num(v, dec)} ${unit}`;
    const ch = this.chart(id, [
      { label: '', data: [], borderColor: color, backgroundColor: color + '14', borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, fill: true, tension: .2, spanGaps: false },
      { label: '', data: [], borderColor: '#8A97B5', borderWidth: 1.2, borderDash: [5, 5], pointRadius: 0, pointHoverRadius: 0, fill: false },
    ]);
    const [m, av] = ch.data.datasets;
    m.label = label; av.label = `Média do período: ${n(avg)}`;
    av.tag = { v: avg, text: `média ${n(avg)}` };
    ch.options.plugins.legend.display = false;
    ch.options.plugins.tooltip.filter = i => i.datasetIndex === 0;
    ch.options.plugins.tooltip.callbacks.label = c => `${label}: ${n(c.parsed.y)}`;
    this.finish(ch, [data, avg == null ? [] : [{ x: r.from, y: avg }, { x: r.to, y: avg }]], `${label} (${unit})`, r);
  },
  pluv(tips, r, cfg) {
    const res = cfg.tip_resolution_mm, k = res || 1, unit = res ? 'mm' : 'basculadas';
    const cum = [{ x: r.from, y: 0 }]; tips.forEach((t, i) => cum.push({ x: t, y: (i + 1) * k })); cum.push({ x: r.to, y: tips.length * k });
    const nb = 48, w = (r.to - r.from) / nb, bins = Array(nb).fill(0);
    tips.forEach(t => { const i = Math.min(nb - 1, Math.floor((t - r.from) / w)); if (i >= 0) bins[i]++; });
    const bars = bins.map((n, i) => ({ x: r.from + w * (i + .5), y: n })).filter(p => p.y > 0);
    const ch = this.chart('ch-pluv', [
      { type: 'bar', label: 'Basculadas por intervalo', data: [], backgroundColor: '#0B1F4B', barThickness: 8, yAxisID: 'y2', order: 2 },
      { label: 'Acumulado', data: [], stepped: 'after', borderColor: '#B07D00', borderWidth: 2.5, pointRadius: 0, yAxisID: 'y', order: 1 },
    ], { y2: { position: 'right', beginAtZero: true, suggestedMax: 3, ticks: { precision: 0 }, grid: { drawOnChartArea: false }, title: { display: true, text: 'Basculadas por intervalo' } } });
    ch.data.datasets[1].label = `Acumulado no período: ${Fmt.num(tips.length * k, res ? 3 : 0)} ${unit}`;
    ch.options.plugins.tooltip.callbacks.label = c => c.dataset.yAxisID === 'y2' ? `${c.parsed.y} basculada(s)` : `${Fmt.num(c.parsed.y, res ? 3 : 0)} ${unit}`;
    this.finish(ch, [bars, cum], `Acumulado no período (${unit})`, r);
  },
  finish(ch, sets, ytitle, r) {
    this.span = r.to - r.from;
    ch.options.scales.x.min = r.from; ch.options.scales.x.max = r.to;
    ch.options.scales.y.title.text = ytitle;
    sets.forEach((d, i) => ch.data.datasets[i].data = d);
    ch.update('none');
  },
  flowKind: null,   // o que o gráfico do medidor mostra agora: 'flow' (L/min convertido) | 'hz' | 'ma'
  flow(pts, d, fs, base, cfg, cv) {
    const m = d.flow_mode === 'pulse' ? 'pulsos' : 'analógico';
    if (fs.flow) { this.flowKind = 'flow'; this.line('ch-cor', pts('flow', cv), { ...base, label: `Vazão (${m})`, avg: cv(fs.flow.avg), dec: cfg.flow_decimals, unit: cfg.flow_unit }); }   // K ou faixa 4–20 mA configurados
    else if (d.flow_mode === 'pulse') { this.flowKind = 'hz'; this.line('ch-cor', pts('hz', v => v), { ...base, label: 'Frequência', avg: fs.pulses ? fs.pulses.avg_hz : null, dec: 1, unit: 'Hz' }); }   // sem K: frequência bruta, sem inventar vazão
    else { this.flowKind = 'ma'; this.line('ch-cor', pts('cor_ma', v => v), { ...base, label: 'Sinal', avg: fs.ma.avg, dec: 3, unit: 'mA' }); }   // sem faixa: sinal bruto em mA
  },
  // Amostra nova pelo Socket.IO: entra no gráfico na hora e a janela desliza, sem consultar o banco nem refazer a série.
  // Os valores são exatamente os recebidos (nenhuma suavização); a média do período só é recalculada na recarga periódica.
  push(s, r, cfg, comp) {
    if (!this.c['ch-mass'] || s.ts == null) return;
    const mu = Units.mass[cfg.mass_unit] || Units.mass.g, tu = Units.temp[cfg.temp_unit] || Units.temp.C;
    const f = s.flow || {}, cv = v => v == null ? null : Flow.convert(v, 'L/min', cfg.flow_unit, cfg.density_g_cm3);
    const add = (id, y) => {
      const ch = this.c[id];
      if (!ch) return;
      const [m, av] = ch.data.datasets, last = m.data[m.data.length - 1];
      if (last && last.x >= s.ts) return;
      m.data.push({ x: s.ts, y });
      while (m.data.length && m.data[0].x < r.from) m.data.shift();
      if (av && av.data.length === 2) { av.data[0].x = r.from; av.data[1].x = r.to; }
      ch.options.scales.x.min = r.from; ch.options.scales.x.max = r.to;
      ch.update('none');
    };
    add('ch-mass', s.mass_g == null ? null : mu.to(s.mass_g));
    add('ch-temp', s.temp_c == null ? null : tu.to(s.temp_c));
    if (comp && this.flowKind) {
      const y = this.flowKind === 'flow' ? (f.state === 'ok' && f.method === s.flow_mode ? cv(f.lmin) : null)
        : this.flowKind === 'hz' ? (s.cor_status === 'ok' ? s.flow_hz : null) : (s.cor_status === 'ok' ? s.cor_ma : null);
      add('ch-cor', y);
    }
  },
  render(d, r, cfg, comp) {
    const mu = Units.mass[cfg.mass_unit] || Units.mass.g, tu = Units.temp[cfg.temp_unit] || Units.temp.C;
    const pts = (k, conv) => d.t.map((t, i) => ({ x: t, y: d[k][i] == null ? null : conv(d[k][i]) }));
    const av = (st, conv) => st.avg == null ? null : conv(st.avg);
    this.line('ch-mass', pts('mass', mu.to), { label: 'Massa', color: '#0B1F4B', avg: av(d.stats.mass, mu.to), r, dec: cfg.mass_decimals, unit: mu.l });
    this.line('ch-temp', pts('temp', tu.to), { label: 'Temperatura', color: '#B07D00', avg: av(d.stats.temp, tu.to), r, dec: cfg.temp_decimals, unit: tu.l });
    const fu = cfg.flow_unit, fs = d.stats.cor, base = { color: '#2F6FB0', r };
    const cv = v => v == null ? null : Flow.convert(v, 'L/min', fu, cfg.density_g_cm3);
    if (comp) this.flow(pts, d, fs, base, cfg, cv);   // medidor de vazão só no método comparativo
    this.pluv(d.tips, r, cfg);
  },
};
