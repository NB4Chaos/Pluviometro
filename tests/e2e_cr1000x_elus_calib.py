"""Teste ponta a ponta: emulador do CR1000X (dados FICTÍCIOS) -> adaptador -> servidor Flask -> banco.
Roda com:  python tests/test_e2e_cr1000x.py   (da pasta do projeto)"""
import sys as _s; _s.stdout.reconfigure(encoding="utf-8", errors="replace")
import atexit, json, os, signal, sqlite3, subprocess, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = __import__("tempfile").mkdtemp(prefix="elus_e2e_")   # dados do teste NUNCA na pasta do projeto
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import fake_cr1000x as F

fails = 0
def ok(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("ok    " if cond else "FALHA ") + label + (f"  -> {extra}" if extra else ""))

for f in ("dados_cr1000x.db", "cursor_cr1000x.json", "config.json"):
    p = os.path.join(DATA, f)
    if os.path.exists(p): os.remove(p)

srv = F.start(prefill=600, oor_every=50)
port = srv.server_address[1]
json.dump({"comm": {"mode": "cr1000x", "protocol": "http", "address": f"127.0.0.1:{port}", "user": "dash", "profile": "elus_calib"}}, open(os.path.join(DATA, "config.json"), "w"))
env = dict(os.environ, ELUS_DATA_DIR=DATA, DATALOGGER_MODE="cr1000x", DATALOGGER_PASSWORD="segredo", PORT="5071", CR1000X_PROFILE="elus_calib",
           BAL_REGEX=r"([-+]?\s*\d+(?:\.\d+)?)\s*g", PYTHONUNBUFFERED="1")
PROCS = []
atexit.register(lambda: [p.kill() for p in PROCS if p.poll() is None])   # nao deixa servidor para tras se o teste falhar
def start_app(log):
    p = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p
def api(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:5071" + path, timeout=10))
def emu(cmd):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/?command={cmd}", timeout=5))
def db():
    return sqlite3.connect(os.path.join(DATA, "dados_cr1000x.db"))

app = start_app(__import__("tempfile").gettempdir() + "/e2e_app1.log"); time.sleep(12)
c = db()
n = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
ok(f"backlog recuperado ao ligar: {n} amostras (emulador tinha 600 + as geradas depois)", n >= 600)
m = c.execute("SELECT mass_g, mass_status FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
ok(f"massa interpretada do texto bruto da balança pelo BAL_REGEX: {m}", m[0] and m[0] > 1050 and m[1] == "ok")
ts = [r[0] for r in c.execute("SELECT ts FROM samples ORDER BY ts")]
ok("horários de cada registro preservados (passo de 1 s, sem buracos)", max(b - a for a, b in zip(ts, ts[1:])) <= 1100, f"maior passo {max(b - a for a, b in zip(ts, ts[1:]))} ms")
oor = c.execute("SELECT COUNT(*) FROM samples WHERE cor_status='out_of_range' AND cor_ma<4").fetchone()[0]
okc = c.execute("SELECT COUNT(*) FROM samples WHERE cor_status='ok' AND cor_ma BETWEEN 4 AND 20").fetchone()[0]
ok(f"sinal abaixo de 4 mA marcado 'fora da faixa' ({oor}) e o resto válido ({okc}); mA original guardado", oor >= 10 and okc > 500)
tips = c.execute("SELECT COUNT(*), COUNT(DISTINCT src) FROM tips").fetchone()
ok(f"eventos de basculamento: {tips[0]} no banco, todos com chave única", tips[0] == tips[1] and tips[0] > 5)
st = emu("_state")
ok(f"total no banco = TipsTotal do datalogger ({st['tips']})", abs(tips[0] - st["tips"]) <= 1, f"banco {tips[0]} x datalogger {st['tips']}")
s = api("/api/summary")["latest"]
ok("amostra ao vivo do servidor com Coriolis e vazão pela balança", s["cor_ma"] is not None and s["mass_g"] > 1050, f"cor_ma={s['cor_ma']} mass_g={s['mass_g']}")
c.close()

# ---- queda de rede de 10 s: o datalogger segue gravando; nada de linhas inventadas; na volta, tudo recuperado
before = db().execute("SELECT COUNT(*) FROM samples").fetchone()[0]
emu("_outage&on=1"); time.sleep(10); emu("_outage&on=0"); time.sleep(13)   # 30/10: o recuo progressivo (1, 2, 4, 8 s) só volta a consultar ~15 s após o início da queda
c = db()
ts = [r[0] for r in c.execute("SELECT ts FROM samples ORDER BY ts")]
gap = max(b - a for a, b in zip(ts, ts[1:]))
nc = c.execute("SELECT COUNT(*) FROM samples WHERE mass_status='no_comm' AND temp_status='no_comm'").fetchone()[0]
ok(f"após queda de rede de 10 s não há buraco nos dados (maior passo {gap} ms)", gap <= 1100)
ok("nenhuma linha 'sem comunicação' inventada durante a queda", nc == 0, f"{nc} linhas")
ok(f"registros do período da queda foram recuperados (+{len(ts) - before} amostras)", len(ts) - before >= 14)
c.close()

# ---- reinício do servidor: o cursor em disco evita duplicar
n_s = db().execute("SELECT COUNT(*) FROM samples").fetchone()[0]; n_t = db().execute("SELECT COUNT(*) FROM tips").fetchone()[0]
app.terminate(); app.wait(timeout=10); time.sleep(4)
cur = json.load(open(os.path.join(DATA, "cursor_cr1000x.json")))
ok(f"cursor gravado em disco: {cur}", "Medidas" in cur and "Basculadas" in cur)
app = start_app(__import__("tempfile").gettempdir() + "/e2e_app2.log"); time.sleep(8)
c = db()
n_s2, d_s = c.execute("SELECT COUNT(*), COUNT(DISTINCT ts) FROM samples").fetchone()
n_t2, d_t = c.execute("SELECT COUNT(*), COUNT(DISTINCT src) FROM tips").fetchone()
st = emu("_state")
ok(f"após reiniciar não duplicou amostras ({n_s} -> {n_s2}, todas com horário único)", n_s2 == d_s and n_s2 - n_s <= 20)
ok(f"nem eventos ({n_t} -> {n_t2}); total = datalogger ({st['tips']})", n_t2 == d_t and abs(n_t2 - st["tips"]) <= 1, f"banco {n_t2} x datalogger {st['tips']}")
c.close()

# ---- adaptador direto: senha errada, lacuna na memória do datalogger, tabela reiniciada
from datalogger import CR1000X
import urllib.error
bad = CR1000X(address=f"127.0.0.1:{port}", user="dash", password="errada", cursor_file=__import__("tempfile").gettempdir() + "/c_bad.json", profile="elus_calib")
try:
    bad.read(); ok("senha errada deveria falhar", False)
except urllib.error.HTTPError as e:
    ok(f"senha errada recusada pelo datalogger (HTTP {e.code}), o servidor não cai", e.code == 401)
F.S["ring"] = 50; time.sleep(3)
g = CR1000X(address=f"127.0.0.1:{port}", user="dash", password="segredo", cursor_file=__import__("tempfile").gettempdir() + "/c_gap.json", profile="elus_calib"); g.next = {"Medidas": 5}
got = g.read()
ok(f"lacuna na memória do datalogger detectada (gaps={g.gaps}) e dados disponíveis recuperados ({len(got)} registros)", g.gaps >= 1 and len(got) > 0)
r = CR1000X(address=f"127.0.0.1:{port}", user="dash", password="segredo", cursor_file=__import__("tempfile").gettempdir() + "/c_rst.json", profile="elus_calib"); r.next = {"Medidas": 10 ** 6, "Basculadas": 10 ** 6}
got = r.read()
ok(f"tabela reiniciada (número de registro voltou atrás) detectada: recomeça do primeiro ({len(got)} registros)", len(got) > 0)
app.terminate(); app.wait(timeout=10)
for f in ("dados_cr1000x.db", "cursor_cr1000x.json", "config.json"):
    p = os.path.join(DATA, f)
    try:
        if os.path.exists(p): os.remove(p)
    except PermissionError: pass
print("\nTUDO OK" if not fails else f"\n{fails} FALHA(S)")
sys.exit(1 if fails else 0)
