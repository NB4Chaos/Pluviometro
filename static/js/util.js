// Mostra o erro real no console (o navegador às vezes só mostra "Script error." sem detalhes).
window.addEventListener('error', e => console.error('[Elus] erro:', e.message, `${e.filename}:${e.lineno}:${e.colno}`, e.error && e.error.stack));
window.addEventListener('unhandledrejection', e => console.error('[Elus] promessa rejeitada:', e.reason && (e.reason.stack || e.reason)));

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reducedMotion = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } };
const setHtml = (el, h) => { if (el._h !== h) { el._h = h; el.innerHTML = h; } };   // só reescreve o DOM quando o conteúdo muda
const p2 = n => String(n).padStart(2, '0');
const Fmt = {
  // um valor que arredonda para zero é exibido como 0 (sem "-0,0" quando a diferença é negativa e muito pequena)
  num: (v, d = 1) => v == null || isNaN(v) ? '—' : (Number(v.toFixed(d)) === 0 ? 0 : v).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }),
  any: v => v == null ? '—' : v.toLocaleString('pt-BR', { maximumFractionDigits: 6 }),
  // número com algarismos significativos (fator K, resolução): 0,01 continua 0,01 e 16 666,67 vira 16 666,7
  sig: (v, s = 4) => v == null || !isFinite(v) ? '—' : Number(v.toPrecision(s)).toLocaleString('pt-BR', { maximumFractionDigits: 10 }),
  int: v => v == null || isNaN(v) ? '—' : Math.round(v).toLocaleString('pt-BR'),
  time: t => { if (t == null) return '—'; const d = new Date(t); return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`; },
  dt: t => { if (t == null) return '—'; const d = new Date(t); return `${p2(d.getDate())}/${p2(d.getMonth() + 1)}/${d.getFullYear()} ${Fmt.time(t)}`; },
  tick: (t, span) => { const d = new Date(t), h = `${p2(d.getHours())}:${p2(d.getMinutes())}`; return span > 864e5 ? `${p2(d.getDate())}/${p2(d.getMonth() + 1)} ${h}` : h; },
  local: ms => new Date(ms - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 16),
};
// Unidades de exibição. Os dados guardados e a exportação seguem em g, °C e mA; só a tela converte.
const Units = {
  mass: { mg: { l: 'mg', to: v => v * 1000 }, g: { l: 'g', to: v => v }, kg: { l: 'kg', to: v => v / 1000 },
          lb: { l: 'lb', to: v => v / 453.59237 }, oz: { l: 'oz', to: v => v / 28.349523125 } },
  temp: { C: { l: '°C', to: v => v }, F: { l: '°F', to: v => v * 9 / 5 + 32 }, K: { l: 'K', to: v => v + 273.15 } },
};
// Número digitado em pt-BR ("2,5" ou "2.5"): null se vazio, NaN se não for número.
const parseNum = s => { s = String(s == null ? '' : s).trim().replace(',', '.'); return s === '' ? null : Number(s); };
// Fator K: mesma tabela do servidor (calc.K_UNITS). Unidade interna: pulsos/L.
const KUnits = {
  'pulsos/L': { k: 'k', f: 1 }, 'pulsos/m³': { k: 'k', f: 1e-3 }, 'L/pulso': { k: 'v', f: 1 }, 'mL/pulso': { k: 'v', f: 1e-3 },
  toL(v, u) { const d = this[u]; if (v == null || !d || !isFinite(v) || v <= 0) return null; return d.k === 'k' ? v * d.f : 1 / (v * d.f); },
};
// Vazão: volumétrica (k:'vol', base m³/s) ou mássica (k:'mass', base kg/s). `f` = valor da unidade na base.
const Flow = {
  units: { 'L/min': { k: 'vol', f: 1e-3 / 60 }, 'L/h': { k: 'vol', f: 1e-3 / 3600 }, 'mL/min': { k: 'vol', f: 1e-6 / 60 }, 'mL/s': { k: 'vol', f: 1e-6 },
           'm³/h': { k: 'vol', f: 1 / 3600 }, 'm³/s': { k: 'vol', f: 1 }, 'm³/min': { k: 'vol', f: 1 / 60 }, 'kg/h': { k: 'mass', f: 1 / 3600 }, 'kg/s': { k: 'mass', f: 1 } },
  // Converte entre unidades. Entre massa e volume usa a densidade (g/cm³ = kg/L); sem densidade devolve null (não presume valor).
  convert(v, from, to, dens) {
    if (v == null) return null;
    const a = this.units[from], b = this.units[to];
    if (!a || !b) return null;
    const base = v * a.f;
    if (a.k === b.k) return base / b.f;
    if (!dens) return null;
    const rho = dens * 1000; // kg/m³
    return (a.k === 'vol' ? base * rho : base / rho) / b.f;
  },
};
