"""Servidor REAL (app.py) lendo o emulador (dados fictícios, só para testar a lógica): ensaio de ponta a ponta, congelamento do resultado,
preservação do endereço ao salvar configurações, token de escrita, latência e degradação sem comunicação.
Rodar da pasta do projeto:  python tests/e2e_ensaio.py"""
import sys as _s; _s.stdout.reconfigure(encoding="utf-8", errors="replace")
import atexit, json, os, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.fake_programa_atual import Fake

DATA = tempfile.mkdtemp(prefix="elus_e2e_ens_")
PORT = "5077"
fails = 0


def ok(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(("ok    " if cond else "FALHA ") + label + (f"  -> {extra}" if extra else ""))


fake = Fake(prefill=60, tip_every=10)
fake.mass = 500.0
fake.run(period=1.0)
ADDR = f"127.0.0.1:{fake.port}"
json.dump({"comm": {"protocol": "http", "address": ADDR, "user": "dash", "profile": "programa_vazao"}, "tip_resolution_mm": 0.2,
           "density_g_cm3": 1.0, "catch_area_cm2": 100.0, "flow_method": "pulse", "flow_k_value": 1000.0, "flow_k_unit": "pulsos/L", "trial_duration_s": 10},
          open(os.path.join(DATA, "config.json"), "w"))
env = dict(os.environ, ELUS_DATA_DIR=DATA, DATALOGGER_PASSWORD="segredo", PORT=PORT, PYTHONUNBUFFERED="1", LOG_LEVEL="DEBUG")
for k in ("DATALOGGER_HOST", "DATALOGGER_USER", "CR1000X_PROFILE", "DASHBOARD_TOKEN"):
    env.pop(k, None)
PROCS = []
atexit.register(lambda: [p.kill() for p in PROCS if p.poll() is None])


def start(**extra):
    p = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=dict(env, **extra), stdout=open(os.path.join(DATA, "out.log"), "a"), stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p


def api(path, body=None, headers=None, raw=False, ctype="application/json"):
    h = {"Content-Type": ctype} | (headers or {})
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}" + path, data=None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode()), headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x:
            t = x.read().decode()
            return x.status, (t if raw or "json" not in x.headers.get("Content-Type", "") else json.loads(t))
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        return e.code, (json.loads(t) if t.startswith("{") else t)


def wait(cond, timeout=40, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = cond()
        except OSError:   # servidor ainda subindo (conexão recusada)
            v = None
        if v:
            return v
        time.sleep(step)
    return None


app = start()
wait(lambda: api("/api/summary")[1].get("latest") if api("/api/summary")[0] == 200 else None, 40)
s, summ = api("/api/summary")
ok("servidor leu o datalogger (perfil com Vazao1s) e se declara conectado", s == 200 and summ["link"]["connected"] and summ["link"]["flow_integrated"])
lat = summ["latest"]
ok(f"medidor por pulsos: {lat['flow_pulses']} pulsos brutos no Scan, acumulado {lat['flow_pulses_total']}, estado {lat['flow_state']} (K = 1000 pulsos/L -> 6 L/min)",
   lat["flow"]["method"] == "pulse" and lat["flow"]["active"] == "pulse" and lat["flow_state"] == "ok" and abs(lat["flow_lmin"] - 6.0) < 1e-6
   and lat["flow_pulses"] == 100 and lat["flow_pulses_total"] >= 100)
# 30/10: o método (analógico | pulsos) é do servidor (flow_method), não do campo Flow_mode do datalogger (que fica em 2 no v3/v4).
s, fv = api("/api/flow")
ok("GET /api/flow: método solicitado = ativo = pulsos, canais do programa v4 e dado bruto", s == 200 and fv["method"] == fv["active"] == "pulse"
   and fv["channels"] == {"analog": True, "pulse": True} and fv["raw"]["pulses"] == 100)

# ---- configuração: endereço preservado, sem aceitar endereço pela interface
s, cfg = api("/api/config")
ok("a API de configuração não expõe o endereço do datalogger", "address" not in cfg["comm"])
body = {k: cfg[k] for k in ("mass_unit", "temp_unit", "flow_unit", "mass_decimals", "temp_decimals", "flow_decimals", "default_range_s", "cor",
                            "tip_resolution_mm", "density_g_cm3", "catch_area_cm2", "flow_k_value", "flow_k_unit", "trial_duration_s")}
body["comm"] = {"protocol": "http", "user": "", "profile": "programa_vazao", "address": "10.9.9.9:1"}   # tenta trocar o endereço e apagar o usuário
s, new = api("/api/config", body)
saved = json.load(open(os.path.join(DATA, "config.json")))
ok("salvar configurações NÃO altera o endereço nem apaga o usuário (campo vazio/ausente preserva)", s == 200 and saved["comm"]["address"] == ADDR and saved["comm"]["user"] == "dash")
s, e = api("/api/config", body, ctype="text/plain")
ok("POST que não é JSON é recusado (barra formulário de outro site)", s == 415)

# ---- ensaio de ponta a ponta
s, t = api("/api/trials/start", {"kind": "flow"})
ok("ensaio inicia com a aquisição ativa", s == 200 and t["state"] == "running", f"{t.get('id')}")
s2, e2 = api("/api/trials/start", {"kind": "pluv"})
ok("segundo ensaio simultâneo é recusado (409)", s2 == 409, e2.get("error"))
tid = t["id"]
st = api("/api/trials")[1]["running"]
ok("em andamento: progresso e resultado parcial identificados", st and st["id"] == tid and st["remaining_s"] <= 10 and "partial" in st)
s, _ = api("/api/config", dict(body, trial_duration_s=30))           # operador muda a duração no card durante o ensaio
st2 = api("/api/trials")[1]["running"]
ok("mudar a duração durante o ensaio não altera o ensaio em andamento", s == 200 and st2["duration_cfg_s"] == 10 and st2["end_ts"] == st["end_ts"])
done = wait(lambda: (api(f"/api/trials/{tid}")[1] if api(f"/api/trials/{tid}")[1]["state"] != "running" else None), 40)
ok(f"ensaio termina sozinho no fim previsto: estado {done and done['state']}", done and done["state"] == "completed", done and done.get("reason"))
r = done["result"]; f = r["flow"]
ok(f"vazão do ensaio = 6 L/min e pulsos brutos conferem ({f['pulses_total']} pulsos em {r['quality']['rows']} amostras)",
   abs(f["flow_l_min"]["mean"] - 6.0) < 1e-6 and f["pulses_total"] == 100 * r["quality"]["rows"] and 9 <= r["quality"]["rows"] <= 10)
g = r["gravimetric"]
ok(f"gravimetria: delta de massa = {g['delta_mass_g']:.1f} g em {g['duration_s']:.0f} s (balança ganha 0,1 g/s no emulador)",
   abs(g["delta_mass_g"] - 0.1 * g["duration_s"]) < 0.25 and g["volume_ml"] is not None)
ok("ensaio concluído com a duração fixada no início (10 s), não a nova (30 s)", done["duration_cfg_s"] == 10 and done["duration_cfg_ms"] == 10_000 and done["end_ts"] - done["start_ts"] == 10_000)
tm = r["timing"]
ok(f"temporização registrada: cfg {tm['cfg_ms']} ms, efetivo {tm['eff_ms']} ms, resolução {tm['resolution_ms']} ms, {tm['samples']} amostras, PC {tm['wall_ms']} ms",
   tm["cfg_ms"] == 10_000 and tm["resolution_ms"] == 1000 and tm["eff_ms"] in (9_000, 10_000) and tm["samples"] == r["quality"]["rows"] and tm["wall_ms"] > 0)
ok("pulsos brutos do ensaio: N pela diferença do contador acumulado = soma dos registros", f["count_method"] == "acumulado" and f["pulses_delta_total"] == f["pulses_sum"] == f["pulses_total"])
s, e = api("/api/config", {"trial_duration_ms": 500})
ok("duração de 500 ms é recusada com a resolução efetiva (Scan de 1000 ms)", s == 400 and "1000 ms" in e.get("error", ""), e.get("error"))
s, e = api("/api/config", {"trial_duration_ms": 1500, "trial_duration_unit": "ms"})
ok("duração de 1500 ms (não múltipla do Scan) é aceita e guardada em ms", s == 200 and e["trial_duration_ms"] == 1500 and e["trial_duration_unit"] == "ms" and e["trial_duration_s"] == 1.5)
ok("resultado sem média de massa (a massa coletada é Δm)", "mass" not in r and g["delta_mass_g"] is not None)
s, html = api(f"/relatorio/{tid}", raw=True)
ok("página de relatório imprimível responde (montada no navegador)", s == 200 and "Relatório" in html and "window.print" in html)
dg = api("/api/diag")[1]
ok("diagnóstico traz reinícios de tabela e saúde (relógio/SkippedScan) separados", "restarts" in dg and "health" in dg)
api("/api/config", body)                                             # volta a 10 s para os próximos passos
summ = api(f"/api/summary?from={done['start_ts']}&to={done['end_ts']}")[1]
ok("referência gravimétrica do PERÍODO = mesma regra do ensaio (mesmo Δm e mesmo volume no mesmo intervalo)",
   summ["grav"]["delta_mass_g"] == g["delta_mass_g"] and summ["grav"]["volume_ml"] == g["volume_ml"] and "recent" not in summ and "mass_flow" not in summ, summ["grav"])
frozen = json.dumps(api(f"/api/trials/{tid}")[1], sort_keys=True)
time.sleep(6)                                                        # a aquisição continua; a "janela recente" avança
ok("resultado congelado: igual 6 s depois, mesmo com novas leituras chegando", json.dumps(api(f"/api/trials/{tid}")[1], sort_keys=True) == frozen)
con = sqlite3.connect(os.path.join(DATA, "dados_cr1000x.db"))
try:
    con.execute("UPDATE trials SET result='{}' WHERE id=?", (tid,))
    altered = True
except sqlite3.DatabaseError:
    altered = False
ok("o próprio banco recusa alterar um ensaio encerrado", not altered)
con.close()
s, csvt = api(f"/api/trials/{tid}/raw.csv", raw=True)
ok("amostras brutas do ensaio exportáveis (pulsos, Hz, estado, vazão)", s == 200 and "Pulsos" in csvt and csvt.count("\n") >= 10, f"{s} linhas={csvt.count(chr(10))} {csvt[:160]!r}")

# ---- interrupção pelo usuário
s, t2 = api("/api/trials/start", {"kind": "pluv"}); time.sleep(3)
s, stp = api("/api/trials/stop", {})
ok("ensaio interrompido pelo usuário fica 'interrompido' com os dados preservados", s == 200 and stp["state"] == "interrupted" and stp["result"]["quality"]["rows"] >= 1, stp.get("reason"))

# ---- sem comunicação: o servidor não trava e a interface é avisada; recupera sem duplicar
fake.outage = True
time.sleep(14)
s, summ = api("/api/summary")
ok("datalogger fora do ar: servidor continua respondendo e informa erro/desconectado", s == 200 and not summ["link"]["connected"] and summ["link"]["error"])
s, t3 = api("/api/trials/start", {"kind": "flow"})
ok("sem comunicação não inicia ensaio (409)", s == 409, t3.get("error"))
n_before = sqlite3.connect(os.path.join(DATA, "dados_cr1000x.db")).execute("SELECT COUNT(*) FROM samples").fetchone()[0]
fake.outage = False
time.sleep(16)
c2 = sqlite3.connect(os.path.join(DATA, "dados_cr1000x.db"))
ts = [r[0] for r in c2.execute("SELECT ts FROM samples ORDER BY ts")]
steps = {b - a for a, b in zip(ts, ts[1:])}
ok(f"após a queda os segundos perdidos foram recuperados, sem buracos nem duplicatas ({n_before} -> {len(ts)}; passos {sorted(steps)} ms)",
   len(ts) > n_before + 15 and steps == {1000} and len(ts) == len(set(ts)))
c2.close()

# ---- diagnóstico e latência
s, d = api("/api/diag")
ok(f"diagnóstico: latência PC−datalogger p50 = {d['lat_ms']['p50']} ms, consulta p50 = {d['poll_ms']['p50']:.0f} ms, erros = {d['errors']}", s == 200 and d["lat_ms"]["p50"] is not None and d["poll_ms"]["p50"] < 1000)
log = open(os.path.join(DATA, "logs", "servidor.log"), encoding="utf-8").read()
ok("log não contém a senha nem o cabeçalho de autorização", "segredo" not in log and "Authorization" not in log and "Basic " not in log)
ok("log registra o ciclo do ensaio", f"ensaio {tid}" in log and "encerrado" in log)

# ---- token de escrita
app.terminate(); app.wait(timeout=10)
app = start(DASHBOARD_TOKEN="s3gredo-do-teste"); time.sleep(8)
s, e = api("/api/reset-count", {})
ok("com DASHBOARD_TOKEN, escrita sem token é negada (401)", s == 401)
s, e = api("/api/reset-count", {}, headers={"X-Dashboard-Token": "tok-invalido-xyz"})
ok("token errado é negado", s == 401)
s, e = api("/api/reset-count", {}, headers={"X-Dashboard-Token": "s3gredo-do-teste"})
ok("token correto permite a escrita", s == 200)
s, c = api("/api/config")
ok("leitura continua livre e a API informa que a escrita é protegida, sem expor o token", s == 200 and c["write_protected"] is True and "s3gredo" not in json.dumps(c))
log = open(os.path.join(DATA, "logs", "servidor.log"), encoding="utf-8").read()
ok("o token informado (certo ou errado) nunca aparece no log", "s3gredo" not in log and "tok-invalido-xyz" not in log)
app.terminate(); app.wait(timeout=10); fake.stop()
print("\nTUDO OK" if not fails else f"\n{fails} FALHA(S)")
sys.exit(1 if fails else 0)
