"""App inteiro em MODO REAL lendo o emulador do programa atual do usuario (dados ficticios).
Rodar da pasta do projeto:  python tests/e2e_programa_atual.py"""
import sys as _s; _s.stdout.reconfigure(encoding="utf-8", errors="replace")
import atexit, json, os, signal, sqlite3, subprocess, sys, time, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = __import__("tempfile").mkdtemp(prefix="elus_e2e_")   # dados do teste NUNCA na pasta do projeto
sys.path.insert(0, ROOT)
from tests.fake_programa_atual import Fake

fails = 0
def ok(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("ok    " if cond else "FALHA ") + label + (f"  -> {extra}" if extra else ""))

def clean():
    for f in ("dados_cr1000x.db", "cursor_cr1000x.json", "config.json"):
        p = os.path.join(DATA, f)
        if os.path.exists(p):
            try: os.remove(p)
            except PermissionError: pass   # Windows: arquivo ainda aberto; fica na pasta temporária
clean()
fake = Fake(prefill=300, tip_every=15)
fake.run(period=1.0)
json.dump({"comm": {"mode": "cr1000x", "protocol": "http", "address": f"127.0.0.1:{fake.port}", "user": "dash", "profile": "programa_atual"}},
          open(os.path.join(DATA, "config.json"), "w"))
env = dict(os.environ, ELUS_DATA_DIR=DATA, DATALOGGER_PASSWORD="segredo", PORT="5073", PYTHONUNBUFFERED="1")
env.pop("DATALOGGER_MODE", None); env.pop("CR1000X_PROFILE", None)
PROCS = []
atexit.register(lambda: [p.kill() for p in PROCS if p.poll() is None])   # nao deixa servidor para tras se o teste falhar
def start(log):
    p = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p
def api(p, body=None):
    r = urllib.request.Request("http://127.0.0.1:5073" + p, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as x: return x.status, json.load(x) if "json" in x.headers.get("Content-Type", "") else x.read().decode()
    except urllib.error.HTTPError as e: return e.code, json.load(e)
def db(): return sqlite3.connect(os.path.join(DATA, "dados_cr1000x.db"))

app = start(__import__("tempfile").gettempdir() + "/e2e_atual1.log"); time.sleep(14)
s, summ = api("/api/summary")
ok("modo real: o servidor NAO se declara demonstracao", s == 200 and "demo" not in summ and summ["link"]["connected"] is True and summ["mode"] == "cr1000x")
s, html = api("/")
ok("interface fala em termopar tipo T e traz o indicador de dados reais", "termopar tipo T" in html and 'id="real"' in html and "PT100" not in html)
c = db(); n = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
ok(f"historico do datalogger recuperado: {n} amostras (300 de backlog + as geradas)", n >= 300)
lat = summ["latest"]
ok(f"valores ao vivo = os do datalogger (massa {lat['mass_g']} g, temperatura {lat['temp_c']} °C)", abs(lat["mass_g"] - fake.mass) < 3 and 21 < lat["temp_c"] < 22.5)
ok("sem variavel de vazao no programa: nada inventado (estado na = aguardando integracao)", lat["cor_ma"] is None and lat["flow_state"] == "na" and lat["flow_lmin"] is None and summ["link"]["flow_integrated"] is False)
ts = [r[0] for r in c.execute("SELECT ts FROM samples ORDER BY ts")]
ok("uma amostra por segundo, sem buracos nem duplicatas", len(ts) == len(set(ts)) and max(b - a for a, b in zip(ts, ts[1:])) <= 1100, f"maior passo {max(b - a for a, b in zip(ts, ts[1:]))} ms")
incompletas = c.execute("SELECT COUNT(*) FROM samples WHERE temp_status!='ok' OR mass_status!='ok'").fetchone()[0]
ok("nenhuma linha incompleta por atraso entre tabelas", incompletas == 0, f"{incompletas} linhas")
t = c.execute("SELECT COUNT(*), COUNT(DISTINCT src) FROM tips").fetchone()
ok(f"basculadas: {t[0]} eventos com chave unica; datalogger contou {fake.tips}", t[0] == t[1] and abs(t[0] - fake.tips) <= 1)

# Pluvio_Total do datalogger volta a zero (programa reiniciou): a contagem do servidor nao muda
before = c.execute("SELECT COUNT(*) FROM tips").fetchone()[0]; fake.reset_total(); time.sleep(20)
after = db().execute("SELECT COUNT(*) FROM tips").fetchone()[0]
ok(f"reinicio do programa do datalogger (Pluvio_Total=0) nao apaga nem repete basculadas ({before} -> {after}, datalogger {fake.tips})", after >= before and abs(after - fake.tips) <= 1)

# resolucao do pluviometro (config do dashboard) em vez do 0,2 fixo do CRBasic
s, cfg = api("/api/config"); body = {k: cfg[k] for k in ("mass_unit", "temp_unit", "flow_unit", "mass_decimals", "temp_decimals", "flow_decimals", "default_range_s", "cor", "comm")}
body["tip_resolution_mm"] = "0,25"
s, new = api("/api/config", body); s2, summ = api("/api/summary")
p = summ["period"]
ok(f"precipitacao do periodo usa a resolucao configurada (0,25), nao a fixa do datalogger: {p['precip_mm']} mm = {p['tips']} x 0,25", s == 200 and p["tips"] > 0 and abs(p["precip_mm"] - p["tips"] * 0.25) < 1e-6)
body["comm"] = dict(body["comm"], profile="perfil_que_nao_existe")
s, err = api("/api/config", body)
ok(f"perfil inexistente recusado com mensagem: {err.get('error')}", s == 400)

# queda de rede de 12 s
n0 = db().execute("SELECT COUNT(*) FROM samples").fetchone()[0]
fake.outage = True; time.sleep(12); fake.outage = False; time.sleep(8)
c = db(); ts = [r[0] for r in c.execute("SELECT ts FROM samples ORDER BY ts")]
ok(f"apos 12 s sem rede nao ha buraco nos dados (maior passo {max(b - a for a, b in zip(ts, ts[1:]))} ms)", max(b - a for a, b in zip(ts, ts[1:])) <= 1100)
ok("nenhuma linha 'sem comunicacao' inventada durante a queda", c.execute("SELECT COUNT(*) FROM samples WHERE mass_status='no_comm' AND temp_status='no_comm'").fetchone()[0] == 0)
ok(f"os segundos da queda foram recuperados (+{len(ts) - n0} amostras)", len(ts) - n0 >= 18)

# reinicio do servidor
ns, nt = len(ts), c.execute("SELECT COUNT(*) FROM tips").fetchone()[0]
app.terminate(); app.wait(timeout=10); time.sleep(5)
_cur = json.load(open(os.path.join(DATA, "cursor_cr1000x.json")))
ok("cursor gravado em disco para as 3 tabelas, com o horário do último registro de cada uma (âncora)",
   {k for k in _cur if not k.startswith("_")} == {"Balanca1s", "Termopar1s", "Pluviometro1s"} == set(_cur.get("_anchor_time", {})))
app = start(__import__("tempfile").gettempdir() + "/e2e_atual2.log"); time.sleep(10)
c = db(); ns2, d = c.execute("SELECT COUNT(*), COUNT(DISTINCT ts) FROM samples").fetchone(); nt2, dt = c.execute("SELECT COUNT(*), COUNT(DISTINCT src) FROM tips").fetchone()
ok(f"apos reiniciar o servidor nao duplicou amostras ({ns} -> {ns2})", ns2 == d and 0 < ns2 - ns <= 25)
ok(f"nem eventos ({nt} -> {nt2}); total = datalogger ({fake.tips})", nt2 == dt and abs(nt2 - fake.tips) <= 1)
c.close(); app.terminate(); app.wait(timeout=10); fake.stop(); clean()
print("\nTUDO OK" if not fails else f"\n{fails} FALHA(S)"); sys.exit(1 if fails else 0)
