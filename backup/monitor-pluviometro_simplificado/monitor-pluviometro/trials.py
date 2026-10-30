"""Ensaios de calibração: aquisição controlada com início, duração e fim definidos.

Princípios
  * A janela do ensaio é [início, fim) no horário do DATALOGGER (o mesmo carimbo das amostras), nunca no do PC.
  * O resultado nasce de um SNAPSHOT: ao terminar, as amostras e as basculadas da janela são COPIADAS para tabelas do
    ensaio e o resultado é calculado só com elas. Depois disso o banco recusa qualquer alteração (gatilhos abaixo):
    nem a janela de 15 min que continua avançando, nem novas basculadas, nem mudança de configuração o alteram.
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

MIN_DURATION_S, MAX_DURATION_S = 10, 6 * 3600
GRACE_S = 120          # espera (relógio do PC) depois do fim previsto antes de dar o ensaio por interrompido
VALID_FRAC = 0.95      # fração mínima de leituras válidas do sinal exigido para o ensaio ser "concluído"
KINDS = {"flow": "Medidor de Vazão", "pluv": "Pluviômetro (gravimétrico)"}
SCOLS = "ts,mass_g,temp_c,mass_status,temp_status,cor_ma,cor_status,flow_mode,flow_pulses,flow_hz"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL, duration_cfg_s INTEGER NOT NULL, started_wall INTEGER NOT NULL, finished_wall INTEGER,
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


class TrialError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _mode(row):
    """Modo do medidor numa amostra: pulse | analog | None. Perfis antigos (só mA) contam como analógico."""
    return row[7] or ("analog" if row[5] is not None else None)


def compute(rows, tips, cfg, start, end, kind):
    """Resultado de uma janela [start, end) a partir SÓ das linhas e basculadas fornecidas.

    rows: tuplas na ordem de SCOLS; tips: [(ts, src)] ordenadas. Não toca no banco nem no relógio: é a função testada.
    """
    ts = [r[0] for r in rows]
    cov, gaps, complete = calc.window_coverage(ts, start, end)
    q = {"window_s": (end - start) / 1000, "covered_s": cov / 1000, "gaps": gaps, "rows": len(rows),
         "coverage_complete": complete, "reasons": []}
    res = cfg.get("res_mm")
    out = {"quality": q, "flow": None, "gravimetric": None, "pluviometer": None, "temperature": None}

    # ---- temperatura (informativa: densidade e área NÃO são deduzidas dela)
    tv = [r[2] for r in rows if r[2] is not None]
    if tv:
        out["temperature"] = {"mean_c": sum(tv) / len(tv), "min_c": min(tv), "max_c": max(tv), "n": len(tv)}

    # ---- medidor de vazão
    modes = {_mode(r) for r in rows} - {None}
    w = calc.sample_weights_ms(ts)
    if modes:
        mode = "pulse" if modes == {"pulse"} else "analog" if modes == {"analog"} else "misto"
        lm = [calc.flow_from_sample(_mode(r), r[6] if r[6] is not None else "ok", r[9], r[5], cfg.get("k_pulses_per_l"),
                                    cfg.get("q4"), cfg.get("q20"), cfg.get("range_unit"), cfg.get("density"))
              for r in rows]
        valid = [i for i, v in enumerate(lm) if v is not None]
        f = {"mode": mode, "n_rows": len(rows), "n_valid": len(valid),
             "valid_fraction": len(valid) / len(rows) if rows else None, "flow_l_min": None, "volume_l": None,
             "pulses_total": None, "freq_mean_hz": None, "ma": None, "valid_s": None, "vs_reference": None,
             "k_pulses_per_l": cfg.get("k_pulses_per_l"), "issues": []}
        if valid:
            vs = sum(w[i] for i in valid) / 1000
            f["valid_s"] = vs
            vals = [lm[i] for i in valid]
            f["flow_l_min"] = {"mean": None, "min": min(vals), "max": max(vals)}
            vol = sum(lm[i] * w[i] / 60000.0 for i in valid)          # ∫ Q dt (L)
            if mode == "pulse":
                pul = [r[8] for r in rows if r[8] is not None]
                f["pulses_total"] = sum(pul)                            # bruto, para auditoria
                f["freq_mean_hz"] = f["pulses_total"] / vs if vs else None
                if cfg.get("k_pulses_per_l"):
                    vol = f["pulses_total"] / cfg["k_pulses_per_l"]    # volume exato pelas contagens
            f["volume_l"] = vol
            f["flow_l_min"]["mean"] = vol / (vs / 60.0) if vs else None
            mav = [r[5] for r in rows if r[5] is not None and r[6] in (None, "ok")]
            if mav:
                f["ma"] = {"mean": sum(mav) / len(mav), "min": min(mav), "max": max(mav), "n": len(mav)}
        elif mode == "pulse" and not cfg.get("k_pulses_per_l"):
            f["issues"].append("fator K (pulsos por litro) não configurado: vazão e volume indisponíveis")
        elif mode in ("analog", "misto") and (cfg.get("q4") is None or cfg.get("q20") is None):
            f["issues"].append("faixa 4–20 mA não configurada: vazão indisponível (o sinal em mA é preservado)")
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
    f = out["flow"]
    if f and g.get("volume_l") is not None and f["valid_s"]:
        a, b = g["start_ts"], g["end_ts"]
        idx = [i for i, r in enumerate(rows) if a < r[0] <= b and lm[i] is not None]   # (t0, t1]: a amostra em t traz o segundo que termina em t
        if idx:
            if f["mode"] == "pulse" and cfg.get("k_pulses_per_l"):
                vm = sum(rows[i][8] for i in idx if rows[i][8] is not None) / cfg["k_pulses_per_l"]
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
        elif (f["valid_fraction"] or 0) < VALID_FRAC:
            q["reasons"].append(f"leituras válidas do medidor: {100 * (f['valid_fraction'] or 0):.0f} % (mínimo {100 * VALID_FRAC:.0f} %)")
    if kind == "pluv":
        if (g["mass_valid_fraction"] or 0) < VALID_FRAC:
            q["reasons"].append(f"leituras válidas da balança: {100 * (g['mass_valid_fraction'] or 0):.0f} % (mínimo {100 * VALID_FRAC:.0f} %)")
        if rows and g["volume_ml"] is None:   # sem referência gravimétrica o ensaio não serve para comparação
            q["reasons"].append("referência gravimétrica indisponível: " + "; ".join(g["issues"]))
    q["ok"] = not q["reasons"]
    return out


class Trials:
    def __init__(self, db, lock, get_cfg, latest_ts):
        self.db, self.lock, self.get_cfg, self.latest_ts = db, lock, get_cfg, latest_ts
        with lock:
            db.executescript(SCHEMA)
            db.commit()
        self._live = (0.0, None, None, 0)

    # ---------------- leitura
    def _all(self, sql, a=()):
        with self.lock:
            return self.db.execute(sql, a).fetchall()

    def _row(self, r):
        keys = ("id", "kind", "state", "start_ts", "end_ts", "duration_cfg_s", "started_wall", "finished_wall", "reason", "cfg", "result")
        d = dict(zip(keys, r))
        d["cfg"] = json.loads(d["cfg"])
        d["result"] = json.loads(d["result"]) if d["result"] else None
        d["kind_label"] = KINDS.get(d["kind"], d["kind"])
        return d

    def get(self, tid):
        r = self._all("SELECT id,kind,state,start_ts,end_ts,duration_cfg_s,started_wall,finished_wall,reason,cfg,result FROM trials WHERE id=?", (tid,))
        return self._row(r[0]) if r else None

    def list(self, limit=50):
        rows = self._all("SELECT id,kind,state,start_ts,end_ts,duration_cfg_s,started_wall,finished_wall,reason,cfg,result FROM trials "
                         "ORDER BY started_wall DESC LIMIT ?", (limit,))
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
        r = self._all("SELECT id,kind,state,start_ts,end_ts,duration_cfg_s,started_wall,finished_wall,reason,cfg,result FROM trials WHERE state='running'")
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
            done = max(0, min(run["end_ts"], (lt + 1) if lt is not None else run["start_ts"]) - run["start_ts"])
            live = self._live   # snapshot: outra thread pode trocar self._live no meio
            step = 0 if run["duration_cfg_s"] <= 900 else 5000   # parcial a cada amostra em ensaios curtos; a cada 5 s nos longos (janela grande)
            if live[1] != run["id"] or (lt or 0) - (live[0] or 0) > step:
                s, t = self._window(run["start_ts"], run["end_ts"])
                live = self._live = (lt, run["id"], compute(s, t, run["cfg"], run["start_ts"], max(run["start_ts"] + 1, min(run["end_ts"], (lt or run["start_ts"]) + 1)), run["kind"]), len(s))
            out["running"] = {k: run[k] for k in ("id", "kind", "kind_label", "start_ts", "end_ts", "duration_cfg_s", "cfg")} | {
                "state": "running", "elapsed_s": done / 1000, "remaining_s": max(0, run["duration_cfg_s"] - done / 1000),
                "n_samples": live[3], "partial": live[2]}
        r = self._all("SELECT id,kind,state,start_ts,end_ts,duration_cfg_s,started_wall,finished_wall,reason,cfg,result FROM trials "
                      "WHERE state<>'running' ORDER BY finished_wall DESC LIMIT 1")
        out["last"] = self._row(r[0]) if r else None
        return out

    # ---------------- escrita
    def start(self, kind, connected):
        if kind not in KINDS:
            raise TrialError(400, "Tipo de ensaio inválido.")
        cfg = self.get_cfg()
        dur = cfg["trial_duration_s"]
        if not MIN_DURATION_S <= dur <= MAX_DURATION_S:
            raise TrialError(400, f"Duração do ensaio fora de {MIN_DURATION_S} s a {MAX_DURATION_S} s.")
        lt = self.latest_ts()
        if lt is None or not connected:
            raise TrialError(409, "Sem dados atuais do datalogger: o ensaio só inicia com a aquisição ativa.")
        snap = {"res_mm": cfg["tip_resolution_mm"], "area_cm2": cfg["catch_area_cm2"], "density": cfg["density_g_cm3"],
                "k_pulses_per_l": cfg["flow_k_pulses_per_l"], "q4": cfg["cor"]["q4"], "q20": cfg["cor"]["q20"],
                "range_unit": cfg["cor"]["unit"], "duration_s": dur}
        tid = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        start = lt + 1     # primeira amostra do ensaio = a PRÓXIMA; a leitura que já estava na tela não entra
        try:
            with self.lock:
                self.db.execute("INSERT INTO trials(id,kind,state,start_ts,end_ts,duration_cfg_s,started_wall,cfg) VALUES(?,?,?,?,?,?,?,?)",
                                (tid, kind, "running", start, start + dur * 1000, dur, int(time.time() * 1000), json.dumps(snap)))
                self.db.commit()
        except Exception as e:   # índice único: já existe um 'running'
            if "UNIQUE" in str(e).upper():
                raise TrialError(409, "Já existe um ensaio em andamento. Encerre-o antes de iniciar outro.")
            raise
        log.info("ensaio %s (%s) iniciado: início=%d (horário do datalogger) duração=%ds cfg=%s", tid, kind, start, dur, snap)
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
        if now_wall > run["started_wall"] + (run["duration_cfg_s"] + GRACE_S) * 1000:
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
        res = compute(s, t, run["cfg"], start, end, run["kind"])
        state = forced or ("completed" if res["quality"]["ok"] else "incomplete")
        if state == "incomplete" and not reason:
            reason = "; ".join(res["quality"]["reasons"])
        res["quality"]["effective_window_s"] = (end - start) / 1000
        with self.lock:
            if not self.db.execute("SELECT 1 FROM trials WHERE id=? AND state='running'", (run["id"],)).fetchone():
                return self.get(run["id"])   # outra thread (tick × stop) já encerrou este ensaio
            try:
                self.db.executemany("INSERT INTO trial_samples(trial_id," + SCOLS + ") VALUES(?" + ",?" * 10 + ")", [(run["id"],) + tuple(r) for r in s])
                self.db.executemany("INSERT INTO trial_tips(trial_id,ts,src) VALUES(?,?,?)", [(run["id"], a, b) for a, b in t])
                self.db.execute("UPDATE trials SET state=?, end_ts=?, finished_wall=?, reason=?, result=? WHERE id=? AND state='running'",
                                (state, end, int(time.time() * 1000), reason, json.dumps(res), run["id"]))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        log.info("ensaio %s encerrado: estado=%s motivo=%s amostras=%d basculadas=%d cobertura=%.0f/%.0f s", run["id"], state, reason,
                 len(s), len(t), res["quality"]["covered_s"], res["quality"]["window_s"])
        self._live = (0.0, None, None, 0)
        return self.get(run["id"])
