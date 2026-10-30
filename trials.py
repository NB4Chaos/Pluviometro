"""Ensaios de calibração: aquisição controlada com início, duração e fim definidos.

Princípios
  * A janela do ensaio é [início, fim) no horário do DATALOGGER (o mesmo carimbo das amostras), nunca no do PC.
  * O resultado nasce de um SNAPSHOT: ao terminar, as amostras e as basculadas da janela são COPIADAS para tabelas do
    ensaio e o resultado é calculado só com elas. Depois disso o banco recusa qualquer alteração (gatilhos abaixo):
    nem a janela de 15 min que continua avançando, nem novas basculadas, nem mudança de configuração o alteram.
  * O MÉTODO do medidor (analógico | pulsos), o fator K, a faixa 4–20 mA, a tolerância e a duração ficam congelados no
    início: trocar a configuração depois não altera o ensaio.
  * Pulsos: N = Contador_final − Contador_inicial (Flow_PulsosTot) quando o contador não reiniciou — robusto a registros
    perdidos; senão N = Σ contagens por registro. A contagem bruta é sempre preservada; K só entra depois.
  * Tempo: duração configurada em ms; resolução EFETIVA = intervalo do Scan do datalogger (1000 ms no programa atual);
    tempo efetivo medido pelos carimbos dos registros. Os três são informados separadamente, sem arredondar antes.
  * Estados: running | completed | incomplete (chegou ao fim, mas com lacunas/leituras inválidas) | interrupted
    (parado antes do fim previsto: usuário ou falta de dados).
  * Um ensaio de cada vez (índice único no banco): impossível iniciar dois.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime

import calc

log = logging.getLogger("ensaios")

MAX_DURATION_MS = 6 * 3600 * 1000
GRACE_S = 120          # espera (relógio do PC) depois do fim previsto antes de dar o ensaio por interrompido
VALID_FRAC = 0.95      # fração mínima de leituras válidas do sinal exigido para o ensaio ser "concluído"
MIN_PULSES_WARN = 200  # abaixo disso a quantização (±1 pulso) pesa: aviso, não erro
KINDS = {"flow": "Medidor de Vazão", "pluv": "Pluviômetro (gravimétrico)"}
SCOLS_LIST = ["ts", "mass_g", "temp_c", "mass_status", "temp_status", "cor_ma", "cor_status", "flow_mode", "flow_pulses", "flow_hz",
              "flow_pulses_total", "pulse_status"]
SCOLS = ",".join(SCOLS_LIST)
I = {c: i for i, c in enumerate(SCOLS_LIST)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL, duration_cfg_s REAL NOT NULL, started_wall INTEGER NOT NULL, finished_wall INTEGER,
  reason TEXT, cfg TEXT NOT NULL, result TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_trial_running ON trials(state) WHERE state='running';
CREATE TABLE IF NOT EXISTS trial_samples(trial_id TEXT NOT NULL, ts INTEGER NOT NULL, mass_g REAL, temp_c REAL, mass_status TEXT,
  temp_status TEXT, cor_ma REAL, cor_status TEXT, flow_mode TEXT, flow_pulses REAL, flow_hz REAL);
CREATE INDEX IF NOT EXISTS ix_trial_samples ON trial_samples(trial_id, ts);
CREATE TABLE IF NOT EXISTS trial_tips(trial_id TEXT NOT NULL, ts INTEGER NOT NULL, src TEXT);
CREATE INDEX IF NOT EXISTS ix_trial_tips ON trial_tips(trial_id, ts);
CREATE TRIGGER IF NOT EXISTS trials_imutavel_upd BEFORE UPDATE ON trials WHEN OLD.state <> 'running'
  BEGIN SELECT RAISE(ABORT, 'ensaio encerrado e imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trials_imutavel_del BEFORE DELETE ON trials
  BEGIN SELECT RAISE(ABORT, 'ensaios nao podem ser apagados'); END;
CREATE TRIGGER IF NOT EXISTS trial_samples_ins BEFORE INSERT ON trial_samples
  WHEN COALESCE((SELECT state FROM trials WHERE id = NEW.trial_id), '') <> 'running'
  BEGIN SELECT RAISE(ABORT, 'ensaio encerrado e imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trial_samples_upd BEFORE UPDATE ON trial_samples BEGIN SELECT RAISE(ABORT, 'imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trial_samples_del BEFORE DELETE ON trial_samples BEGIN SELECT RAISE(ABORT, 'imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trial_tips_ins BEFORE INSERT ON trial_tips
  WHEN COALESCE((SELECT state FROM trials WHERE id = NEW.trial_id), '') <> 'running'
  BEGIN SELECT RAISE(ABORT, 'ensaio encerrado e imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trial_tips_upd BEFORE UPDATE ON trial_tips BEGIN SELECT RAISE(ABORT, 'imutavel'); END;
CREATE TRIGGER IF NOT EXISTS trial_tips_del BEFORE DELETE ON trial_tips BEGIN SELECT RAISE(ABORT, 'imutavel'); END;
"""
TCOLS = "id,kind,state,start_ts,end_ts,duration_cfg_s,duration_cfg_ms,started_wall,finished_wall,reason,cfg,result"


class TrialError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _method(cfg, rows):
    """Método congelado no ensaio; ensaios antigos (sem `method`) inferem pelo modo que o datalogger informava."""
    m = cfg.get("method")
    if m in ("analog", "pulse"):
        return m
    return "pulse" if any(r[I["flow_mode"]] == "pulse" for r in rows) else "analog"


def _pulse_row(r):
    """(contagem, válida?, acumulado) de uma linha. Linhas antigas (sem pulse_status) valem pelo modo 'pulse' + status ok."""
    n, ps, tot = r[I["flow_pulses"]], r[I["pulse_status"]], r[I["flow_pulses_total"]]
    if ps is None and r[I["flow_mode"]] == "pulse" and n is not None and r[I["cor_status"]] in (None, "ok"):
        ps = "ok"
    return n, (ps == "ok" and n is not None), tot


def _analog_lm(r, cfg):
    """Vazão (L/min) do canal analógico de uma linha, pela faixa e tolerância congeladas; None se inválida/fora da faixa."""
    ma, cs = r[I["cor_ma"]], r[I["cor_status"]]
    if ma is None or cs in (None, "no_comm", "invalid"):
        return None
    return calc.flow_from_sample("analog", "ok", None, ma, None, cfg.get("q4"), cfg.get("q20"), cfg.get("range_unit"), cfg.get("density"),
                                 cfg.get("ma_tol", calc.MA_TOL))


def flow_of_row(d, cfg):
    """Vazão (L/min) de UMA amostra do ensaio (dict com SCOLS_LIST) pelo método congelado; para o CSV bruto."""
    r = tuple(d.get(c) for c in SCOLS_LIST)
    if _method(cfg, [r]) == "pulse":
        n, ok, _ = _pulse_row(r)
        return calc.pulse_flow_l_min(n, cfg.get("scan_ms", 1000) / 1000.0, cfg.get("k_pulses_per_l")) if ok else None
    return _analog_lm(r, cfg)


def timing(ts, cfg, start, end, scan_ms):
    """Temporização do ensaio, só com carimbos do DATALOGGER (ms, resolução = Scan). Três tempos, sem misturar:
      cfg_ms    = duração configurada pelo operador (preservada como digitada, em ms)
      window_ms = janela [start, end) usada no cálculo (= cfg_ms quando o ensaio chega ao fim previsto)
      eff_ms    = tempo efetivamente coberto pelos registros: do 1º ao último carimbo, mais um Scan (o registro em t cobre (t−Scan, t])
    diff_ms = eff − cfg. Sem registros: eff/diff = None (nunca zero). `wall_ms` (relógio do PC) entra em _finish, só como informação.
    Isto NÃO calibra o temporizador: é o registro necessário para comparar com uma referência externa de tempo."""
    cfg_ms = cfg.get("duration_ms")
    if cfg_ms is None and cfg.get("duration_s") is not None:
        cfg_ms = int(round(float(cfg["duration_s"]) * 1000))
    eff = (ts[-1] - ts[0] + scan_ms) if ts else None
    return {"start_ts": start, "end_ts": end, "cfg_ms": cfg_ms, "window_ms": end - start, "resolution_ms": scan_ms,
            "first_sample_ts": ts[0] if ts else None, "last_sample_ts": ts[-1] if ts else None, "samples": len(ts),
            "eff_ms": eff, "diff_ms": (eff - cfg_ms) if eff is not None and cfg_ms is not None else None, "wall_ms": None}


def compute(rows, tips, cfg, start, end, kind, scan_ms=None):
    """Resultado de uma janela [start, end) a partir SÓ das linhas e basculadas fornecidas.

    rows: tuplas na ordem de SCOLS; tips: [(ts, src)] ordenadas. Não toca no banco nem no relógio: é a função testada.
    """
    scan_ms = int(scan_ms or cfg.get("scan_ms") or 1000)
    ts = [r[0] for r in rows]
    cov, gaps, complete = calc.window_coverage(ts, start, end)
    q = {"window_s": (end - start) / 1000, "covered_s": cov / 1000, "gaps": gaps, "rows": len(rows),
         "coverage_complete": complete, "reasons": []}
    res = cfg.get("res_mm")
    out = {"quality": q, "flow": None, "gravimetric": None, "pluviometer": None, "temperature": None, "timing": timing(ts, cfg, start, end, scan_ms)}

    # ---- temperatura (informativa: densidade e área NÃO são deduzidas dela)
    tv = [r[2] for r in rows if r[2] is not None]
    if tv:
        out["temperature"] = {"mean_c": sum(tv) / len(tv), "min_c": min(tv), "max_c": max(tv), "n": len(tv)}

    # ---- medidor de vazão: pelo método CONGELADO; o outro canal fica como informação
    w = calc.sample_weights_ms(ts)
    method = _method(cfg, rows)
    prow = [_pulse_row(r) for r in rows]
    has_pulse = any(r[I["pulse_status"]] is not None for r in rows) or any(ok for _, ok, _ in prow)
    has_analog = any(r[I["cor_status"]] is not None for r in rows)
    lm = [None] * len(rows)   # vazão instantânea (L/min) por linha, pelo método
    f = None
    k = cfg.get("k_pulses_per_l")
    if has_pulse or has_analog:
        f = {"mode": method, "n_rows": len(rows), "n_valid": 0, "valid_fraction": None, "flow_l_min": None, "volume_l": None,
             "pulses_total": None, "pulses_sum": None, "pulses_delta_total": None, "count_method": None, "counter_reset": False, "raw_counts": 0,
             "freq_mean_hz": None, "ma": None, "valid_s": None, "elapsed_s": None, "time_cfg_ms": cfg.get("duration_ms"), "time_eff_ms": None,
             "time_resolution_ms": scan_ms, "vs_reference": None, "other_channel": None, "k_pulses_per_l": k, "k_value": cfg.get("k_value"),
             "k_unit": cfg.get("k_unit"), "ma_tol": cfg.get("ma_tol"), "issues": [], "warnings": []}
        mav = [r[I["cor_ma"]] for r in rows if r[I["cor_ma"]] is not None and r[I["cor_status"]] == "ok"]
        if mav:
            f["ma"] = {"mean": sum(mav) / len(mav), "min": min(mav), "max": max(mav), "n": len(mav)}
        if method == "pulse":
            valid = [i for i, (_, ok, _) in enumerate(prow) if ok]
            f["n_valid"] = f["raw_counts"] = len(valid)
            f["valid_fraction"] = len(valid) / len(rows) if rows else None
            if not has_pulse:
                f["issues"].append("o programa do datalogger não fornece o canal de pulsos (P2) do medidor de vazão")
            elif valid:
                cw = calc.pulse_count_window([prow[i][0] for i in valid], [prow[i][2] for i in valid])
                f.update(pulses_sum=cw["n_sum"], pulses_delta_total=cw["n_delta"], pulses_total=cw["n"], count_method=cw["method"], counter_reset=cw["reset"])
                vs = sum(w[i] for i in valid)
                # acumulado: o contador cobre também os registros que faltaram -> tempo do 1º ao último registro válido (inclusive o Scan dele)
                t_eff = (rows[valid[-1]][0] - rows[valid[0]][0] + scan_ms) if cw["method"] == "acumulado" else vs
                f["time_eff_ms"], f["elapsed_s"], f["valid_s"] = int(t_eff), t_eff / 1000.0, vs / 1000.0
                n = cw["n"]
                f["freq_mean_hz"] = n / f["elapsed_s"] if f["elapsed_s"] > 0 else None
                if cw["reset"]:
                    if gaps:
                        f["issues"].append("contador do datalogger reiniciado E lacunas de registros no mesmo ensaio: a contagem de pulsos é incerta")
                    else:
                        f["warnings"].append("contador do datalogger reiniciado durante o ensaio: N pela soma dos registros (sem perda: não houve lacuna)")
                elif gaps and cw["method"] == "acumulado":
                    f["warnings"].append("lacunas de registros: N obtido pela diferença do contador acumulado (os pulsos das lacunas estão incluídos)")
                if n < MIN_PULSES_WARN:
                    f["warnings"].append(f"ensaio com menos de {MIN_PULSES_WARN} pulsos (N = {n}): ±1 pulso = "
                                         + (f"±{100.0 / n:.2f} %" if n else "resolução indefinida") + " do volume; prolongue o ensaio para reduzir a quantização")
                if k:
                    f["volume_l"] = calc.pulse_volume_l(n, k)
                    for i in valid:
                        lm[i] = calc.pulse_flow_l_min(prow[i][0], w[i] / 1000.0, k)
                    inst = [lm[i] for i in valid]
                    f["flow_l_min"] = {"mean": calc.pulse_flow_l_min(n, f["elapsed_s"], k), "min": min(inst), "max": max(inst)}
                else:
                    f["issues"].append("fator K (pulsos por volume) não configurado: vazão e volume indisponíveis; a contagem bruta de pulsos está preservada")
            else:
                f["issues"].append("nenhuma leitura válida do canal de pulsos no ensaio")
            if has_analog:   # outro canal, só informação
                la = [_analog_lm(r, cfg) for r in rows]
                ia = [i for i, v in enumerate(la) if v is not None]
                if ia:
                    f["other_channel"] = {"channel": "analog", "n_valid": len(ia), "ma_mean": sum(rows[i][I["cor_ma"]] for i in ia) / len(ia),
                                          "flow_l_min_mean": sum(la[i] for i in ia) / len(ia), "volume_l": sum(la[i] * w[i] / 60000.0 for i in ia)}
                elif mav:
                    f["other_channel"] = {"channel": "analog", "n_valid": 0, "ma_mean": f["ma"]["mean"], "flow_l_min_mean": None, "volume_l": None}
        else:
            lm = [_analog_lm(r, cfg) for r in rows]
            valid = [i for i, v in enumerate(lm) if v is not None]
            f["n_valid"], f["valid_fraction"] = len(valid), (len(valid) / len(rows) if rows else None)
            if not has_analog:
                f["issues"].append("o programa do datalogger não fornece o canal analógico (RG1) do medidor de vazão")
            elif valid:
                vs = sum(w[i] for i in valid) / 1000.0
                vol = sum(lm[i] * w[i] / 60000.0 for i in valid)          # ∫ Q dt (L)
                vals = [lm[i] for i in valid]
                f.update(valid_s=vs, elapsed_s=vs, time_eff_ms=int(vs * 1000), volume_l=vol,
                         flow_l_min={"mean": vol / (vs / 60.0) if vs else None, "min": min(vals), "max": max(vals)})
            elif cfg.get("q4") is None or cfg.get("q20") is None:
                f["issues"].append("faixa 4–20 mA não configurada: vazão indisponível (o sinal em mA é preservado)")
            else:
                f["issues"].append("nenhuma leitura válida do sinal 4–20 mA no ensaio")
            if has_pulse:   # outro canal, só informação
                pv = [i for i, (_, ok, _) in enumerate(prow) if ok]
                if pv:
                    cw = calc.pulse_count_window([prow[i][0] for i in pv], [prow[i][2] for i in pv])
                    f["other_channel"] = {"channel": "pulse", "n_valid": len(pv), "pulses_total": cw["n"], "count_method": cw["method"],
                                          "volume_l": calc.pulse_volume_l(cw["n"], k) if k else None}
        out["flow"] = f

    # ---- gravimetria (variação de massa na balança) e pluviômetro
    mrows = [(r[0], r[1]) for r in rows if r[1] is not None]
    g = None
    if len(mrows) >= 2:
        (t0, m0), (t1, m1) = mrows[0], mrows[-1]
        # Pulsos: o registro em t traz as basculadas de (t-Δ, t]; a massa é instantânea. Logo (t0, t1].
        n = sum(1 for t, _ in tips if t0 < t <= t1)
        g = calc.gravimetric(m0, m1, t0, t1, cfg.get("density"), cfg.get("area_cm2"), n if res else None, res)
        g.update({"start_ts": t0, "end_ts": t1, "pulses_window": n})
    else:
        g = calc.gravimetric(None, None, None, None, cfg.get("density"), cfg.get("area_cm2"))
    g["mass_valid_fraction"] = len(mrows) / len(rows) if rows else None
    g["density_g_cm3"], g["area_cm2"], g["resolution_mm"] = cfg.get("density"), cfg.get("area_cm2"), res
    out["gravimetric"] = g

    pp = calc.precip_period([t for t, _ in tips], ts, start, end, res)
    pp.update({"raw_pulses": len(tips), "resolution_mm": res})
    out["pluviometer"] = pp

    # ---- comparação do medidor com a referência, NO MESMO intervalo da referência
    if f and g.get("volume_l") is not None and f.get("valid_s"):
        a, b = g["start_ts"], g["end_ts"]
        idx = [i for i, r in enumerate(rows) if a < r[0] <= b and lm[i] is not None]   # (t0, t1]: a amostra em t traz o segundo que termina em t
        if idx:
            if method == "pulse" and k:
                cw = calc.pulse_count_window([prow[i][0] for i in idx], [prow[i][2] for i in idx])
                vm = calc.pulse_volume_l(cw["n"], k)
            else:
                vm = sum(lm[i] * w[i] / 60000.0 for i in idx)
            vr = g["volume_l"]
            f["vs_reference"] = {"window_s": (b - a) / 1000, "volume_meter_l": vm, "volume_ref_l": vr, "diff_l": vm - vr,
                                 "error_pct": 100.0 * (vm - vr) / vr if vr > 0 else None}

    # ---- qualidade: o que o tipo de ensaio exige
    if not rows:
        q["reasons"].append("nenhuma amostra na janela")
    if not complete and rows:
        q["reasons"].append(f"lacunas: {q['covered_s']:.0f} s cobertos de {q['window_s']:.0f} s")
    if kind == "flow":
        if not f:
            q["reasons"].append("o programa do datalogger não fornece o medidor de vazão")
        else:
            q["reasons"] += f["issues"]
            if (f["valid_fraction"] or 0) < VALID_FRAC and not any("não fornece" in i for i in f["issues"]):
                q["reasons"].append(f"leituras válidas do medidor: {100 * (f['valid_fraction'] or 0):.0f} % (mínimo {100 * VALID_FRAC:.0f} %)")
    if kind == "pluv":
        if (g["mass_valid_fraction"] or 0) < VALID_FRAC:
            q["reasons"].append(f"leituras válidas da balança: {100 * (g['mass_valid_fraction'] or 0):.0f} % (mínimo {100 * VALID_FRAC:.0f} %)")
        if rows and g["volume_ml"] is None:   # sem referência gravimétrica o ensaio não serve para comparação
            q["reasons"].append("referência gravimétrica indisponível: " + "; ".join(g["issues"]))
    q["ok"] = not q["reasons"]
    return out


class Trials:
    def __init__(self, db, lock, get_cfg, latest_ts, scan_ms=1000):
        self.db, self.lock, self.get_cfg, self.latest_ts, self.scan_ms = db, lock, get_cfg, latest_ts, int(scan_ms or 1000)
        with lock:
            db.executescript(SCHEMA)
            have = {r[1] for r in db.execute("PRAGMA table_info(trial_samples)")}
            for col, typ in (("flow_pulses_total", "INTEGER"), ("pulse_status", "TEXT")):
                if col not in have:   # bancos antigos ganham as colunas dos pulsos brutos (ALTER TABLE não dispara os gatilhos)
                    db.execute(f"ALTER TABLE trial_samples ADD COLUMN {col} {typ}")
            if "duration_cfg_ms" not in {r[1] for r in db.execute("PRAGMA table_info(trials)")}:
                db.execute("ALTER TABLE trials ADD COLUMN duration_cfg_ms INTEGER")
            db.commit()
        self._live = (0.0, None, None, 0)

    # ---------------- leitura
    def _all(self, sql, a=()):
        with self.lock:
            return self.db.execute(sql, a).fetchall()

    def _row(self, r):
        d = dict(zip(TCOLS.split(","), r))
        d["cfg"] = json.loads(d["cfg"])
        d["result"] = json.loads(d["result"]) if d["result"] else None
        d["kind_label"] = KINDS.get(d["kind"], d["kind"])
        if d["duration_cfg_ms"] is None:
            d["duration_cfg_ms"] = int(round(d["duration_cfg_s"] * 1000))
        s = d["duration_cfg_s"]
        d["duration_cfg_s"] = int(s) if s is not None and float(s).is_integer() else s
        return d

    def get(self, tid):
        r = self._all(f"SELECT {TCOLS} FROM trials WHERE id=?", (tid,))
        return self._row(r[0]) if r else None

    def list(self, limit=50):
        rows = self._all(f"SELECT {TCOLS} FROM trials ORDER BY started_wall DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = self._row(r)
            d.pop("result"), d.pop("cfg")
            out.append(d)
        return out

    def raw(self, tid):
        s = self._all(f"SELECT {SCOLS} FROM trial_samples WHERE trial_id=? ORDER BY ts", (tid,))
        t = self._all("SELECT ts,src FROM trial_tips WHERE trial_id=? ORDER BY ts", (tid,))
        return s, t

    def has_running(self):
        return bool(self._all("SELECT 1 FROM trials WHERE state='running' LIMIT 1"))

    def _running(self):
        r = self._all(f"SELECT {TCOLS} FROM trials WHERE state='running'")
        return self._row(r[0]) if r else None

    def _window(self, start, end):
        s = self._all(f"SELECT {SCOLS} FROM samples WHERE ts>=? AND ts<? ORDER BY ts", (start, end))
        t = self._all("SELECT ts,src FROM tips WHERE ts>=? AND ts<? ORDER BY ts", (start, end))
        return s, t

    def status(self):
        """{running: andamento (com resultado PARCIAL, marcado como tal) ou None, last: último ensaio encerrado, congelado}."""
        run, out = self._running(), {"running": None, "last": None}
        if run:
            lt = self.latest_ts()
            dur_ms = run["duration_cfg_ms"]
            done = max(0, min(run["end_ts"], (lt + 1) if lt is not None else run["start_ts"]) - run["start_ts"])
            live = self._live   # snapshot: outra thread pode trocar self._live no meio
            step = 0 if dur_ms <= 900_000 else 5000   # parcial a cada amostra em ensaios curtos; a cada 5 s nos longos (janela grande)
            if live[1] != run["id"] or (lt or 0) - (live[0] or 0) > step:
                s, t = self._window(run["start_ts"], run["end_ts"])
                live = self._live = (lt, run["id"], compute(s, t, run["cfg"], run["start_ts"], max(run["start_ts"] + 1, min(run["end_ts"], (lt or run["start_ts"]) + 1)),
                                                           run["kind"], self.scan_ms), len(s))
            out["running"] = {k: run[k] for k in ("id", "kind", "kind_label", "start_ts", "end_ts", "duration_cfg_s", "duration_cfg_ms", "cfg")} | {
                "state": "running", "elapsed_s": done / 1000, "remaining_s": max(0.0, (dur_ms - done) / 1000),
                "n_samples": live[3], "partial": live[2], "scan_ms": self.scan_ms}
        r = self._all(f"SELECT {TCOLS} FROM trials WHERE state<>'running' ORDER BY finished_wall DESC LIMIT 1")
        out["last"] = self._row(r[0]) if r else None
        return out

    # ---------------- escrita
    def start(self, kind, connected):
        if kind not in KINDS:
            raise TrialError(400, "Tipo de ensaio inválido.")
        cfg = self.get_cfg()
        dur_ms = cfg.get("trial_duration_ms") or int(round(float(cfg.get("trial_duration_s") or 0) * 1000))
        if dur_ms < self.scan_ms:
            raise TrialError(400, f"Duração do ensaio: mínimo {self.scan_ms} ms, que é a resolução efetiva do datalogger (Scan de {self.scan_ms} ms). "
                                  "Durações menores não podem ser medidas com o programa atual do CR1000Xe.")
        if dur_ms > MAX_DURATION_MS:
            raise TrialError(400, f"Duração do ensaio: máximo {MAX_DURATION_MS // 1000} s.")
        lt = self.latest_ts()
        if lt is None or not connected:
            raise TrialError(409, "Sem dados atuais do datalogger: o ensaio só inicia com a aquisição ativa.")
        snap = {"res_mm": cfg.get("tip_resolution_mm"), "area_cm2": cfg.get("catch_area_cm2"), "density": cfg.get("density_g_cm3"),
                "method": cfg.get("flow_method") if cfg.get("flow_method") in ("analog", "pulse") else None,   # None: inferir pelas linhas (configuração antiga)
                "k_pulses_per_l": cfg.get("flow_k_pulses_per_l"), "k_value": cfg.get("flow_k_value"), "k_unit": cfg.get("flow_k_unit"),
                "ma_tol": cfg.get("flow_ma_tol", calc.MA_TOL),
                "q4": cfg["cor"]["q4"], "q20": cfg["cor"]["q20"], "range_unit": cfg["cor"]["unit"],
                "duration_ms": dur_ms, "duration_s": dur_ms / 1000, "scan_ms": self.scan_ms}
        tid = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        start = lt + 1     # primeira amostra do ensaio = a PRÓXIMA; a leitura que já estava na tela não entra
        try:
            with self.lock:
                self.db.execute("INSERT INTO trials(id,kind,state,start_ts,end_ts,duration_cfg_s,duration_cfg_ms,started_wall,cfg) VALUES(?,?,?,?,?,?,?,?,?)",
                                (tid, kind, "running", start, start + dur_ms, dur_ms / 1000, dur_ms, int(time.time() * 1000), json.dumps(snap)))
                self.db.commit()
        except Exception as e:   # índice único: já existe um 'running'
            if "UNIQUE" in str(e).upper():
                raise TrialError(409, "Já existe um ensaio em andamento. Encerre-o antes de iniciar outro.")
            raise
        log.info("ensaio %s (%s) iniciado: início=%d (horário do datalogger) duração=%d ms método=%s cfg=%s", tid, kind, start, dur_ms, snap["method"], snap)
        self._live = (0.0, None, None, 0)
        return self.get(tid)

    def tick(self, now_wall):
        """Chamado depois de cada lote gravado: encerra o ensaio quando o relógio do DATALOGGER passa do fim previsto."""
        run = self._running()
        if not run:
            return None
        lt = self.latest_ts()
        if lt is not None and lt >= run["end_ts"]:
            return self._finish(run, run["end_ts"], None, None)
        if now_wall > run["started_wall"] + run["duration_cfg_ms"] + GRACE_S * 1000:
            return self._finish(run, max(run["start_ts"] + 1, min(run["end_ts"], (lt or run["start_ts"]) + 1)), "interrupted",
                                "sem dados do datalogger após o fim previsto (tempo de espera esgotado)")
        return None

    def stop(self, reason="parado pelo usuário"):
        run = self._running()
        if not run:
            raise TrialError(409, "Nenhum ensaio em andamento.")
        lt = self.latest_ts()
        end = max(run["start_ts"] + 1, min(run["end_ts"], (lt or run["start_ts"]) + 1))
        return self._finish(run, end, "interrupted", reason)

    def _finish(self, run, end, forced, reason):
        start = run["start_ts"]
        s, t = self._window(start, end)
        res = compute(s, t, run["cfg"], start, end, run["kind"], self.scan_ms)
        state = forced or ("completed" if res["quality"]["ok"] else "incomplete")
        if state == "incomplete" and not reason:
            reason = "; ".join(res["quality"]["reasons"])
        res["quality"]["effective_window_s"] = (end - start) / 1000
        fin_wall = int(time.time() * 1000)
        res["timing"]["wall_ms"] = fin_wall - run["started_wall"]   # relógio do PC (início do pedido → encerramento): só informativo
        with self.lock:
            if not self.db.execute("SELECT 1 FROM trials WHERE id=? AND state='running'", (run["id"],)).fetchone():
                return self.get(run["id"])   # outra thread (tick × stop) já encerrou este ensaio
            try:
                self.db.executemany("INSERT INTO trial_samples(trial_id," + SCOLS + ") VALUES(?" + ",?" * len(SCOLS_LIST) + ")", [(run["id"],) + tuple(r) for r in s])
                self.db.executemany("INSERT INTO trial_tips(trial_id,ts,src) VALUES(?,?,?)", [(run["id"], a, b) for a, b in t])
                self.db.execute("UPDATE trials SET state=?, end_ts=?, finished_wall=?, reason=?, result=? WHERE id=? AND state='running'",
                                (state, end, fin_wall, reason, json.dumps(res), run["id"]))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        log.info("ensaio %s encerrado: estado=%s motivo=%s amostras=%d basculadas=%d cobertura=%.0f/%.0f s", run["id"], state, reason,
                 len(s), len(t), res["quality"]["covered_s"], res["quality"]["window_s"])
        self._live = (0.0, None, None, 0)
        return self.get(run["id"])
