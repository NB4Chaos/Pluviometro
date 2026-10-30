// Padrões de vazão: cadastro único (aba Padrões) e seleção direta no card principal (método Comparativo).
// O servidor copia os parâmetros do padrão escolhido para a configuração ativa e o ensaio congela a própria cópia:
// editar ou excluir um padrão nunca altera um ensaio já feito. Nada aqui decide se a aquisição está ativa: isso vem do datalogger (FlowUI).
const ACQ = { pulse: 'Pulsos', analog: '4–20 mA' };
const Standards = {
  list: [], q: '', editing: null, menuOpen: false, busy: false,

  // ---------- dados ----------
  async load() {
    const d = await Api.get('/api/standards', this.q ? { q: this.q } : {});
    this.list = d.standards;
    this.renderList(); this.renderHero();
  },
  selected() { return S.cfg && S.cfg.standard; },
  byId(id) { return this.list.find(s => s.id === Number(id)); },
  paramsText(s) {
    if (s.acq === 'pulse') return `K = ${Fmt.sig(s.k_value, 6)} ${esc(s.k_unit)}${s.k_unit === 'pulsos/kg' ? ' (massa)' : ''}`;
    return `${Fmt.sig(s.q4)} → ${Fmt.sig(s.q20)} ${esc(s.range_unit)} (4–20 mA)`;
  },
  idLine(s) { return [s.brand, s.model].filter(Boolean).map(esc).join(' | ') + (s.sn ? `${s.brand || s.model ? ' · ' : ''}SN ${esc(s.sn)}` : ''); },

  // ---------- card principal: seletor por TAG ----------
  renderHero() {
    const btn = $('#std-sel'), menu = $('#std-menu'); if (!btn) return;
    const s = this.selected();
    setHtml(btn, s ? `<span class="tag-id">${esc(s.tag)}</span><span class="tag-sub">${this.idLine(s) || esc(ACQ[s.acq])}</span><svg class="ic chev" aria-hidden="true"><use href="#i-chev"/></svg>`
      : `<span class="tag-id">Medidor de vazão</span><span class="tag-sub">${this.list.length ? 'escolha o padrão' : 'cadastre um padrão na aba Padrões'}</span><svg class="ic chev" aria-hidden="true"><use href="#i-chev"/></svg>`);
    btn.setAttribute('aria-expanded', String(this.menuOpen));
    const run = Trials.st.running;
    btn.disabled = !!run;
    btn.title = run ? 'O padrão fica fixo durante o ensaio.' : 'Escolher o padrão de vazão';
    const items = this.list.map(x => `<li role="option" aria-selected="${s && s.id === x.id}" data-id="${x.id}" tabindex="-1">
        <span class="tag-id">${esc(x.tag)}</span><span class="tag-sub">${this.idLine(x)}</span><span class="tag-acq">${ACQ[x.acq]}</span></li>`).join('');
    setHtml(menu, items || '<li class="empty">Nenhum padrão cadastrado. Use a aba <b>Padrões</b>.</li>');
  },
  toggleMenu(open) {
    const menu = $('#std-menu'), btn = $('#std-sel');
    this.menuOpen = open === undefined ? !this.menuOpen : open;
    menu.hidden = false;
    requestAnimationFrame(() => menu.classList.toggle('open', this.menuOpen));
    btn.setAttribute('aria-expanded', String(this.menuOpen));
    if (!this.menuOpen) setTimeout(() => { if (!this.menuOpen) menu.hidden = true; }, reducedMotion() ? 0 : 220);
    else { const cur = menu.querySelector('[aria-selected=true]') || menu.querySelector('li[data-id]'); if (cur) cur.focus(); }
  },
  async select(id) {
    if (this.busy) return;
    this.busy = true; this.toggleMenu(false);
    const msg = $('#bal-msg');
    try {
      const r = await Api.post(`/api/standards/${id}/select`, {});
      S.cfg = r.config; FlowUI.st = r.flow; FlowUI.msg = r.method_error || '';
      if (r.method_error) setTimeout(() => { FlowUI.msg = ''; FlowUI.renderMethod(); }, 10000);
      onConfigChanged();
      if (msg) msg.textContent = r.method_error ? '' : `Padrão ${r.config.standard.tag} selecionado: parâmetros carregados.`;
    } catch (e) { if (msg) msg.textContent = e.message; }
    finally { this.busy = false; this.renderHero(); }
  },
  bindHero() {
    const btn = $('#std-sel'), menu = $('#std-menu'); if (!btn) return;
    btn.onclick = () => this.toggleMenu();
    menu.addEventListener('click', e => { const li = e.target.closest('li[data-id]'); if (li) this.select(li.dataset.id); });
    menu.addEventListener('keydown', e => {
      const items = $$('#std-menu li[data-id]'), i = items.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); this.toggleMenu(false); btn.focus(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); (items[i + 1] || items[0]).focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); (items[i - 1] || items[items.length - 1]).focus(); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (i >= 0) this.select(items[i].dataset.id); }
    });
    document.addEventListener('click', e => { if (this.menuOpen && !e.target.closest('#std-wrap')) this.toggleMenu(false); });
  },

  // ---------- aba Padrões ----------
  renderList() {
    const el = $('#std-list'); if (!el) return;
    const sel = this.selected();
    setHtml(el, this.list.map(s => `<article class="std-card${sel && sel.id === s.id ? ' on' : ''}" data-id="${s.id}">
      <div class="std-hd"><div><span class="tag-id">${esc(s.tag)}</span><p class="tag-sub">${this.idLine(s) || '—'}</p></div><span class="tag ${s.acq === 'pulse' ? 'ok' : ''}">${ACQ[s.acq]}</span></div>
      <p class="std-par">${this.paramsText(s)}${s.pulse_cfg ? ` · ${esc(s.pulse_cfg)}` : ''}${s.signal_type ? ` · ${esc(s.signal_type)}` : ''}</p>
      ${s.description ? `<p class="note">${esc(s.description)}</p>` : ''}
      <div class="grp"><button class="btn sm" data-act="edit">Editar</button><button class="btn sm ghost" data-act="del">Excluir</button>${sel && sel.id === s.id ? '<span class="note ok">Selecionado no card principal</span>' : ''}</div>
    </article>`).join('') || `<p class="lbl">${this.q ? 'Nenhum padrão corresponde à busca.' : 'Nenhum padrão cadastrado ainda. Clique em "Novo padrão".'}</p>`);
  },
  openForm(s) {
    this.editing = s ? s.id : null;
    const f = $('#std-form'); f.hidden = false;
    $('#std-form-title').textContent = s ? `Editar ${s.tag}` : 'Novo padrão';
    const v = (k, d = '') => { const el = $('#sf-' + k); if (el) el.value = s && s[k] != null ? String(s[k]).replace('.', ',') : d; };
    ['tag', 'brand', 'model', 'sn', 'manufacturer', 'description', 'notes', 'pulse_cfg', 'signal_type'].forEach(k => v(k));
    v('k_value'); v('q4'); v('q20');
    $('#sf-acq').value = s ? s.acq : 'pulse'; $('#sf-k_unit').value = s && s.k_unit ? s.k_unit : 'pulsos/L'; $('#sf-range_unit').value = s && s.range_unit ? s.range_unit : 'L/min';
    $('#std-msg').textContent = ''; $$('#std-form [aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
    this.applyAcq();
    f.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
    $('#sf-tag').focus();
  },
  closeForm() { $('#std-form').hidden = true; this.editing = null; },
  applyAcq() {
    const acq = $('#sf-acq').value;
    $('#sf-pulse').hidden = acq !== 'pulse'; $('#sf-analog').hidden = acq !== 'analog';
    const mass = $('#sf-k_unit').value === 'pulsos/kg';
    $('#sf-k-help').textContent = mass ? 'pulsos/kg: N ÷ K é MASSA (kg). O volume e a vazão volumétrica só são calculados com a densidade da água configurada, e aparecem marcados como convertidos.'
      : 'Volume = N ÷ K. Use a unidade exatamente como está no certificado ou na configuração da saída de pulsos do medidor.';
  },
  values() {
    const g = k => ($('#sf-' + k).value || '').trim();
    return { tag: g('tag'), brand: g('brand'), model: g('model'), sn: g('sn'), manufacturer: g('manufacturer'), description: g('description'), notes: g('notes'),
             acq: $('#sf-acq').value, k_value: g('k_value'), k_unit: $('#sf-k_unit').value, pulse_cfg: g('pulse_cfg'),
             q4: g('q4'), q20: g('q20'), range_unit: $('#sf-range_unit').value, signal_type: g('signal_type') };
  },
  validate(v) {
    const bad = (k, m) => { $('#sf-' + k).setAttribute('aria-invalid', 'true'); return m; };
    $$('#std-form [aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
    if (!v.tag) return bad('tag', 'Informe a TAG do padrão.');
    if (v.acq === 'pulse') { const k = parseNum(v.k_value); if (k === null || !isFinite(k) || k <= 0) return bad('k_value', 'Fator K: informe um número maior que zero.'); }
    else {
      const a = parseNum(v.q4), b = parseNum(v.q20);
      if (a === null || !isFinite(a)) return bad('q4', 'Informe o valor correspondente a 4 mA.');
      if (b === null || !isFinite(b)) return bad('q20', 'Informe o valor correspondente a 20 mA.');
      if (a === b) return bad('q20', 'O valor em 20 mA precisa ser diferente do valor em 4 mA.');
    }
    return '';
  },
  async save(e) {
    e.preventDefault();
    const v = this.values(), msg = $('#std-msg'), err = this.validate(v);
    if (err) { msg.textContent = err; msg.className = 'note err'; return; }
    const btn = $('#std-save'); btn.disabled = true;
    try {
      if (this.editing) await Api.put(`/api/standards/${this.editing}`, v); else await Api.post('/api/standards', v);
      msg.textContent = `Padrão ${v.tag} salvo.`; msg.className = 'note ok';
      this.closeForm(); await this.load();
      $('#std-list-msg').textContent = `Padrão ${v.tag} salvo às ${Fmt.time(Date.now())}.`;
    } catch (x) { msg.textContent = x.message; msg.className = 'note err'; }
    finally { btn.disabled = false; }
  },
  async remove(s) {
    if (!confirm(`Excluir o padrão ${s.tag}?\nOs ensaios já realizados com ele continuam no histórico, com a cópia dos parâmetros usados.`)) return;
    try { await Api.del(`/api/standards/${s.id}`); $('#std-list-msg').textContent = `Padrão ${s.tag} excluído.`; await this.load(); }
    catch (x) { $('#std-list-msg').textContent = x.message; }
  },
  bindTab() {
    if (!$('#v-padroes')) return;
    $('#std-new').onclick = () => this.openForm(null);
    $('#std-cancel').onclick = () => this.closeForm();
    $('#std-form').addEventListener('submit', e => this.save(e));
    $('#sf-acq').onchange = $('#sf-k_unit').onchange = () => this.applyAcq();
    let t; $('#std-q').addEventListener('input', e => { clearTimeout(t); t = setTimeout(() => { this.q = e.target.value; this.load(); }, 250); });
    $('#std-list').addEventListener('click', e => {
      const b = e.target.closest('button[data-act]'); if (!b) return;
      const s = this.byId(b.closest('.std-card').dataset.id); if (!s) return;
      if (b.dataset.act === 'edit') this.openForm(s); else this.remove(s);
    });
  },
};
