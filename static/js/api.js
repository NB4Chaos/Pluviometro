// Camada de comunicação: tudo que fala com o servidor passa por aqui.
// Token de escrita (DASHBOARD_TOKEN): só é pedido se o servidor exigir (HTTP 401). Fica em sessionStorage (some ao fechar a aba),
// só viaja no cabeçalho X-Dashboard-Token e nunca é exibido nem escrito em log.
const Tok = {
  get() { try { return sessionStorage.getItem('elus.tok') || ''; } catch (e) { return ''; } },
  set(v) { try { sessionStorage.setItem('elus.tok', v); } catch (e) {} },
  clear() { try { sessionStorage.removeItem('elus.tok'); } catch (e) {} },
};
const Api = {
  async get(url, params = {}) {
    const r = await fetch(url + '?' + new URLSearchParams(params));
    if (!r.ok) throw new Error(r.status);
    return r.json();
  },
  async post(url, body = {}, retried = false) {
    const h = { 'Content-Type': 'application/json' }, t = Tok.get();
    if (t) h['X-Dashboard-Token'] = t;
    const r = await fetch(url, { method: 'POST', headers: h, body: JSON.stringify(body) });
    if (r.status === 401 && !retried) {
      Tok.clear();
      const v = window.prompt('Este servidor exige um token de acesso para alterar configurações ou controlar ensaios. Informe o token:');
      if (v) { Tok.set(v.trim()); return this.post(url, body, true); }
    }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
    return r.json();
  },
  connect(onSample, onConn, onTrial) {
    const s = io();
    s.on('sample', onSample);
    s.on('trial', onTrial);
    s.on('connect', () => onConn(true));
    s.on('disconnect', () => onConn(false));
    return s;
  },
};
