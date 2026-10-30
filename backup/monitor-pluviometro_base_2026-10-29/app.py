import copy, csv, hmac, io, json, logging, math, os, sqlite3, threading, time
from collections import deque
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler

# ---------- credenciais e conexão automática com o CR1000Xe ----------
# A senha não fica gravada neste arquivo: é recuperada do Gerenciador de
# Credenciais do Windows pelo pacote keyring, usando a conta do Windows atual.
# Se DATALOGGER_PASSWORD já vier do ambiente (testes automáticos), o keyring não é consultado.
if not os.environ.get("DATALOGGER_PASSWORD"):
    import keyring
    _KEYRING_SERVICE = "Elus-CR1000Xe"
    _stored_user = keyring.get_password(_KEYRING_SERVICE, "DATALOGGER_USER")
    _stored_password = keyring.get_password(_KEYRING_SERVICE, "DATALOGGER_PASSWORD")
    if not _stored_user or not _stored_password:
        raise RuntimeError(
            "Credenciais do CR1000Xe não encontradas no armazenamento do Windows. "
            "Cadastre DATALOGGER_USER e DATALOGGER_PASSWORD no serviço Elus-CR1000Xe."
        )
    os.environ["DATALOGGER_USER"] = _stored_user
    os.environ["DATALOGGER_PASSWORD"] = _stored_password
    os.environ.setdefault("DATALOGGER_HOST", "169.254.244.82")
    os.environ.setdefault("DATALOGGER_PROTOCOL", "http")
    os.environ.setdefault("CR1000X_PROFILE", "programa_vazao")

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

import calc
from datalogger import Reading, make_datalogger
from trials import Trials, TrialError

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("ELUS_DATA_DIR") or BASE   # banco, cursor, config.json e logs (os testes usam uma pasta temporária)
os.makedirs(DATA, exist_ok=True)
CFG_PATH = os.path.join(DATA, "config.json")
SAMPLE_PERIOD = float(os.environ.get("SAMPLE_PERIOD", "1.0"))  # s entre consultas ao datalogger (o Scan do CRBasic é de 1 s)
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN") or None   # se definido, protege TODA operação de escrita
MASS_UNITS, TEMP_UNITS = ("mg", "g", "kg", "lb", "oz"), ("C", "F", "K")
FLOW_UNITS = ("L/min", "L/h", "mL/min", "mL/s", "m³/h", "m³/s", "m³/min", "kg/h", "kg/s")
DEFAULTS = {"mass_unit": "g", "temp_unit": "C", "flow_unit": "L/min", "mass_decimals": 1, "temp_decimals": 2,
            "flow_decimals": 3, "density_g_cm3": None, "tip_resolution_mm": None,
            "default_range_s": 900,
            "catch_area_cm2": None,        # área da ABERTURA do coletor (cm²). Não é a da báscula.
            "flow_k_pulses_per_l": None,   # fator K do medidor por pulsos (pulsos por litro). Nunca presumido.
            "trial_duration_s": 60,        # duração dos ensaios (card da balança); fixada no início de cada ensaio
            "cor": {"q4": None, "q20": None, "unit": "L/min"},  # faixa 4–20 mA: definida pelo operador, nunca fixa no código
            "comm": {"protocol": "http", "address": "", "user": "", "profile": "programa_atual"}}
COLS = ["ts", "mass_g", "temp_c", "mass_status", "temp_status", "tips_total", "cor_ma", "cor_status",
        "flow_mode", "flow_pulses", "flow_hz"]
INSERT_SQL = f"INSERT OR REPLACE INTO samples({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
LAB = {"no_comm": "Sem comunicação", "invalid": "Leitura inválida", "out_of_range": "Fora da faixa"}


# ---------- logs (arquivo com rotação + terminal; nunca registra senha nem token) ----------
def setup_logging():
    os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if not root.handlers:
        fh = RotatingFileHandler(os.path.join(DATA, "logs", "servidor.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        sh = logging.StreamHandler()
        for h in (fh, sh):
            h.setFormatter(fmt)
            root.addHandler(h)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # sem uma linha por requisição


setup_logging()
log = logging.getLogger("servidor")

app = Flask(__name__)
sio = SocketIO(app, async_mode="threading")
lock = threading.Lock()


# ---------- configuração (lida do disco uma vez; só set_config a atualiza) ----------
def _read_cfg():
    cfg = copy.deepcopy(DEFAULTS)
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if k not in ("comm", "cor")})
        cfg["comm"].update({k: v for k, v in user.get("comm", {}).items() if k != "mode"})
        cfg["cor"].update(user.get("cor", {}))
    return cfg


_cfg = _read_cfg()


def load_cfg():
    return _cfg


MODE = "cr1000x"  # único modo: não existe mais geração de dados fictícios
_comm = dict(load_cfg()["comm"])
for _k, _env in (("address", "DATALOGGER_HOST"), ("user", "DATALOGGER_USER"), ("protocol", "DATALOGGER_PROTOCOL"), ("profile", "CR1000X_PROFILE")):
    if os.environ.get(_env):  # variável de ambiente tem prioridade sobre o config.json
        _comm[_k] = os.environ[_env]
dl = make_datalogger(_comm)

# ---------- banco ----------
db = sqlite3.connect(os.path.join(DATA, f"dados_{MODE}.db"), check_same_thread=False)   # escrita: só a aquisição e os ensaios, sob `lock`
db.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS samples(ts INTEGER PRIMARY KEY, mass_g REAL, temp_c REAL,
  mass_status TEXT, temp_status TEXT, tips_total INTEGER, cor_ma REAL, cor_status TEXT);
CREATE TABLE IF NOT EXISTS tips(ts INTEGER, src TEXT);
CREATE INDEX IF NOT EXISTS ix_tips ON tips(ts);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);""")
_have = {r[1] for r in db.execute("PRAGMA table_info(samples)")}
for _col, _typ in (("cor_ma", "REAL"), ("cor_status", "TEXT"), ("flow_mode", "TEXT"), ("flow_pulses", "REAL"), ("flow_hz", "REAL")):
    if _col not in _have:  # bancos antigos ganham as colunas novas sem perder dados
        db.execute(f"ALTER TABLE samples ADD COLUMN {_col} {_typ}")
if "src" not in {r[1] for r in db.execute("PRAGMA table_info(tips)")}:  # banco antigo: ganha a chave única do evento
    db.execute("ALTER TABLE tips ADD COLUMN src TEXT")
db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tips_src ON tips(src)")  # evento vindo do datalogger nunca entra duas vezes
db.commit()


_DB_PATH = os.path.join(DATA, f"dados_{MODE}.db")
_rdb = threading.local()


def q(sql, a=()):
    """Leitura: conexão própria por thread (WAL: leitores não bloqueiam a aquisição nem esperam pelo `lock`)."""
    con = getattr(_rdb, "con", None)
    if con is None:
        con = _rdb.con = sqlite3.connect(_DB_PATH, check_same_thread=False)
    return con.execute(sql, a).fetchall()


def w(sql, a=()):
    with lock:
        db.execute(sql, a)
        db.commit()


def count_since():
    r = q("SELECT v FROM meta WHERE k='count_since'")
    return int(r[0][0]) if r else 0


def tips_total():
    return q("SELECT COUNT(*) FROM tips WHERE ts>=?", (count_since(),))[0][0]


def last_tip():
    return q("SELECT MAX(ts) FROM tips")[0][0]


def latest_sample_ts():
    return q("SELECT MAX(ts) FROM samples")[0][0]


state = {"latest": None, "last_rx": None, "trial_id": None}
trials = Trials(db, lock, load_cfg, latest_sample_ts)


# ---------- Medidor de Vazão: qualquer modo (pulsos em P2 ou mA em 2H/2L) -> L/min, sempre a partir do dado bruto ----------
def lin(ma, cor):
    """Relação linear entre 4 e 20 mA e a faixa configurada. None se a faixa não está configurada."""
    if ma is None or cor["q4"] is None or cor["q20"] is None:
        return None
    return cor["q4"] + (ma - 4) / 16 * (cor["q20"] - cor["q4"])


def cor_class(r):
    """Estado do sinal em mA. Fora de 4–20 mA fica marcado como tal; o valor em mA original é sempre preservado."""
    if r.cor_status != "ok":
        return r.cor_status
    if r.cor_ma is None:
        return "no_comm"
    return "ok" if 4 <= r.cor_ma <= 20 else "out_of_range"


def flow_class(r):
    """Estado do medidor de vazão em qualquer modo. None = o programa não tem a variável (aguardando integração)."""
    if r.flow_mode == "pulse":
        return r.cor_status
    return cor_class(r)



def flow_value(mode, ma, hz, status, cfg=None):
    """Retorna (vazão em L/min, estado)."""
    if status is None:
        return None, "na"
    if status != "ok":
        return None, status

    cfg = cfg or load_cfg()
    mode = mode or "analog"

    # No modo analógico, valida primeiro a corrente recebida.
    if mode == "analog":
        if ma is None:
            return None, "invalid"
        if ma < 4.0 or ma > 20.0:
            return None, "out_of_range"
        if cfg["cor"]["q4"] is None or cfg["cor"]["q20"] is None:
            return None, "unconfigured"

    v = calc.flow_from_sample(
        mode,
        "ok",
        hz,
        ma,
        cfg["flow_k_pulses_per_l"],
        cfg["cor"]["q4"],
        cfg["cor"]["q20"],
        cfg["cor"]["unit"],
        cfg["density_g_cm3"],
    )

    return (v, "ok") if v is not None else (None, "unconfigured")



def flow_stats(where, a, cfg):
    """Média/mín/máx da vazão (L/min) no período. Pulso e mA são lineares: média da vazão = vazão da média."""
    base = f"FROM samples WHERE {where} AND cor_status='ok'"
    n_out = q(f"SELECT COUNT(*) FROM samples WHERE {where} AND cor_status='out_of_range'", a)[0][0]
    pu = q(f"SELECT AVG(flow_hz),MIN(flow_hz),MAX(flow_hz),COUNT(flow_hz) {base} AND flow_mode='pulse'", a)[0]
    an = q(f"SELECT AVG(cor_ma),MIN(cor_ma),MAX(cor_ma),COUNT(cor_ma) {base} AND COALESCE(flow_mode,'analog')='analog'", a)[0]
    f = lambda v: None if v is None else round(v, 3)
    ma = {"avg": f(an[0]), "min": f(an[1]), "max": f(an[2]), "n": an[3], "n_out": n_out}
    out = {"ma": ma, "flow": None, "pulses": None, "mode": "pulse" if pu[3] > an[3] else "analog" if an[3] else None,
           "mixed": bool(pu[3] and an[3])}
    if pu[3]:
        out["pulses"] = {"avg_hz": f(pu[0]), "n": pu[3]}
    use_pulse = out["mode"] == "pulse"
    k, cor = cfg["flow_k_pulses_per_l"], cfg["cor"]
    if use_pulse and k:
        out["flow"] = {"avg": f(pu[0] / k * 60), "min": f(pu[1] / k * 60), "max": f(pu[2] / k * 60), "unit": "L/min"}
    elif not use_pulse and an[3] and cor["q4"] is not None and cor["q20"] is not None:
        vals = [calc.flow_to_l_min(lin(m, cor), cor["unit"], cfg["density_g_cm3"]) for m in (an[0], an[1], an[2])]
        if None not in vals:
            lo, hi = sorted([vals[1], vals[2]])
            out["flow"] = {"avg": f(vals[0]), "min": f(lo), "max": f(hi), "unit": "L/min"}
    return out


def stats(where, a):
    """Média, mínimo, máximo e nº de leituras válidas (valores nulos ficam de fora). Média do PERÍODO inteiro."""
    r = q(f"SELECT AVG(mass_g),MIN(mass_g),MAX(mass_g),COUNT(mass_g),AVG(temp_c),MIN(temp_c),MAX(temp_c),COUNT(temp_c) "
          f"FROM samples WHERE {where}", a)[0]
    f = lambda v: None if v is None else round(v, 3)
    return {"mass": {"avg": f(r[0]), "min": f(r[1]), "max": f(r[2]), "n": r[3]},
            "temp": {"avg": f(r[4]), "min": f(r[5]), "max": f(r[6]), "n": r[7]},
            "cor": flow_stats(where, a, load_cfg())}


def period_grav(fr, to):
    """Referência gravimétrica do período [fr, to): 1ª e última massa válida e basculadas em (t0, t1], a mesma regra dos ensaios."""
    cfg = load_cfg()
    sql = "SELECT ts,mass_g FROM samples WHERE ts>=? AND ts<? AND mass_g IS NOT NULL ORDER BY ts {} LIMIT 1"
    a, b = q(sql.format("ASC"), (fr, to)), q(sql.format("DESC"), (fr, to))
    if not a or a[0][0] == b[0][0]:
        return calc.gravimetric(None, None, None, None, cfg["density_g_cm3"], cfg["catch_area_cm2"])
    (t0, m0), (t1, m1), res = a[0], b[0], cfg["tip_resolution_mm"]
    n = q("SELECT COUNT(*) FROM tips WHERE ts>? AND ts<=?", (t0, t1))[0][0]
    return calc.gravimetric(m0, m1, t0, t1, cfg["density_g_cm3"], cfg["catch_area_cm2"], n if res else None, res)


# ---------- aquisição ----------
diag = {"polls": 0, "errors": 0, "consec_errors": 0, "poll_ms": deque(maxlen=300), "lat_ms": deque(maxlen=300),
        "rows": 0, "out_of_order": 0, "stalls": 0, "last_ts": None, "live": True, "started": int(time.time() * 1000), "health": {}}
link = {"last_try": None, "last_ok": None, "error": None}  # estado real da comunicação com o datalogger


def _health():
    diag["health"] = dl.health()
    off = diag["health"]["clock_offset_s"]
    if off is not None and abs(off) > 2:
        log.warning("Relógio do datalogger difere do PC em %s s", off)


def pct(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p))] if s else None


def link_view():
    """Conectado = a última consulta funcionou há pouco. Nunca presumido: sem consulta bem-sucedida, fica desconectado."""
    ok, now = link["last_ok"], time.time() * 1000
    fresh = ok is not None and link["error"] is None and now - ok < max(10, 5 * SAMPLE_PERIOD) * 1000
    rx = state["last_rx"]
    lat = list(diag["lat_ms"])
    print("DEBUG FLOW:", dl.has_flow, dl.profile.get("flow"), dl.profile.get("cor"))
    return {"connected": fresh, "last_try_ts": link["last_try"], "last_ok_ts": ok, "error": link["error"],
            "gaps": dl.gaps, "flow_integrated": dl.has_flow or bool(dl.profile.get("cor")),
            "data_fresh": rx is not None and now - rx < 10_000,        # chegou amostra NOVA nos últimos 10 s
            "last_rx_ts": rx, "latency_s": round(pct(lat, .5) / 1000, 1) if lat else None,
            "clock_skew_s": diag["health"].get("clock_offset_s")}   # desvio real do relógio (ClockCheck), não a latência


def store_batch(batch, now):
    """Grava um lote de Readings numa única transação. Devolve (linhas gravadas, eventos realmente novos).
    As basculadas entram ANTES das amostras, para que `tips_total` de cada amostra já as inclua."""
    events, rows = [], []
    with lock:
        for r in batch:
            for item in r.tips:  # cada basculada é um evento com id próprio; o INSERT OR IGNORE recusa repetidos pela chave
                tts, key = item if isinstance(item, tuple) else (item, None)
                cur = db.execute("INSERT OR IGNORE INTO tips(ts,src) VALUES(?,?)", (tts, key))
                if cur.rowcount:
                    events.append({"id": cur.lastrowid, "ts": tts})
        since = count_since()
        for r in batch:
            if not r.sample:
                continue
            ts = r.ts or now
            n = db.execute("SELECT COUNT(*) FROM tips WHERE ts>=? AND ts<=?", (since, ts)).fetchone()[0]
            full = (ts, r.mass_g, r.temp_c, r.mass_status, r.temp_status, n, r.cor_ma, flow_class(r), r.flow_mode, r.flow_pulses, r.flow_hz)
            db.execute(INSERT_SQL, full)
            rows.append(full)
        db.commit()
    return rows, events


def emit_trial():
    st = trials.status()
    sio.emit("trial", st)
    return st


def acquire():
    summary_t, health_t = time.time(), 0.0
    while True:   # a thread de aquisição nunca morre: qualquer erro inesperado é registrado e o ciclo seguinte continua
        try:
            summary_t, health_t = _acquire_once(summary_t, health_t)
        except Exception:
            log.exception("Erro inesperado no ciclo de aquisição; continuando")
            sio.sleep(SAMPLE_PERIOD)


def _acquire_once(summary_t, health_t):
    if True:
        t0 = time.time()
        now = int(t0 * 1000)
        link["last_try"] = now
        diag["polls"] += 1
        try:
            if not _comm.get("address"):
                raise RuntimeError("Endereço do datalogger não configurado (DATALOGGER_HOST ou config.json).")
            got = dl.read()
            link["last_ok"], link["error"] = now, None
            diag["consec_errors"] = 0
            diag["poll_ms"].append((time.time() - t0) * 1000)
        except Exception as e:  # falha de comunicação: nada é gravado; o datalogger guarda os dados e recuperamos na volta
            diag["errors"] += 1
            diag["consec_errors"] += 1
            msg = (str(e) or e.__class__.__name__)[:200]
            if link["error"] != msg:
                log.warning("Falha na leitura do datalogger: %s", msg)
            link["error"] = msg
            # recuo progressivo (até 10 s): não martela um datalogger/rede que já está com problema
            sio.sleep(min(10.0, SAMPLE_PERIOD * 2 ** min(diag["consec_errors"], 5)))
            try:
                trials.tick(int(time.time() * 1000))
            except Exception:
                log.exception("Falha ao avaliar o ensaio")
            return summary_t, health_t
        batch = got if isinstance(got, list) else [got]
        diag["live"] = len(batch) <= 2
        rows, events = store_batch(batch, now)
        for full in rows:
            diag["rows"] += 1
            if diag["last_ts"] is not None and full[0] <= diag["last_ts"]:
                diag["out_of_order"] += 1
                if diag["out_of_order"] in (1, 10, 100) or diag["out_of_order"] % 1000 == 0:   # não inunda o log numa releitura
                    log.warning("Amostra fora de ordem ou repetida: ts=%d (última=%d); %d ocorrências", full[0], diag["last_ts"], diag["out_of_order"])
            diag["last_ts"] = max(full[0], diag["last_ts"] or 0)
        last = rows[-1] if rows else None
        if last:   # a tela recebe ANTES de gravar o cursor: nada do que acontece no disco atrasa a exibição
            t_rx = int(time.time() * 1000)
            diag["lat_ms"].append(t_rx - last[0])   # latência real (PC − carimbo do datalogger), de TODO ciclo com dados
            state["last_rx"] = t_rx
            fl, fst = flow_value(last[8], last[6], last[10], last[7])
            s = dict(zip(COLS, last), last_tip_ts=last_tip(), new_tips=events, flow_lmin=fl, flow_state=fst, rx_ts=t_rx)
            state["latest"] = s
            sio.emit("sample", s)
        if len(batch) > 2 or time.time() - t0 > 1.5:   # ciclo lento ou rajada: fica registrado para diagnóstico
            diag["stalls"] += 1
            if diag["stalls"] in (1, 10, 100) or diag["stalls"] % 1000 == 0:
                log.warning("Ciclo de %.2f s com %d leituras (recuperação/atraso); %d ocorrências", time.time() - t0, len(batch), diag["stalls"])
        dl.ack()  # o cursor só avança depois de gravado: nada se perde se o servidor cair no meio
        try:
            fin = trials.tick(int(time.time() * 1000))
            if fin or state["trial_id"] or trials.has_running():   # status() calcula o parcial: só quando há ensaio
                st = trials.status()
                state["trial_id"] = st["running"]["id"] if st["running"] else None
                sio.emit("trial", st)
        except Exception:
            log.exception("Falha ao avaliar o ensaio")
        if time.time() - health_t > 3600:   # diagnóstico leve (2 consultas) uma vez por hora, em outra thread: nunca atrasa a aquisição
            health_t = time.time()
            sio.start_background_task(_health)
        if time.time() - summary_t > 60:   # um resumo por minuto: suficiente para diagnosticar sem inflar o log
            summary_t = time.time()
            lat, pm = list(diag["lat_ms"]), list(diag["poll_ms"])
            log.info("resumo: consultas=%d erros=%d amostras=%d lat(PC-datalogger) p50=%s p95=%s ms consulta p50=%s p95=%s ms lacunas=%d "
                     "sem-correspondencia=%s", diag["polls"], diag["errors"], diag["rows"], pct(lat, .5), pct(lat, .95),
                     pct(pm, .5), pct(pm, .95), dl.gaps, dl.join_miss)
        sio.sleep(max(0.05, SAMPLE_PERIOD - (time.time() - t0)))
        return summary_t, health_t


# ---------- segurança ----------
def guarded(f):
    """Operações de escrita: JSON obrigatório (barra POST de formulário de outro site) e token, se DASHBOARD_TOKEN estiver definido."""
    @wraps(f)
    def inner(*a, **k):
        if request.mimetype != "application/json":
            return jsonify(error="Use Content-Type: application/json."), 415
        if DASHBOARD_TOKEN and not hmac.compare_digest(request.headers.get("X-Dashboard-Token", "").encode(), DASHBOARD_TOKEN.encode()):
            log.warning("Escrita negada em %s (token ausente ou incorreto)", request.path)   # o token informado nunca é registrado
            return jsonify(error="Token de acesso inválido."), 401
        return f(*a, **k)
    return inner


# ---------- API ----------
def rng():
    to = int(float(request.args.get("to") or time.time() * 1000))
    return int(float(request.args.get("from") or to - 900000)), to


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    return app.send_static_file("img/favicon.ico")


@app.get("/relatorio/<tid>")
def relatorio(tid):
    """Relatório imprimível: página estática que lê /api/trials/<id> no navegador (nenhum processamento no servidor)."""
    return render_template("relatorio.html")


@app.get("/api/summary")
def summary():
    fr, to = rng()
    cfg, res = load_cfg(), load_cfg()["tip_resolution_mm"]
    smp = [r[0] for r in q("SELECT ts FROM samples WHERE ts>=? AND ts<? ORDER BY ts", (fr, to))]
    tps = [r[0] for r in q("SELECT ts FROM tips WHERE ts>=? AND ts<? ORDER BY ts", (fr, to))]
    period = calc.precip_period(tps, smp, fr, to, res) | {"from": fr, "to": to}
    return jsonify(latest=state["latest"], link=link_view(), now=int(time.time() * 1000), mode=MODE, period=period,
                   tips_total=tips_total(), count_since=count_since(), last_tip_ts=last_tip(),
                   stats=stats("ts>=? AND ts<?", [fr, to]), grav=period_grav(fr, to), resolution=res, area_cm2=cfg["catch_area_cm2"])


@app.get("/api/series")
def series():
    fr, to = rng()
    cfg = load_cfg()
    rows = q("SELECT ts,mass_g,temp_c,cor_ma,cor_status,flow_mode,flow_hz FROM samples WHERE ts>=? AND ts<? ORDER BY ts", (fr, to))
    ts = [r[0] for r in rows]
    fl = [flow_value(r[5], r[3], r[6], r[4], cfg)[0] for r in rows]
    cols = {"mass": [r[1] for r in rows], "temp": [r[2] for r in rows], "cor_ma": [r[3] if r[4] == "ok" else None for r in rows], "flow": fl,
            "hz": [r[6] if r[4] == "ok" and r[5] == "pulse" else None for r in rows]}
    step = len(ts) // 600 + 1
    out = {"t": [], **{k: [] for k in cols}}
    for i in range(0, len(ts), step):   # no máx. ~600 pontos: cada ponto = média das leituras válidas do trecho
        ch = range(i, min(i + step, len(ts)))
        out["t"].append(ts[ch[-1]])
        for k, v in cols.items():
            vals = [v[j] for j in ch if v[j] is not None]
            out[k].append(round(sum(vals) / len(vals), 3) if vals else None)
    out["flow_mode"] = next((r[5] for r in reversed(rows) if r[5]), None)
    out["stats"] = stats("ts>=? AND ts<?", [fr, to])
    out["tips"] = [r[0] for r in q("SELECT ts FROM tips WHERE ts>=? AND ts<? ORDER BY ts", (fr, to))]
    return jsonify(out)


@app.get("/api/tips")
def tips_api():
    fr, to = rng()
    lo, lim = max(fr, count_since()), min(int(request.args.get("limit", 50)), 1000)
    rows = tip_rows("t.ts>=? AND t.ts<?", (lo, to), "DESC", lim)
    total = q("SELECT COUNT(*) FROM tips WHERE ts>=? AND ts<?", (lo, to))[0][0]
    return jsonify(total=total, events=rows)


TIP_SETTLE_MS = 3000      # a água leva ~1–2 s para cair e a balança estabilizar: a massa da basculada é lida 3 s depois dela
TIP_PREV_MAX_MS = 600000  # basculada anterior há mais de 10 min (ou massa menor): a referência não vale mais (tara, esvaziamento)


def tip_rows(where, a, order, lim=None):
    """Basculadas com a massa da balança após a basculada e a massa ejetada desde a anterior (Δm).

    Massa de cada basculada = amostra em ts + 3 s, se a próxima basculada ainda não aconteceu; senão a do próprio segundo
    (`settled` diz qual foi). Δm usa a basculada anterior real (mesmo fora da página); None se faltar massa, se a anterior
    for antiga demais ou se a massa diminuiu."""
    tips = q(f"SELECT t.rowid, t.ts FROM tips t WHERE {where} ORDER BY t.ts {order}, t.rowid {order}" + (f" LIMIT {int(lim)}" if lim else ""), a)
    if not tips:
        return []
    if order == "DESC":
        tips = tips[::-1]                       # trabalha em ordem cronológica
    prev = q("SELECT rowid, ts FROM tips WHERE ts < ? OR (ts = ? AND rowid < ?) ORDER BY ts DESC, rowid DESC LIMIT 1", (tips[0][1], tips[0][1], tips[0][0]))
    seq = (prev[0:1] or []) + tips
    nxt = q("SELECT ts FROM tips WHERE ts > ? OR (ts = ? AND rowid > ?) ORDER BY ts, rowid LIMIT 1", (tips[-1][1], tips[-1][1], tips[-1][0]))
    latest = latest_sample_ts() or 0
    want = []
    for i, (_, ts) in enumerate(seq):
        after = seq[i + 1][1] if i + 1 < len(seq) else (nxt[0][0] if nxt else None)
        ok = ts + TIP_SETTLE_MS <= latest and (after is None or after > ts + TIP_SETTLE_MS)
        want.append((ts + TIP_SETTLE_MS, True) if ok else (ts, False))
    mass = dict(q(f"SELECT ts, mass_g FROM samples WHERE ts IN ({','.join('?' * len(want))})", [w[0] for w in want])) if want else {}
    out, pm, pts = [], None, None
    for (rid, ts), (mts, settled) in zip(seq, want):
        m = mass.get(mts)
        dm = None if m is None or pm is None or ts - pts > TIP_PREV_MAX_MS or m < pm else round(m - pm, 3)
        out.append({"id": rid, "ts": ts, "mass_g": m, "settled": settled, "dm_g": dm})
        pm, pts = m, ts
    out = out[1:] if prev else out              # a anterior só serviu de referência
    return out[::-1] if order == "DESC" else out


def hist_where():
    fr, to = rng()
    sensor, st = request.args.get("sensor", "all"), request.args.get("state", "all")
    where, a = ["ts>=? AND ts<?"], [fr, to]
    cols = {"mass": ["mass_status"], "temp": ["temp_status"], "cor": ["cor_status"], "tips": []}.get(
        sensor, ["mass_status", "temp_status", "cor_status"])
    if cols and st == "ok":
        where.append(" AND ".join(f"COALESCE({c},'ok')='ok'" for c in cols))
    elif cols and st in ("no_comm", "invalid", "out_of_range"):
        where.append("(" + " OR ".join(f"{c}='{st}'" for c in cols) + ")")
    return " AND ".join(where), a


@app.get("/api/history")
def history():
    where, a = hist_where()
    lim, off = min(int(request.args.get("limit", 50)), 1000), int(request.args.get("offset", 0))
    total = q(f"SELECT COUNT(*) FROM samples WHERE {where}", a)[0][0]
    rows = q(f"SELECT {','.join(COLS)} FROM samples WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?", a + [lim, off])
    cfg, out = load_cfg(), []
    for r in rows:
        d = dict(zip(COLS, r))
        d["flow_lmin"], d["flow_state"] = flow_value(d["flow_mode"], d["cor_ma"], d["flow_hz"], d["cor_status"], cfg)
        out.append(d)
    return jsonify(total=total, rows=out, stats=stats(where, a), resolution=cfg["tip_resolution_mm"])


def estado(ms, ts, cs):
    parts = [f"{LAB[s]} ({n})" for s, n in ((ms, "balança"), (ts, "termopar"), (cs, "medidor de vazão")) if s not in ("ok", None)]
    return "; ".join(parts) or "Válida"


def export_table():
    """Cabeçalho + linhas. Valores originais (massa em g, temperatura em °C, sinal em mA, pulsos brutos), data/hora e unidades."""
    where, a = hist_where()
    sensor, cfg = request.args.get("sensor", "all"), load_cfg()
    res = cfg["tip_resolution_mm"]
    rows = q(f"SELECT {','.join(COLS)} FROM samples WHERE {where} ORDER BY ts LIMIT 200000", a)
    m_on, t_on, c_on, p_on = (sensor in ("all", "mass"), sensor in ("all", "temp"), sensor in ("all", "cor"),
                              sensor in ("all", "tips"))
    head = ["Data e hora"] + (["Massa (g)"] if m_on else []) + (["Temperatura (°C)"] if t_on else []) \
        + (["Medidor de Vazão (mA)", "Pulsos (contagem em 1 s)", "Frequência (Hz)", "Vazão (L/min)"] if c_on else []) \
        + (["Basculadas (total desde zerar)", "Precipitação acumulada desde zerar (mm)"] if p_on else []) + ["Estado"]
    out = []
    for ts, m, t, ms, tst, n, ma, cs, mode, pul, hz in rows:
        out.append([datetime.fromtimestamp(ts / 1000)] + ([m] if m_on else []) + ([t] if t_on else [])
                   + ([ma, pul, hz, flow_value(mode, ma, hz, cs, cfg)[0]] if c_on else [])
                   + ([n, round(n * res, 3) if res else None] if p_on else [])
                   + [estado(ms if m_on else "ok", tst if t_on else "ok", cs if c_on else "ok")])
    return head, out


def csv_response(head, rows, name):
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=";")  # ";" e vírgula decimal: abre direto no Excel em pt-BR
    wr.writerow(head)
    for r in rows:
        wr.writerow([r[0].strftime("%d/%m/%Y %H:%M:%S") if isinstance(r[0], datetime) else r[0]] +
                    ["" if v is None else str(v).replace(".", ",") if isinstance(v, float) else v for v in r[1:]])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})


@app.get("/export.csv")
def export_csv():
    head, rows = export_table()
    return csv_response(head, rows, "medicoes.csv")


@app.get("/export.xlsx")
def export_xlsx():
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    head, rows = export_table()
    wb = Workbook(write_only=True)  # escrita em fluxo: tempo linear (o modo comum ficava quadrático com milhares de linhas)
    ws = wb.create_sheet("Medições")
    ws.column_dimensions["A"].width = 22
    ws.append(head)
    for r in rows:
        c = WriteOnlyCell(ws, value=r[0])
        c.number_format = "DD/MM/YYYY HH:MM:SS"
        ws.append([c] + r[1:])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=medicoes.xlsx"})


@app.get("/export-eventos.csv")
def export_events():
    fr, to = rng()
    rows = tip_rows("t.ts>=? AND t.ts<?", (max(fr, count_since()), to), "ASC")
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=";")
    wr.writerow(["Evento (id)", "Data e hora", "Intervalo desde a anterior (s)", "Massa 3 s após a basculada (g)", "Massa ejetada desde a anterior (g)", "Massa lida 3 s depois?"])
    d = lambda v: "" if v is None else str(v).replace(".", ",")
    prev = None
    for e in rows:
        wr.writerow([e["id"], datetime.fromtimestamp(e["ts"] / 1000).strftime("%d/%m/%Y %H:%M:%S.%f")[:-3],
                     "" if prev is None else d(round((e["ts"] - prev) / 1000, 3)), d(e["mass_g"]), d(e["dm_g"]), "sim" if e["settled"] else "nao"])
        prev = e["ts"]
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=eventos-basculamento.csv"})


# ---------- ensaios ----------
def _trial_err(e):
    return jsonify(error=e.msg), e.status


@app.get("/api/trials")
def trials_api():
    return jsonify(trials.status() | {"history": trials.list(30)})


@app.get("/api/trials/<tid>")
def trial_get(tid):
    t = trials.get(tid)
    return (jsonify(t), 200) if t else (jsonify(error="Ensaio não encontrado."), 404)


@app.post("/api/trials/start")
@guarded
def trial_start():
    kind = (request.get_json(silent=True) or {}).get("kind")
    lv = link_view()
    try:
        t = trials.start(kind, lv["connected"] and lv["data_fresh"])
    except TrialError as e:
        return _trial_err(e)
    emit_trial()
    return jsonify(t)


@app.post("/api/trials/stop")
@guarded
def trial_stop():
    try:
        t = trials.stop()
    except TrialError as e:
        return _trial_err(e)
    emit_trial()
    return jsonify(t)


@app.get("/api/trials/<tid>/raw.csv")
def trial_raw(tid):
    t = trials.get(tid)
    if not t:
        return jsonify(error="Ensaio não encontrado."), 404
    s, _ = trials.raw(tid)
    cfg = t["cfg"]
    head = ["Data e hora (datalogger)", "Massa (g)", "Temperatura (°C)", "Estado da massa", "Estado da temperatura",
            "Medidor de Vazão (mA)", "Estado do medidor", "Modo do medidor", "Pulsos (contagem em 1 s)", "Frequência (Hz)", "Vazão (L/min)"]
    rows = [[datetime.fromtimestamp(r[0] / 1000), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
             calc.flow_from_sample(r[7] or "analog", r[6] if r[6] is not None else "ok", r[9], r[5], cfg.get("k_pulses_per_l"),
                                   cfg.get("q4"), cfg.get("q20"), cfg.get("range_unit"), cfg.get("density"))] for r in s]
    return csv_response(head, rows, f"ensaio-{tid}-amostras.csv")


@app.get("/api/trials/<tid>/tips.csv")
def trial_tips(tid):
    if not trials.get(tid):
        return jsonify(error="Ensaio não encontrado."), 404
    _, tp = trials.raw(tid)
    return csv_response(["Data e hora (datalogger)", "Chave do evento"],
                        [[datetime.fromtimestamp(a / 1000), b] for a, b in tp], f"ensaio-{tid}-basculadas.csv")


# ---------- diagnóstico ----------
@app.get("/api/diag")
def diag_api():
    lat, pm = list(diag["lat_ms"]), list(diag["poll_ms"])
    return jsonify(link=link_view(), polls=diag["polls"], errors=diag["errors"], rows=diag["rows"], out_of_order=diag["out_of_order"],
                   gaps=dl.gaps, restarts=dl.restarts, stalls=diag["stalls"], join_miss=dl.join_miss, health=diag["health"], sample_period_s=SAMPLE_PERIOD, started=diag["started"],
                   lat_ms={"p50": pct(lat, .5), "p95": pct(lat, .95), "max": max(lat) if lat else None},
                   poll_ms={"p50": pct(pm, .5), "p95": pct(pm, .95), "max": max(pm) if pm else None},
                   write_protected=bool(DASHBOARD_TOKEN))


# ---------- configuração ----------
def public_cfg(cfg):
    c = copy.deepcopy(cfg)
    c["comm"].pop("address", None)   # o endereço do datalogger não é exibido nem editável pela interface
    return c | {"active_mode": MODE, "write_protected": bool(DASHBOARD_TOKEN)}


@app.get("/api/config")
def get_config():
    return jsonify(public_cfg(load_cfg()))


def num(x, label):
    try:
        v = float(str(x).replace(",", "."))
    except ValueError:
        raise ValueError(f"{label}: informe um número.")
    if not math.isfinite(v):
        raise ValueError(f"{label}: informe um número válido.")
    return v


def opt_num(x, label):
    return None if x in (None, "") or str(x).strip() == "" else num(x, label)


def whole(x, label, lo, hi):
    v = num(x, label)
    if v != int(v) or not lo <= v <= hi:
        raise ValueError(f"{label}: use um inteiro entre {lo} e {hi}.")
    return int(v)


def positive(x, label):
    v = opt_num(x, label)
    if v is not None and v <= 0:
        raise ValueError(f"{label}: informe um valor maior que zero.")
    return v


@app.post("/api/config")
@guarded
def set_config():
    global _cfg
    d, cfg = request.get_json(silent=True) or {}, copy.deepcopy(load_cfg())
    try:
        if d["mass_unit"] not in MASS_UNITS or d.get("temp_unit", "C") not in TEMP_UNITS or d.get("flow_unit", "L/min") not in FLOW_UNITS:
            raise ValueError("Unidade inválida.")
        cfg["mass_unit"], cfg["temp_unit"], cfg["flow_unit"] = d["mass_unit"], d.get("temp_unit", "C"), d.get("flow_unit", "L/min")
        for k, label in (("mass_decimals", "Casas decimais da massa"), ("temp_decimals", "Casas decimais da temperatura"),
                         ("flow_decimals", "Casas decimais da vazão")):
            cfg[k] = whole(d.get(k, cfg[k]), label, 0, 6)
        for k, label in (("tip_resolution_mm", "Resolução"), ("density_g_cm3", "Densidade"), ("catch_area_cm2", "Área de captação"),
                         ("flow_k_pulses_per_l", "Fator K")):
            cfg[k] = positive(d.get(k, cfg[k]), label)   # campo ausente preserva; "" apaga
        cfg["default_range_s"] = whole(d.get("default_range_s", 900), "Período inicial", 1, 31 * 86400)
        cfg["trial_duration_s"] = whole(d.get("trial_duration_s", cfg["trial_duration_s"]), "Duração do ensaio", 10, 6 * 3600)
        c = d.get("cor", {})
        unit = c.get("unit", cfg["cor"]["unit"])
        if unit not in FLOW_UNITS:
            raise ValueError("Unidade de vazão da faixa inválida.")
        q4, q20 = opt_num(c.get("q4"), "Vazão em 4 mA"), opt_num(c.get("q20"), "Vazão em 20 mA")
        if (q4 is None) != (q20 is None):
            raise ValueError("Informe a vazão em 4 mA e em 20 mA, ou deixe as duas vazias.")
        if q4 is not None and q4 == q20:
            raise ValueError("A vazão em 20 mA não pode ser igual à vazão em 4 mA.")
        cfg["cor"] = {"q4": q4, "q20": q20, "unit": unit}
        # Comunicação: só atualiza o que veio preenchido e é válido. O ENDEREÇO nunca vem da interface; campos ausentes
        # ou vazios preservam o valor atual (nada é gravado como "" por acidente).
        cm, cur = d.get("comm") or {}, cfg["comm"]
        profiles = sorted(f[:-5] for f in os.listdir(os.path.join(BASE, "profiles")) if f.endswith(".json"))
        if cm.get("profile"):
            if cm["profile"] not in profiles:
                raise ValueError("Perfil do datalogger desconhecido.")
            cur["profile"] = cm["profile"]
        if cm.get("protocol") in ("http", "https"):
            cur["protocol"] = cm["protocol"]
        if str(cm.get("user") or "").strip():
            cur["user"] = str(cm["user"]).strip()
    except (KeyError, TypeError):
        return jsonify(error="Valores inválidos."), 400
    except ValueError as e:
        return jsonify(error=str(e)), 400
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:   # gravação atômica: queda de energia não deixa config.json pela metade
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CFG_PATH)
    _cfg = cfg
    log.info("configuração salva (resolução=%s, área=%s, K=%s, duração do ensaio=%ss)", cfg["tip_resolution_mm"], cfg["catch_area_cm2"],
             cfg["flow_k_pulses_per_l"], cfg["trial_duration_s"])
    return jsonify(public_cfg(cfg))


@app.post("/api/reset-count")
@guarded
def reset_count():
    w("INSERT OR REPLACE INTO meta VALUES('count_since',?)", (str(int(time.time() * 1000)),))
    return jsonify(ok=True)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not DASHBOARD_TOKEN:
        log.warning("Servidor exposto em %s SEM DASHBOARD_TOKEN: qualquer máquina da rede pode alterar configurações e iniciar ensaios.", host)
    log.info("iniciando: datalogger=%s perfil=%s protocolo=%s proteção de escrita=%s", "configurado" if _comm.get("address") else "NÃO configurado",
             _comm.get("profile"), _comm.get("protocol"), "ligada" if DASHBOARD_TOKEN else "desligada")
    sio.start_background_task(acquire)
    sio.run(app, host=host, port=int(os.environ.get("PORT", 5000)), allow_unsafe_werkzeug=True)
