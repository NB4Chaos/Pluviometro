import copy, csv, hmac, io, json, logging, math, os, sqlite3, sys, threading, time
from bisect import bisect_right
from collections import deque
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler

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
KEYRING_SERVICE = "Elus-CR1000Xe"
# Padrões DESTA instalação: valem só quando a senha vem do keyring (uso normal) e nem o ambiente nem o config.json definem o valor
INSTALL_DEFAULTS = {"address": "169.254.244.82", "protocol": "http", "profile": "programa_vazao"}
MASS_UNITS, TEMP_UNITS = ("mg", "g", "kg", "lb", "oz"), ("C", "F", "K")
FLOW_UNITS = ("L/min", "L/h", "mL/min", "mL/s", "m³/h", "m³/s", "m³/min", "kg/h", "kg/s")
FLOW_METHODS = ("analog", "pulse")
DUR_UNITS, TRIAL_MAX_MS = ("ms", "s", "min"), 6 * 3600 * 1000
METHOD_LABEL = {"analog": "analógico (4–20 mA)", "pulse": "pulsos"}
DEFAULTS = {"mass_unit": "g", "temp_unit": "C", "flow_unit": "L/min", "mass_decimals": 1, "temp_decimals": 2,
            "flow_decimals": 3, "density_g_cm3": None, "tip_resolution_mm": None,
            "default_range_s": 900,
            "catch_area_cm2": None,        # área da ABERTURA do coletor (cm²). Não é a da báscula.
            "flow_k_pulses_per_l": None,   # fator K do medidor por pulsos, sempre em pulsos/L (fonte única). Nunca presumido.
            "flow_k_unit": "pulsos/L",     # unidade em que o operador digita e vê o K (calc.K_UNITS; pulsos/kg = grandeza mássica)
            "flow_k_input": None,          # K como digitado, na unidade acima (fonte para recalcular pulsos/L quando a densidade muda)
            "time_resolution_ms": 100,     # resolução do tempo escolhida (100 | 10 | 1 ms); a EFETIVA é a do programa do datalogger
            "standard_id": None,           # padrão de vazão selecionado (tabela standards); seus parâmetros são copiados para as chaves acima
            "flow_method": "analog",       # método do cálculo da vazão: analog | pulse (o datalogger mede os dois canais)
            "flow_ma_tol": calc.MA_TOL,    # mA: tolerância nos limites 4 e 20 mA (dentro dela a escala fica presa no limite)
            "trial_duration_ms": 60000,    # duração dos ensaios; fixada no início de cada ensaio; mínimo = Scan do datalogger
            "trial_duration_unit": "s",    # unidade em que o operador digita (ms | s | min); internamente tudo é ms
            "trial_duration_s": 60,        # derivado de trial_duration_ms (compatibilidade com configurações e testes anteriores)
            "cor": {"q4": None, "q20": None, "unit": "L/min"},  # faixa 4–20 mA: definida pelo operador, nunca fixa no código
            "comm": {"protocol": "http", "address": "", "user": "", "profile": "programa_atual"}}
COLS = ["ts", "mass_g", "temp_c", "mass_status", "temp_status", "tips_total", "cor_ma", "cor_status",
        "flow_mode", "flow_pulses", "flow_hz", "pulses_total", "ma_code", "pulse_code", "flow_dt_ms", "flow_t1_ms", "flow_t2_ms", "flow_tres_ms"]
TIME_RES_MS = (100, 10, 1)            # resolução do tempo escolhida pelo operador (0,1 s | 0,01 s | 0,001 s); a efetiva é a do datalogger
INSERT_SQL = f"INSERT OR IGNORE INTO samples({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
UPDATE_SQL = f"UPDATE samples SET {','.join(c + '=?' for c in COLS[1:])} WHERE ts=?"
LAB = {"no_comm": "Sem comunicação", "invalid": "Leitura inválida", "out_of_range": "Fora da faixa",
       "fault": "Falha do sinal (< 3,6 mA)", "unavailable": "Canal indisponível no programa", "unconfigured": "Não configurado"}


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


# ---------- configuração (lida do disco uma vez; só save_cfg a atualiza) ----------
def _norm_duration(cfg, has_ms):
    """Duração do ensaio: interna em ms; `trial_duration_s` é derivado (inteiro quando exato). Configuração antiga só tinha segundos."""
    ms = cfg.get("trial_duration_ms") if has_ms else None
    if not isinstance(ms, (int, float)) or isinstance(ms, bool) or not 0 < ms <= TRIAL_MAX_MS:
        try:
            ms = int(round(float(cfg.get("trial_duration_s") or DEFAULTS["trial_duration_s"]) * 1000))
        except (TypeError, ValueError):
            ms = DEFAULTS["trial_duration_ms"]
    cfg["trial_duration_ms"] = int(ms)
    cfg["trial_duration_s"] = ms // 1000 if ms % 1000 == 0 else ms / 1000
    if cfg.get("trial_duration_unit") not in DUR_UNITS:
        cfg["trial_duration_unit"] = "s"
    return cfg


def _read_cfg():
    """Configuração = padrões + config.json. Chave nova ausente ou inválida volta ao padrão seguro (arquivos antigos continuam valendo)."""
    cfg, user = copy.deepcopy(DEFAULTS), {}
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if k not in ("comm", "cor")})
        cfg["comm"].update({k: v for k, v in user.get("comm", {}).items() if k != "mode"})
        cfg["cor"].update(user.get("cor", {}))
    if cfg.get("flow_method") not in FLOW_METHODS:
        cfg["flow_method"] = "analog"
    _norm_duration(cfg, "trial_duration_ms" in user)
    if cfg.get("flow_k_unit") not in calc.K_UNITS:
        cfg["flow_k_unit"] = "pulsos/L"
    tol = cfg.get("flow_ma_tol")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not 0 <= tol <= 0.2:
        cfg["flow_ma_tol"] = calc.MA_TOL
    k = cfg.get("flow_k_pulses_per_l")
    if k is not None and (isinstance(k, bool) or not isinstance(k, (int, float)) or not math.isfinite(k) or k <= 0):
        log.warning("Fator K inválido no config.json (%r): ignorado; a vazão por pulsos fica 'não configurada'", k)
        cfg["flow_k_pulses_per_l"] = None
    cfg.pop("flow_k_uncertainty_pct", None)   # chave de uma versão intermediária (31/10): o sistema não calcula incerteza
    if cfg.get("time_resolution_ms") not in TIME_RES_MS:
        cfg["time_resolution_ms"] = 100
    if cfg.get("flow_k_input") is None and cfg.get("flow_k_pulses_per_l"):   # configuração anterior: só pulsos/L gravado
        cfg["flow_k_input"] = calc.k_from_pulses_per_l(cfg["flow_k_pulses_per_l"], cfg["flow_k_unit"], cfg.get("density_g_cm3"))
    _recompute_k(cfg)
    return cfg, user.get("comm", {})


def _recompute_k(cfg):
    """K interno (pulsos/L) a partir do que foi digitado e da unidade; pulsos/kg usa a densidade configurada (sem ela fica None)."""
    if cfg.get("flow_k_input") is not None:
        cfg["flow_k_pulses_per_l"] = calc.k_to_pulses_per_l(cfg["flow_k_input"], cfg["flow_k_unit"], cfg.get("density_g_cm3"))


_cfg, _user_comm = _read_cfg()


def load_cfg():
    return _cfg


def save_cfg(cfg):
    """Grava o config.json de forma atômica (queda de energia não deixa o arquivo pela metade) e passa a usá-lo."""
    global _cfg
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CFG_PATH)
    _cfg = cfg


def load_credentials():
    """Usuário e senha do CR1000Xe. Uso normal: Gerenciador de Credenciais do Windows (keyring, serviço Elus-CR1000Xe).
    A senha nunca fica em arquivo. DATALOGGER_PASSWORD já no ambiente (testes automáticos) dispensa o keyring.
    Devolve a origem ('keyring' | 'ambiente'); sem credencial, registra o motivo no log e encerra."""
    if os.environ.get("DATALOGGER_PASSWORD"):
        return "ambiente"
    try:
        import keyring
        user = keyring.get_password(KEYRING_SERVICE, "DATALOGGER_USER")
        pw = keyring.get_password(KEYRING_SERVICE, "DATALOGGER_PASSWORD")
    except Exception as e:   # pacote ausente ou cofre inacessível
        log.error("Não consegui ler o Gerenciador de Credenciais do Windows: %s", e)
        user = pw = None
    if not user or not pw:
        log.error("Credenciais do CR1000Xe não encontradas no Gerenciador de Credenciais do Windows (serviço %s, chaves "
                  "DATALOGGER_USER e DATALOGGER_PASSWORD). Cadastre as duas e inicie o servidor de novo.", KEYRING_SERVICE)
        raise SystemExit(2)
    os.environ["DATALOGGER_USER"], os.environ["DATALOGGER_PASSWORD"] = user, pw
    return "keyring"


MODE = "cr1000x"  # único modo: não existe mais geração de dados fictícios
CRED_SOURCE = load_credentials()
# Conexão: variável de ambiente > config.json > padrão desta instalação (só no uso normal, com keyring) > padrão do código.
_comm, _origin = dict(load_cfg()["comm"]), {}
for _k, _env in (("address", "DATALOGGER_HOST"), ("user", "DATALOGGER_USER"), ("protocol", "DATALOGGER_PROTOCOL"), ("profile", "CR1000X_PROFILE")):
    if os.environ.get(_env):
        _comm[_k], _origin[_k] = os.environ[_env], _env
    elif _user_comm.get(_k):
        _origin[_k] = "config.json"
    elif CRED_SOURCE == "keyring" and _k in INSTALL_DEFAULTS:
        _comm[_k], _origin[_k] = INSTALL_DEFAULTS[_k], "padrão da instalação"
    else:
        _origin[_k] = "padrão"
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
for _col, _typ in (("cor_ma", "REAL"), ("cor_status", "TEXT"), ("flow_mode", "TEXT"), ("flow_pulses", "REAL"), ("flow_hz", "REAL"),
                   ("pulses_total", "INTEGER"), ("ma_code", "INTEGER"), ("pulse_code", "INTEGER"), ("flow_dt_ms", "INTEGER"),
                   ("flow_t1_ms", "INTEGER"), ("flow_t2_ms", "INTEGER"), ("flow_tres_ms", "INTEGER")):
    if _col not in _have:  # bancos antigos ganham as colunas novas sem perder dados
        db.execute(f"ALTER TABLE samples ADD COLUMN {_col} {_typ}")
# padrões de vazão do laboratório (cadastro único; o ensaio congela uma CÓPIA dos parâmetros usados, então editar/excluir aqui não altera o histórico)
db.execute("""CREATE TABLE IF NOT EXISTS standards(id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT NOT NULL COLLATE NOCASE UNIQUE,
  brand TEXT, model TEXT, sn TEXT, manufacturer TEXT, description TEXT, notes TEXT, acq TEXT NOT NULL,
  k_value REAL, k_unit TEXT, pulse_cfg TEXT, q4 REAL, q20 REAL, range_unit TEXT, signal_type TEXT, created_ts INTEGER, updated_ts INTEGER)""")
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
SCAN_MS = int(dl.profile.get("scan_ms") or 1000)   # intervalo do Scan do programa CRBasic: resolução temporal efetiva dos registros
trials = Trials(db, lock, load_cfg, latest_sample_ts, scan_ms=SCAN_MS, get_standard=lambda sid: std_get(sid))


# ---------- Medidor de Vazão: os dois canais (4–20 mA em RG1 e pulsos em P2) -> L/min, sempre a partir do dado bruto ----------
def flow_cfg(cfg):
    """Parâmetros do medidor no formato de calc.flow_reading (fonte única: config.json)."""
    mass_no_rho = calc.k_is_mass(cfg["flow_k_unit"]) and cfg.get("flow_k_input") and not cfg["flow_k_pulses_per_l"]
    return {"q4": cfg["cor"]["q4"], "q20": cfg["cor"]["q20"], "range_unit": cfg["cor"]["unit"], "density": cfg["density_g_cm3"],
            "k_pulses_per_l": cfg["flow_k_pulses_per_l"], "ma_tol": cfg["flow_ma_tol"],
            "k_reason": "fator K em pulsos/kg: informe a densidade da água em Configurações para obter a vazão volumétrica" if mass_no_rho else None}


def flow_value(mode, ma, hz, status, cfg=None, fc=None):
    """(vazão em L/min, estado detalhado) de uma amostra GRAVADA, recalculada do dado bruto com a configuração atual.
    `mode` = método usado na amostra; amostras antigas sem método contam como analógicas (único modo que existia).
    `fc` = flow_cfg já montado: quem converte muitas linhas monta uma vez só."""
    if status is None:
        return None, "na"
    fc = fc or flow_cfg(cfg or load_cfg())
    if status != "ok":
        if status == "out_of_range" and (mode or "analog") == "analog" and ma is not None:
            return None, "fault" if calc.classify_ma(ma, fc["ma_tol"])[0] == "fault" else "out_of_range"
        return None, status
    if mode == "pulse":
        if hz is None:
            return None, "invalid"
        k = fc["k_pulses_per_l"]
        return (hz / k * 60.0, "ok") if k else (None, "unconfigured")
    cls, eff = calc.classify_ma(ma, fc["ma_tol"])
    if eff is None:
        return None, {"fault": "fault", "invalid": "invalid"}.get(cls, "out_of_range")
    v = calc.analog_flow_l_min(eff, fc["q4"], fc["q20"], fc["range_unit"], fc["density"])
    return (v, "ok") if v is not None else (None, "unconfigured")


def flow_stats(where, a, cfg):
    """Média/mín/máx da vazão (L/min) no período. Pulso e mA são lineares: média da vazão = vazão da média.
    No analógico a escala usa o mA preso a 4–20 (amostras válidas dentro da tolerância); a média em mA mostrada é a bruta."""
    base = f"FROM samples WHERE {where} AND cor_status='ok'"
    n_out = q(f"SELECT COUNT(*) FROM samples WHERE {where} AND cor_status='out_of_range'", a)[0][0]
    pu = q(f"SELECT AVG(flow_hz),MIN(flow_hz),MAX(flow_hz),COUNT(flow_hz) {base} AND flow_mode='pulse'", a)[0]
    clamp = "MIN(MAX(cor_ma,4.0),20.0)"
    an = q(f"SELECT AVG(cor_ma),MIN(cor_ma),MAX(cor_ma),COUNT(cor_ma),AVG({clamp}),MIN({clamp}),MAX({clamp}) {base} "
           f"AND COALESCE(flow_mode,'analog')='analog'", a)[0]
    f = lambda v: None if v is None else round(v, 3)       # mA e Hz: 3 casas (resolução do sinal)
    fq = lambda v: None if v is None else round(v, 9)      # vazão em L/min: sem arredondar antes da conversão de unidade na tela
    ma = {"avg": f(an[0]), "min": f(an[1]), "max": f(an[2]), "n": an[3], "n_out": n_out}
    out = {"ma": ma, "flow": None, "pulses": None, "mode": "pulse" if pu[3] > an[3] else "analog" if an[3] else None,
           "mixed": bool(pu[3] and an[3])}
    if pu[3]:
        out["pulses"] = {"avg_hz": f(pu[0]), "n": pu[3]}
    use_pulse = out["mode"] == "pulse"
    k, cor = cfg["flow_k_pulses_per_l"], cfg["cor"]
    if use_pulse and k:
        out["flow"] = {"avg": fq(pu[0] / k * 60), "min": fq(pu[1] / k * 60), "max": fq(pu[2] / k * 60), "unit": "L/min"}
    elif not use_pulse and an[3] and cor["q4"] is not None and cor["q20"] is not None:
        vals = [calc.analog_flow_l_min(m, cor["q4"], cor["q20"], cor["unit"], cfg["density_g_cm3"]) for m in (an[4], an[5], an[6])]
        if None not in vals:
            lo, hi = sorted([vals[1], vals[2]])
            out["flow"] = {"avg": fq(vals[0]), "min": fq(lo), "max": fq(hi), "unit": "L/min"}
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
        "rows": 0, "out_of_order": 0, "merged": 0, "stalls": 0, "empty_polls": 0, "last_ts": None, "live": True,
        "started": int(time.time() * 1000), "health": {}}
link = {"last_try": None, "last_ok": None, "error": None}  # estado real da comunicação com o datalogger
# Método do medidor: "requested" = escolhido e gravado; "active" = só depois que uma amostra do datalogger foi calculada com ele
FLOW = {"requested": load_cfg()["flow_method"], "active": None, "changed_at": int(time.time() * 1000), "confirmed_at": None,
        "no_pulse_streak": 0}
XCHECK_MIN_FRAC = 0.02   # comparação entre canais: corrente indicando > 2 % do span com zero pulsos...
XCHECK_STREAK = 5        # ...por 5 amostras seguidas => "pulsos ausentes" (cabo solto, saída digital desligada ou K errado)


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
    return {"connected": fresh, "last_try_ts": link["last_try"], "last_ok_ts": ok, "error": link["error"],
            "gaps": dl.gaps, "flow_integrated": dl.has_flow or bool(dl.profile.get("cor")), "flow_has": list(dl.flow_has),
            "data_fresh": rx is not None and now - rx < 10_000,        # chegou amostra NOVA nos últimos 10 s
            "last_rx_ts": rx, "latency_s": round(pct(lat, .5) / 1000, 1) if lat else None,
            "clock_skew_s": diag["health"].get("clock_offset_s")}   # desvio real do relógio (ClockCheck), não a latência


_MERGE_GROUPS = (("mass_status", "mass_g"), ("temp_status", "temp_c"),
                 ("cor_status", "cor_ma", "flow_mode", "flow_pulses", "flow_hz", "pulses_total", "ma_code", "pulse_code", "flow_dt_ms"))


def merge_sample(old, new):
    """Mesma amostra (mesmo horário) lida de novo: cada grupo (balança, termopar, medidor) só é trocado se a linha gravada não
    tinha leitura válida e a nova tem. Uma releitura nunca piora o que já foi gravado (antes, um INSERT OR REPLACE com a
    junção vazia de uma releitura apagava temperatura e vazão de horas de histórico)."""
    o, n = dict(zip(COLS, old)), dict(zip(COLS, new))
    for st, *cols in _MERGE_GROUPS:
        if o[st] != "ok" and n[st] == "ok":
            for c in (st, *cols):
                o[c] = n[c]
    o["tips_total"] = n["tips_total"]   # recontado agora, com as basculadas já deduplicadas pela chave
    return tuple(o[c] for c in COLS)


def eval_flow(r, method, fc):
    """Os dois canais da amostra avaliados a partir do dado bruto: (leitura do método escolhido, {canal disponível: leitura}).
    (None, {}) = o programa não tem medidor de vazão (aguardando integração)."""
    if not dl.has_flow or r.cor_status is None:
        return None, {}
    has, comm = set(r.flow_has), ("ok" if r.cor_status == "ok" else "no_comm")
    ev = {m: calc.flow_reading(m, has, comm, r.cor_ma, r.flow_pulses, r.flow_pulse_code, r.flow_dt_ms, fc) for m in FLOW_METHODS}
    return ev[method], {m: v for m, v in ev.items() if m in has}


def crosscheck(ev):
    """Comparação entre os canais, só diagnóstico (nunca altera a leitura). Corrente indicando vazão (> 2 % do span acima de
    4 mA) com zero pulsos por XCHECK_STREAK amostras seguidas => suspeita de pulsos ausentes, que a contagem sozinha não detecta."""
    a, p = ev.get("analog"), ev.get("pulse")
    if not a or not p:
        FLOW["no_pulse_streak"] = 0
        return None
    out = {"analog_lmin": a["lmin"], "pulse_lmin": p["lmin"], "diff_pct": None, "suspect": None}
    if a["lmin"] is not None and p["lmin"] is not None and abs(a["lmin"]) > 1e-9:
        out["diff_pct"] = 100.0 * (p["lmin"] - a["lmin"]) / a["lmin"]
    flowing = a["ma_class"] in ("ok", "high") and a["ma"] > 4.0 + 16.0 * XCHECK_MIN_FRAC
    if flowing and p["pulses"] == 0 and p["state"] in ("ok", "unconfigured"):
        FLOW["no_pulse_streak"] += 1
    else:
        FLOW["no_pulse_streak"] = 0
    if FLOW["no_pulse_streak"] >= XCHECK_STREAK:
        out["suspect"] = "no_pulses"
    return out


FLOW_KEYS = ("state", "reason", "lmin", "clamp", "ma", "ma_class", "pulses", "hz", "window_s", "window_assumed", "resolution_lmin")


def flow_payload(act, ev):
    """Bloco 'flow' do evento ao vivo: tudo o que a tela precisa para mostrar o medidor sem decidir nada sozinha."""
    base = {"requested": FLOW["requested"], "active": FLOW["active"], "confirmed": FLOW["active"] == FLOW["requested"],
            "changed_at": FLOW["changed_at"], "locked": trials.has_running()}
    if act is None:
        return base | {"integrated": False, "has": [], "state": "na"}
    return base | {"integrated": True, "method": act["method"], "has": sorted(ev), **{k: act[k] for k in FLOW_KEYS},
                   "channels": {m: {k: v[k] for k in FLOW_KEYS} for m, v in ev.items()}, "crosscheck": crosscheck(ev)}


def store_batch(batch, now):
    """Grava um lote de Readings numa única transação. Devolve (linhas gravadas, eventos realmente novos, avaliações do medidor).
    As basculadas entram ANTES das amostras, para que `tips_total` de cada amostra já as inclua."""
    events, rows, flows = [], [], []
    cfg = load_cfg()
    fc, method = flow_cfg(cfg), cfg["flow_method"]
    with lock:
        for r in batch:
            for item in r.tips:  # cada basculada é um evento com id próprio; o INSERT OR IGNORE recusa repetidos pela chave
                tts, key = item if isinstance(item, tuple) else (item, None)
                cur = db.execute("INSERT OR IGNORE INTO tips(ts,src) VALUES(?,?)", (tts, key))
                if cur.rowcount:
                    events.append({"id": cur.lastrowid, "ts": tts})
        since = count_since()
        samples = [r for r in batch if r.sample]
        if samples:
            tss = [r.ts or now for r in samples]
            lo, hi = min(tss), max(tss)
            # total desde "Zerar contagem": UMA contagem por lote + posição de cada amostra entre as basculadas do lote
            base = db.execute("SELECT COUNT(*) FROM tips WHERE ts>=? AND ts<?", (since, lo)).fetchone()[0]
            near = [t for (t,) in db.execute("SELECT ts FROM tips WHERE ts>=? AND ts<=? ORDER BY ts", (max(since, lo), hi))]
            for r, ts in zip(samples, tss):
                n = base + bisect_right(near, ts)
                act, ev = eval_flow(r, method, fc)
                hz = ev["pulse"]["hz"] if "pulse" in ev else r.flow_hz   # os dois canais ficam gravados, qualquer que seja o método
                full = (ts, r.mass_g, r.temp_c, r.mass_status, r.temp_status, n, r.cor_ma,
                        calc.stored_status(act) if act else None, method if act else None, r.flow_pulses, hz,
                        r.flow_pulses_total, r.flow_ma_code, r.flow_pulse_code, r.flow_dt_ms, r.flow_t1_ms, r.flow_t2_ms, r.flow_tres_ms)
                if not db.execute(INSERT_SQL, full).rowcount:   # horário já gravado (releitura): completa, nunca piora
                    old = tuple(db.execute(f"SELECT {','.join(COLS)} FROM samples WHERE ts=?", (ts,)).fetchone())
                    merged = merge_sample(old, full)
                    if merged != old:
                        db.execute(UPDATE_SQL, merged[1:] + (ts,))
                        diag["merged"] += 1
                    full = merged
                rows.append(full)
                flows.append((act, ev))
        db.commit()
    return rows, events, flows


def emit_trial():
    st = trials.status()
    sio.emit("trial", st)
    sio.emit("flow", flow_status())   # início/fim de ensaio trava/libera a troca do método do medidor
    return st


class Pacer:
    """Agenda das consultas: horário absoluto (o atraso de cada espera não se acumula) com a fase travada logo depois da
    gravação do Scan no datalogger.

    Antes: espera relativa de 1 s; o pequeno excesso de cada sleep acumulava (~0,5 ms por ciclo), a latência subia de
    0,16 s a ~1,1 s em dente de serra e, a cada volta, o servidor pedia um registro ainda não gravado.
    Agora: com amostra nova, a próxima consulta vem 1 período depois do início desta, menos CREEP (a fase anda devagar
    para mais cedo); se a consulta chega antes da gravação (nenhuma amostra nova), tenta de novo em RETRY. Em regime:
    ~1 consulta por Scan, perto do instante da gravação. Depois de MAX_RETRY tentativas sem dado novo (programa parado,
    datalogger sem gravar), volta ao período normal: nunca martela o datalogger."""
    CREEP, RETRY, MAX_RETRY = 0.004, 0.12, 2

    def __init__(self, period):
        self.period, self.next, self.empty = period, time.monotonic(), 0

    def delay(self):
        return max(0.0, self.next - time.monotonic())

    def done(self, started, got_new):
        if got_new or self.period > 2:
            self.empty = 0
            self.next = started + self.period - (self.CREEP if got_new else 0.0)
        else:
            self.empty += 1
            self.next = time.monotonic() + (self.RETRY if self.empty <= self.MAX_RETRY else self.period)

    def now(self):
        self.next = time.monotonic()


def acquire():
    summary_t, health_t, pacer = time.time(), 0.0, Pacer(SAMPLE_PERIOD)
    while True:   # a thread de aquisição nunca morre: qualquer erro inesperado é registrado e o ciclo seguinte continua
        try:
            summary_t, health_t = _acquire_once(summary_t, health_t, pacer)
        except Exception:
            log.exception("Erro inesperado no ciclo de aquisição; continuando")
            sio.sleep(SAMPLE_PERIOD)
            pacer.now()


def _confirm_method(act, t_rx):
    """O método só vira 'ativo' quando uma amostra do datalogger foi calculada com ele (canal presente no programa)."""
    if act is None:
        return
    with flow_lock:
        confirm = act["method"] == FLOW["requested"] and act["state"] != "unavailable" and FLOW["active"] != act["method"]
        lost = act["state"] == "unavailable" and FLOW["active"] is not None
        if confirm:
            FLOW["active"], FLOW["confirmed_at"] = act["method"], t_rx
        elif lost:
            FLOW["active"], FLOW["confirmed_at"] = None, None
    if confirm:
        log.info("medidor de vazão: método %s confirmado por dado do datalogger", METHOD_LABEL[act["method"]])
    elif lost:
        log.warning("medidor de vazão: o programa do datalogger deixou de fornecer o canal do método %s", METHOD_LABEL[act["method"]])
    if confirm or lost:
        sio.emit("flow", flow_status())


def _acquire_once(summary_t, health_t, pacer):
    sio.sleep(pacer.delay())
    if True:
        m0, t0 = time.monotonic(), time.time()
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
            pacer.now()
            try:
                trials.tick(int(time.time() * 1000))
            except Exception:
                log.exception("Falha ao avaliar o ensaio")
            return summary_t, health_t
        batch = got if isinstance(got, list) else [got]
        diag["live"] = len(batch) <= 2
        rows, events, flows = store_batch(batch, now)
        if not rows:
            diag["empty_polls"] += 1
        pacer.done(m0, bool(rows))
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
            act, ev = flows[-1]
            _confirm_method(act, t_rx)
            fp = flow_payload(act, ev)
            s = dict(zip(COLS, last), last_tip_ts=last_tip(), new_tips=events, flow_lmin=fp.get("lmin"), flow_state=fp["state"],
                     rx_ts=t_rx, flow=fp)
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
                if fin:
                    sio.emit("flow", flow_status())
        except Exception:
            log.exception("Falha ao avaliar o ensaio")
        if time.time() - health_t > 3600:   # diagnóstico leve (2 consultas) uma vez por hora, em outra thread: nunca atrasa a aquisição
            health_t = time.time()
            sio.start_background_task(_health)
        if time.time() - summary_t > 60:   # um resumo por minuto: suficiente para diagnosticar sem inflar o log
            summary_t = time.time()
            lat, pm = list(diag["lat_ms"]), list(diag["poll_ms"])
            log.info("resumo: consultas=%d (sem dado novo=%d) erros=%d amostras=%d lat(PC-datalogger) p50=%s p95=%s ms consulta p50=%s "
                     "p95=%s ms lacunas=%d reinicios=%d releituras-completadas=%d sem-correspondencia=%s", diag["polls"],
                     diag["empty_polls"], diag["errors"], diag["rows"], pct(lat, .5), pct(lat, .95), _ms(pct(pm, .5)), _ms(pct(pm, .95)),
                     dl.gaps, dl.restarts, diag["merged"], dl.join_miss)
        return summary_t, health_t


def _ms(v):
    return None if v is None else round(v)


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
                   stats=stats("ts>=? AND ts<?", [fr, to]), grav=period_grav(fr, to), resolution=res, area_cm2=cfg["catch_area_cm2"],
                   flow=flow_status())


@app.get("/api/series")
def series():
    fr, to = rng()
    cfg = load_cfg()
    rows = q("SELECT ts,mass_g,temp_c,cor_ma,cor_status,flow_mode,flow_hz FROM samples WHERE ts>=? AND ts<? ORDER BY ts", (fr, to))
    ts = [r[0] for r in rows]
    fc, memo, fl = flow_cfg(cfg), {}, []
    for r in rows:   # a vazão só depende do método, do canal que ele usa e do estado: valor repetido não é recalculado
        x = r[6] if r[5] == "pulse" else r[3]
        if not x:    # None, 0,0 ou -0,0 (o sinal do zero chega ao JSON e as duas chaves seriam iguais): calcula direto
            fl.append(flow_value(r[5], r[3], r[6], r[4], fc=fc)[0])
            continue
        key = (r[5], x, r[4])
        fv = memo.get(key, memo)
        if fv is memo:
            fv = memo[key] = flow_value(r[5], r[3], r[6], r[4], fc=fc)[0]
        fl.append(fv)
    cols = {"mass": [r[1] for r in rows], "temp": [r[2] for r in rows], "cor_ma": [r[3] if r[4] == "ok" else None for r in rows], "flow": fl,
            "hz": [r[6] if r[4] == "ok" and r[5] == "pulse" else None for r in rows]}
    n = len(ts)
    step = n // 600 + 1
    out = {"t": [], **{k: [] for k in cols}}
    for i in range(0, n, step):   # no máx. ~600 pontos: cada ponto = média das leituras válidas do trecho
        j = min(i + step, n)
        out["t"].append(ts[j - 1])
        for k, v in cols.items():
            vals = [y for y in v[i:j] if y is not None]
            out[k].append(round(sum(vals) / len(vals), 9 if k == "flow" else 3) if vals else None)   # vazão em L/min sem arredondamento prematuro
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
    fc = flow_cfg(cfg)
    for r in rows:
        d = dict(zip(COLS, r))
        d["flow_lmin"], d["flow_state"] = flow_value(d["flow_mode"], d["cor_ma"], d["flow_hz"], d["cor_status"], fc=fc)
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
        + (["Medidor de Vazão (mA)", "Pulsos (contagem em 1 s)", "Frequência (Hz)", "Vazão (L/min)", "Método do cálculo",
            "Janela de contagem (s)", "Pulsos acumulados (datalogger)"] if c_on else []) \
        + (["Basculadas (total desde zerar)", "Precipitação acumulada desde zerar (mm)"] if p_on else []) + ["Estado"]
    out, fc = [], flow_cfg(cfg)
    for ts, m, t, ms, tst, n, ma, cs, mode, pul, hz, ptot, _mc, _pc, dtms in rows:
        fl, fst = flow_value(mode, ma, hz, cs, fc=fc)
        out.append([datetime.fromtimestamp(ts / 1000)] + ([m] if m_on else []) + ([t] if t_on else [])
                   + ([ma, pul, hz, fl, METHOD_LABEL.get(mode, ""), None if dtms is None else dtms / 1000, ptot] if c_on else [])
                   + ([n, round(n * res, 3) if res else None] if p_on else [])
                   + [estado(ms if m_on else "ok", tst if t_on else "ok", ("fault" if fst == "fault" else cs) if c_on else "ok")])
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
    if kind == "flow" and dl.has_flow and FLOW["active"] != FLOW["requested"]:   # nunca ensaiar com um método ainda não confirmado
        return jsonify(error=f"O método {METHOD_LABEL[FLOW['requested']]} do medidor ainda não foi confirmado por dado do datalogger. "
                             "Aguarde a confirmação no card de Vazão ou volte ao método anterior."), 409
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
            "Medidor de Vazão (mA)", "Estado do medidor", "Modo do medidor", "Pulsos (contagem em 1 s)", "Frequência (Hz)", "Vazão (L/min)",
            "Pulsos acumulados (datalogger)", "Código do canal analógico", "Código do canal de pulsos", "Janela de contagem (ms)"]
    rows = [[datetime.fromtimestamp(r[0] / 1000), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
             calc.flow_from_sample(r[7] or "analog", r[6] if r[6] is not None else "ok", r[9], r[5], cfg.get("k_pulses_per_l"),
                                   cfg.get("q4"), cfg.get("q20"), cfg.get("range_unit"), cfg.get("density"), cfg.get("ma_tol", 0.0)),
             r[10], r[11], r[12], r[13]] for r in s]
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
                   empty_polls=diag["empty_polls"], merged=diag["merged"], flow=flow_status(),
                   gaps=dl.gaps, restarts=dl.restarts, stalls=diag["stalls"], join_miss=dl.join_miss, health=diag["health"], sample_period_s=SAMPLE_PERIOD, started=diag["started"],
                   lat_ms={"p50": pct(lat, .5), "p95": pct(lat, .95), "max": max(lat) if lat else None},
                   poll_ms={"p50": pct(pm, .5), "p95": pct(pm, .95), "max": max(pm) if pm else None},
                   write_protected=bool(DASHBOARD_TOKEN))


# ---------- configuração ----------
def public_cfg(cfg):
    c = copy.deepcopy(cfg)
    c["comm"].pop("address", None)   # o endereço do datalogger não é exibido nem editável pela interface
    lt = state["latest"] or {}
    tres = lt.get("flow_tres_ms") or SCAN_MS   # resolução EFETIVA dos carimbos de tempo: Scan rápido da v5, ou o Scan do programa
    return c | {"active_mode": MODE, "write_protected": bool(DASHBOARD_TOKEN),
                "flow_k_value": cfg.get("flow_k_input") if cfg.get("flow_k_input") is not None else calc.k_from_pulses_per_l(cfg["flow_k_pulses_per_l"], cfg["flow_k_unit"]),
                "flow_k_mass": calc.k_is_mass(cfg["flow_k_unit"]),
                "flow_k_units": list(calc.K_UNITS), "ma_fault": calc.MA_FAULT, "scan_ms": SCAN_MS, "duration_min_ms": SCAN_MS,
                "timing_res_ms": int(tres), "time_resolution_options_ms": list(TIME_RES_MS),
                "standard": std_get(cfg.get("standard_id")) if cfg.get("standard_id") else None}


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
    """Atualização PARCIAL: cada campo ausente preserva o valor salvo; "" apaga um parâmetro numérico opcional."""
    d, cfg = request.get_json(silent=True) or {}, copy.deepcopy(load_cfg())
    try:
        for k, allowed, label in (("mass_unit", MASS_UNITS, "massa"), ("temp_unit", TEMP_UNITS, "temperatura"), ("flow_unit", FLOW_UNITS, "vazão")):
            if k in d:
                if d[k] not in allowed:
                    raise ValueError(f"Unidade de {label} inválida.")
                cfg[k] = d[k]
        for k, label in (("mass_decimals", "Casas decimais da massa"), ("temp_decimals", "Casas decimais da temperatura"),
                         ("flow_decimals", "Casas decimais da vazão")):
            if k in d:
                cfg[k] = whole(d[k], label, 0, 6)
        for k, label in (("tip_resolution_mm", "Resolução"), ("density_g_cm3", "Densidade"), ("catch_area_cm2", "Área de captação")):
            if k in d:
                cfg[k] = positive(d[k], label)
        if "flow_k" in d:   # fator K como o operador digita: {"value": ..., "unit": "pulsos/L" | "pulsos/m³" | "L/pulso" | "mL/pulso"}
            fk = d["flow_k"] or {}
            unit = fk.get("unit", cfg["flow_k_unit"])
            if unit not in calc.K_UNITS:
                raise ValueError("Unidade do fator K inválida.")
            v = positive(fk.get("value"), "Fator K")
            cfg["flow_k_input"], cfg["flow_k_unit"] = v, unit
            cfg["flow_k_pulses_per_l"] = None if v is None else calc.k_to_pulses_per_l(v, unit, cfg["density_g_cm3"])
        elif "flow_k_pulses_per_l" in d:   # formato antigo: sempre pulsos/L
            cfg["flow_k_pulses_per_l"] = positive(d["flow_k_pulses_per_l"], "Fator K")
            cfg["flow_k_input"], cfg["flow_k_unit"] = cfg["flow_k_pulses_per_l"], "pulsos/L"
        if "flow_k_unit" in d and "flow_k" not in d:
            if d["flow_k_unit"] not in calc.K_UNITS:
                raise ValueError("Unidade do fator K inválida.")
            cfg["flow_k_unit"] = d["flow_k_unit"]
        if "time_resolution_ms" in d:
            tr = whole(d["time_resolution_ms"], "Resolução do tempo", 1, 100)
            if tr not in TIME_RES_MS:
                raise ValueError("Resolução do tempo: use 100 ms (0,1 s), 10 ms (0,01 s) ou 1 ms (0,001 s).")
            cfg["time_resolution_ms"] = tr
        _recompute_k(cfg)   # densidade ou K mudaram: K interno (pulsos/L) acompanha; pulsos/kg sem densidade fica indisponível
        if "flow_ma_tol" in d:
            tol = num(d["flow_ma_tol"], "Tolerância nos limites de 4 e 20 mA")
            if not 0 <= tol <= 0.2:
                raise ValueError("Tolerância nos limites de 4 e 20 mA: use de 0 a 0,2 mA.")
            cfg["flow_ma_tol"] = tol
        if "default_range_s" in d:
            cfg["default_range_s"] = whole(d["default_range_s"], "Período inicial", 1, 31 * 86400)
        # ---- duração do ensaio: internamente em ms; mínimo = resolução efetiva do datalogger (Scan); nunca arredondada ao salvar
        if "trial_duration_ms" in d:
            ms = whole(d["trial_duration_ms"], "Duração do ensaio", 1, TRIAL_MAX_MS)
            if ms < SCAN_MS:
                raise ValueError(f"Duração do ensaio: mínimo {SCAN_MS} ms, que é a resolução efetiva do datalogger (Scan de {SCAN_MS} ms). "
                                 "Valores menores não podem ser medidos com o programa atual.")
            cfg["trial_duration_ms"] = ms
        elif "trial_duration_s" in d:
            cfg["trial_duration_ms"] = whole(d["trial_duration_s"], "Duração do ensaio", 1, TRIAL_MAX_MS // 1000) * 1000
            if cfg["trial_duration_ms"] < SCAN_MS:
                raise ValueError(f"Duração do ensaio: mínimo {SCAN_MS} ms (resolução efetiva do datalogger).")
        if "trial_duration_unit" in d:
            if d["trial_duration_unit"] not in DUR_UNITS:
                raise ValueError("Unidade da duração inválida (ms | s | min).")
            cfg["trial_duration_unit"] = d["trial_duration_unit"]
        _norm_duration(cfg, True)
        if "cor" in d:
            c, cur = d["cor"] or {}, cfg["cor"]
            unit = c.get("unit", cur["unit"])
            if unit not in FLOW_UNITS:
                raise ValueError("Unidade de vazão da faixa inválida.")
            q4 = opt_num(c["q4"], "Vazão em 4 mA") if "q4" in c else cur["q4"]
            q20 = opt_num(c["q20"], "Vazão em 20 mA") if "q20" in c else cur["q20"]
            if (q4 is None) != (q20 is None):
                raise ValueError("Informe a vazão em 4 mA e em 20 mA, ou deixe as duas vazias.")
            if q4 is not None and q4 == q20:
                raise ValueError("A vazão em 20 mA não pode ser igual à vazão em 4 mA.")
            cfg["cor"] = {"q4": q4, "q20": q20, "unit": unit}
        method = d.get("flow_method")
        if method is not None and method != FLOW["requested"]:
            err = method_refusal(method)
            if err:
                raise ValueError(err[1])
            cfg["flow_method"] = method
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
    except (KeyError, TypeError, AttributeError):
        return jsonify(error="Valores inválidos."), 400
    except ValueError as e:
        return jsonify(error=str(e)), 400
    save_cfg(cfg)
    if cfg["flow_method"] != FLOW["requested"]:
        set_requested(cfg["flow_method"])
    log.info("configuração salva (resolução=%s, área=%s, K=%s pulsos/L (exibido em %s), faixa 4–20 mA=%s..%s %s, tolerância=%s mA, "
             "duração do ensaio=%s ms)", cfg["tip_resolution_mm"], cfg["catch_area_cm2"], cfg["flow_k_pulses_per_l"], cfg["flow_k_unit"],
             cfg["cor"]["q4"], cfg["cor"]["q20"], cfg["cor"]["unit"], cfg["flow_ma_tol"], cfg["trial_duration_ms"])
    pc = public_cfg(cfg)
    sio.emit("config", pc)   # outras abas abertas passam a usar a mesma configuração
    return jsonify(pc)


# ---------- padrões de vazão (cadastro único do laboratório) ----------
STD_COLS = ("id", "tag", "brand", "model", "sn", "manufacturer", "description", "notes", "acq", "k_value", "k_unit", "pulse_cfg",
            "q4", "q20", "range_unit", "signal_type", "created_ts", "updated_ts")
STD_TEXT = ("tag", "brand", "model", "sn", "manufacturer", "description", "notes", "pulse_cfg", "signal_type")


def std_row(r):
    return dict(zip(STD_COLS, r)) if r else None


def std_get(sid):
    try:
        return std_row(q(f"SELECT {','.join(STD_COLS)} FROM standards WHERE id=?", (int(sid),))[0]) if sid is not None else None
    except (IndexError, ValueError, TypeError):
        return None


def std_list(search=""):
    s = f"%{search.strip()}%" if search and search.strip() else None
    where = "WHERE tag LIKE ? OR brand LIKE ? OR model LIKE ? OR sn LIKE ?" if s else ""
    return [std_row(r) for r in q(f"SELECT {','.join(STD_COLS)} FROM standards {where} ORDER BY tag COLLATE NOCASE", (s, s, s, s) if s else ())]


def std_validate(d, cfg):
    """Campos do cadastro -> dicionário pronto para gravar. Só os parâmetros do tipo de saída escolhido são guardados."""
    out = {k: (str(d.get(k) or "").strip() or None) for k in STD_TEXT}
    if not out["tag"]:
        raise ValueError("Informe a TAG do padrão.")
    if len(out["tag"]) > 40:
        raise ValueError("TAG: no máximo 40 caracteres.")
    acq = d.get("acq")
    if acq not in FLOW_METHODS:
        raise ValueError("Tipo de aquisição: use 'pulse' (pulsos) ou 'analog' (4–20 mA).")
    out["acq"] = acq
    out.update(k_value=None, k_unit=None, q4=None, q20=None, range_unit=None)
    if acq == "pulse":
        unit = d.get("k_unit") or "pulsos/L"
        if unit not in calc.K_UNITS:
            raise ValueError("Unidade do fator K inválida.")
        v = positive(d.get("k_value"), "Fator K")
        if v is None:
            raise ValueError("Informe o fator K do padrão por pulsos.")
        out.update(k_value=v, k_unit=unit)
        out["pulse_cfg"] = out["pulse_cfg"]
        out["signal_type"] = None
    else:
        unit = d.get("range_unit") or "L/min"
        if unit not in FLOW_UNITS:
            raise ValueError("Unidade da faixa 4–20 mA inválida.")
        q4, q20 = opt_num(d.get("q4"), "Valor em 4 mA"), opt_num(d.get("q20"), "Valor em 20 mA")
        if q4 is None or q20 is None:
            raise ValueError("Informe os valores correspondentes a 4 mA e a 20 mA.")
        if q4 == q20:
            raise ValueError("O valor em 20 mA precisa ser diferente do valor em 4 mA.")
        out.update(q4=q4, q20=q20, range_unit=unit, pulse_cfg=None)
    return out


def std_apply(cfg, s):
    """Copia os parâmetros do padrão para a configuração ativa (o ensaio congela a própria cópia em trials.start)."""
    cfg["standard_id"] = s["id"]
    if s["acq"] == "pulse":
        cfg["flow_k_input"], cfg["flow_k_unit"] = s["k_value"], s["k_unit"]
        _recompute_k(cfg)
    else:
        cfg["cor"] = {"q4": s["q4"], "q20": s["q20"], "unit": s["range_unit"]}
    cfg["flow_method"] = s["acq"]


@app.get("/api/standards")
def standards_list():
    return jsonify(standards=std_list(request.args.get("q", "")), selected_id=load_cfg().get("standard_id"))


@app.post("/api/standards")
@guarded
def standards_create():
    d = request.get_json(silent=True) or {}
    try:
        v = std_validate(d, load_cfg())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    now = int(time.time() * 1000)
    cols = [c for c in STD_COLS if c not in ("id",)]
    vals = [v.get(c) for c in cols[:-2]] + [now, now]
    try:
        with lock:
            cur = db.execute(f"INSERT INTO standards({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
            db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error=f"Já existe um padrão com a TAG {v['tag']}."), 409
    log.info("padrão cadastrado: %s (%s)", v["tag"], v["acq"])
    return jsonify(std_get(cur.lastrowid)), 201


@app.route("/api/standards/<int:sid>", methods=["PUT", "DELETE"])
@guarded
def standards_update(sid):
    cur = std_get(sid)
    if not cur:
        return jsonify(error="Padrão não encontrado."), 404
    cfg = load_cfg()
    if request.method == "DELETE":
        if trials.has_running() and cfg.get("standard_id") == sid:
            return jsonify(error="Este padrão está em uso num ensaio em andamento."), 409
        with lock:
            db.execute("DELETE FROM standards WHERE id=?", (sid,))
            db.commit()
        if cfg.get("standard_id") == sid:   # a seleção some; os parâmetros copiados continuam válidos até outro padrão ser escolhido
            cfg = copy.deepcopy(cfg)
            cfg["standard_id"] = None
            save_cfg(cfg)
            sio.emit("config", public_cfg(cfg))
        log.info("padrão excluído: %s (os ensaios já realizados mantêm a cópia dos parâmetros)", cur["tag"])
        return jsonify(ok=True)
    d = request.get_json(silent=True) or {}
    try:
        v = std_validate(d, cfg)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    v["updated_ts"] = int(time.time() * 1000)
    cols = [c for c in STD_COLS if c not in ("id", "created_ts")]
    try:
        with lock:
            db.execute(f"UPDATE standards SET {','.join(c + '=?' for c in cols)} WHERE id=?", [v.get(c) for c in cols] + [sid])
            db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error=f"Já existe um padrão com a TAG {v['tag']}."), 409
    s = std_get(sid)
    if cfg.get("standard_id") == sid and not trials.has_running():   # padrão em uso ao vivo: a leitura ao vivo acompanha; ensaios feitos não mudam
        cfg = copy.deepcopy(cfg)
        std_apply(cfg, s)
        if cfg["flow_method"] != FLOW["requested"] and method_refusal(cfg["flow_method"]):
            cfg["flow_method"] = FLOW["requested"]
        save_cfg(cfg)
        if cfg["flow_method"] != FLOW["requested"]:
            set_requested(cfg["flow_method"])
        sio.emit("config", public_cfg(cfg))
    log.info("padrão editado: %s", s["tag"])
    return jsonify(s)


@app.post("/api/standards/<int:sid>/select")
@guarded
def standards_select(sid):
    """Seleciona o padrão: copia K/unidade ou faixa 4–20 mA para a configuração e pede o método correspondente.
    O método só aparece como ATIVO quando o datalogger confirma; se o programa carregado não tem o canal, a seleção
    vale (parâmetros carregados) e a resposta traz `method_error`."""
    s = std_get(sid)
    if not s:
        return jsonify(error="Padrão não encontrado."), 404
    if trials.has_running():
        return jsonify(error="Há um ensaio em andamento: troque o padrão depois que ele terminar."), 409
    cfg = copy.deepcopy(load_cfg())
    std_apply(cfg, s)
    err = method_refusal(s["acq"]) if s["acq"] != FLOW["requested"] else None
    if err:
        cfg["flow_method"] = FLOW["requested"]
    save_cfg(cfg)
    if cfg["flow_method"] != FLOW["requested"]:
        set_requested(cfg["flow_method"])
    pc = public_cfg(cfg)
    sio.emit("config", pc)
    log.info("padrão selecionado: %s (%s)%s", s["tag"], s["acq"], f"; método não solicitado: {err[1]}" if err else "")
    return jsonify(config=pc, flow=flow_status(), method_error=err[1] if err else None)


# ---------- medidor de vazão: método de aquisição ----------
flow_lock = threading.Lock()


def flow_status():
    """Estado do medidor para a interface: método escolhido × confirmado por dado do datalogger, canais que o programa
    fornece e bloqueio durante ensaio. Os parâmetros vêm do config.json (fonte única)."""
    cfg = load_cfg()
    k = cfg["flow_k_pulses_per_l"]
    return {"integrated": dl.has_flow, "has": list(dl.flow_has), "requested": FLOW["requested"], "active": FLOW["active"],
            "confirmed": FLOW["active"] == FLOW["requested"], "changed_at": FLOW["changed_at"], "confirmed_at": FLOW["confirmed_at"],
            "locked": trials.has_running(),
            "params": {"k_pulses_per_l": k, "k_unit": cfg["flow_k_unit"], "k_value": calc.k_from_pulses_per_l(k, cfg["flow_k_unit"]),
                       "resolution_lmin_1s": calc.pulse_resolution_l_min(k, 1.0), "ma_tol": cfg["flow_ma_tol"],
                       "q4": cfg["cor"]["q4"], "q20": cfg["cor"]["q20"], "range_unit": cfg["cor"]["unit"]}}


def method_refusal(m):
    """(status HTTP, motivo) para recusar a troca do método, ou None se a troca é segura."""
    if m not in FLOW_METHODS:
        return 400, "Método inválido: use 'analog' (4–20 mA) ou 'pulse' (pulsos)."
    if not dl.has_flow:
        return 409, "O perfil do datalogger em uso não tem o medidor de vazão."
    if trials.has_running():
        return 409, "Há um ensaio em andamento: o método do medidor só pode mudar depois que ele terminar."
    if not dl.flow_has:
        return 409, "Ainda não houve leitura do datalogger para confirmar quais canais o programa fornece. Aguarde a comunicação."
    if m not in dl.flow_has:
        return 409, ("O programa carregado no datalogger não fornece o canal de pulsos (P2). Carregue "
                     "crbasic/Pluviometria_v4_vazao_pulsos.CR1X para usar este método." if m == "pulse"
                     else "O programa carregado no datalogger não fornece o canal 4–20 mA.")
    return None


def set_requested(m):
    """Novo método gravado: deixa de ser 'ativo' até que uma amostra do datalogger seja calculada com ele."""
    with flow_lock:
        old = FLOW["requested"]
        FLOW.update(requested=m, active=None, changed_at=int(time.time() * 1000), confirmed_at=None, no_pulse_streak=0)
    log.info("medidor de vazão: método alterado de %s para %s; aguardando confirmação por dado do datalogger",
             METHOD_LABEL.get(old, old), METHOD_LABEL[m])
    sio.emit("flow", flow_status())


@app.get("/api/flow")
def flow_get():
    return jsonify(flow_status())


@app.post("/api/flow/method")
@guarded
def flow_method_set():
    m = (request.get_json(silent=True) or {}).get("method")
    if m == FLOW["requested"] and m in FLOW_METHODS:
        return jsonify(flow_status())   # já é o método escolhido: nada a mudar
    err = method_refusal(m)
    if err:
        return jsonify(error=err[1], flow=flow_status()), err[0]
    cfg = copy.deepcopy(load_cfg())
    cfg["flow_method"] = m
    save_cfg(cfg)
    set_requested(m)
    sio.emit("config", public_cfg(cfg))
    return jsonify(flow_status())


@app.post("/api/reset-count")
@guarded
def reset_count():
    w("INSERT OR REPLACE INTO meta VALUES('count_since',?)", (str(int(time.time() * 1000)),))
    return jsonify(ok=True)


def single_instance():
    """Trava de instância única por pasta de dados. No Windows o servidor web abre a porta com SO_REUSEADDR, e uma segunda
    cópia sobe na MESMA porta sem erro: as duas consultavam o datalogger e gravavam o mesmo banco e o mesmo cursor
    (visto em 27/10/2026). A trava é liberada pelo sistema quando o processo termina, mesmo se ele cair."""
    f = open(os.path.join(DATA, "logs", "servidor.lock"), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Outra cópia do servidor já está rodando com esta pasta de dados (%s). Esta cópia vai encerrar; "
                  "use a que já está aberta (http://127.0.0.1:%s) ou pare-a com parar.bat.", DATA, os.environ.get("PORT", 5000))
        sys.exit(3)
    return f


if __name__ == "__main__":
    _instance_lock = single_instance()
    host = os.environ.get("HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not DASHBOARD_TOKEN:
        log.warning("Servidor exposto em %s SEM DASHBOARD_TOKEN: qualquer máquina da rede pode alterar configurações e iniciar ensaios.", host)
    log.info("iniciando: datalogger=%s (%s) perfil=%s (%s) protocolo=%s (%s) credenciais=%s método do medidor=%s proteção de escrita=%s",
             "configurado" if _comm.get("address") else "NÃO configurado", _origin.get("address"), _comm.get("profile"), _origin.get("profile"),
             _comm.get("protocol"), _origin.get("protocol"), CRED_SOURCE, METHOD_LABEL[FLOW["requested"]],
             "ligada" if DASHBOARD_TOKEN else "desligada")
    sio.start_background_task(acquire)
    sio.run(app, host=host, port=int(os.environ.get("PORT", 5000)), allow_unsafe_werkzeug=True)
