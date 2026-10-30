"""Camada de comunicação com o datalogger.

O servidor só conhece a interface `Datalogger.read()`. O adaptador `CR1000X` lê as tabelas do
datalogger real pela API web oficial (DataQuery). Nada aqui gera ou simula medições.
"""
from __future__ import annotations

import base64
import bisect
import json
import math
import logging
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("datalogger")
JOIN_TOL_MS = 500   # tolerancia ao casar registros de tabelas diferentes do mesmo Scan


@dataclass
class Reading:
    """Uma leitura. Valor None = indisponível. Status: ok | no_comm | invalid."""
    mass_g: float | None = None
    temp_c: float | None = None
    tips: list = field(default_factory=list)  # basculadas novas: ts em ms, ou (ts, chave_unica) para nunca contar duas vezes
    mass_status: str = "ok"
    temp_status: str = "ok"
    cor_ma: float | None = None  # sinal 4–20 mA do Medidor de Vazão, EXATAMENTE como o datalogger entrega (bruto, mesmo fora da faixa)
    cor_status: str | None = "ok"  # canal analogico: ok (mA finito) | invalid (NAN) | no_comm | None = sem variavel no programa
    flow_mode: str | None = None    # modo informado pelo datalogger: "pulse" | "analog" | None (so informativo; o metodo e do servidor)
    flow_pulses: float | None = None  # pulsos brutos contados em P2 no ultimo Scan (Flow_Pulsos); None = invalido/indisponivel
    flow_pulses_total: int | None = None  # contador acumulado do datalogger (Flow_PulsosTot); reinicia com o programa
    flow_hz: float | None = None      # pulsos / intervalo do Scan (derivado; o dado primario e flow_pulses)
    pulse_status: str | None = None   # canal de pulsos: ok | invalid | no_comm | None = sem variavel no programa
    flow_channels: dict = field(default_factory=lambda: {"analog": False, "pulse": False})  # canais que o PROGRAMA em execucao fornece
    ts: int | None = None       # horário da medição em ms; None = agora (dados históricos recuperados trazem o próprio horário)
    sample: bool = True         # False = só carrega eventos (sem linha de medição)


class Datalogger:
    buffered = False  # True: o equipamento guarda os dados e eles são recuperados depois de uma queda de rede

    def _match(self, table, ts, rows, keys):
        """Registro da tabela para o horario `ts`. Exato; senao o mais proximo ate JOIN_TOL_MS (as tabelas sao gravadas no mesmo
        Scan, mas o horario pode divergir por milissegundos). Sem correspondencia: None (vira 'sem comunicacao') e fica contado."""
        v = rows.get(ts)
        if v is not None or not keys:
            if v is None and table not in self._nojoin:
                self._miss(table, ts, None)
            return v
        i = bisect.bisect_left(keys, ts)
        best = min((k for k in keys[max(0, i - 1):i + 1]), key=lambda k: abs(k - ts), default=None)
        if best is not None and abs(best - ts) <= JOIN_TOL_MS:
            return rows[best]
        self._miss(table, ts, best)
        return None

    def _miss(self, table, ts, near):
        n = self.join_miss[table] = self.join_miss.get(table, 0) + 1
        if n in (1, 10, 100) or n % 1000 == 0:   # nao inunda o log
            log.warning("Sem registro de %s para %s (mais proximo: %s); %d ocorrencias", table, ts, near, n)

    def read(self):
        """Devolve um Reading ou uma lista de Reading (em ordem de horário)."""
        raise NotImplementedError

    def ack(self):
        """Chamado depois que o servidor GRAVOU o que read() devolveu."""


def _ts_ms(s: str) -> int:
    """"2026-10-19T12:34:56.25" -> ms. Hora LOCAL sem fuso: datalogger e servidor precisam estar no mesmo fuso/hora."""
    base, _, frac = s.partition(".")
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    return int(dt.timestamp() * 1000) + (int(float("0." + frac) * 1000) if frac else 0)


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None  # a API entrega "NAN" como texto
    return x if math.isfinite(x) else None   # "NAN"/"INF" chegam como texto; nenhum dos dois é medida


BASE = os.path.dirname(os.path.abspath(__file__))


def pulled_any(t, pending):
    return t in pending


def load_profile(name):
    """Perfil = quais tabelas e campos do SEU programa CRBasic alimentam cada grandeza (pasta profiles/)."""
    path = name if name.endswith(".json") else os.path.join(BASE, "profiles", name + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        raise ValueError(f"Perfil do datalogger nao encontrado: {path}")


def _anchor(v):
    """Cursor em disco -> ancora {no, time}. Formato antigo (inteiro = PROXIMO registro a pedir) vira ancora no-1 sem horario."""
    if isinstance(v, dict) and "no" in v:
        return {"no": int(v["no"]), "time": v.get("time")}
    if isinstance(v, (int, float)) and v >= 1:
        return {"no": int(v) - 1, "time": None}
    return None


class CR1000X(Datalogger):
    """Le as tabelas do CR1000X pela API web (DataQuery, mode=since-record), sempre pelo numero do registro.

    Cursor por REGISTRO-ANCORA: guarda o ultimo registro recebido (numero + horario) e pede a partir DELE, nunca de um registro que
    ainda nao existe (a API responde a um numero inexistente a partir do registro mais antigo, o que fazia o servidor reler e
    regravar horas de historico). A ancora e descartada da resposta; so se ela sumiu ou mudou de horario e que houve reinicio
    ou lacuna de verdade.
    Quais tabelas/campos usar vem do perfil (profiles/*.json; padrao: programa_atual, ou a variavel CR1000X_PROFILE).
    Senha: variavel de ambiente DATALOGGER_PASSWORD. Use conta SOMENTE LEITURA. Prefira HTTPS.
    """
    buffered = True

    def __init__(self, address="", user="", password=None, scheme="http", cursor_file=None, profile=None, **_):
        self.base = f"{scheme}://{address}"
        pw = password if password is not None else os.environ.get("DATALOGGER_PASSWORD", "")
        self.auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
        self.timeout, self.max_pages, self.gaps, self.restarts = 5, 20, 0, 0
        self.ctx = None
        if scheme == "https":
            self.ctx = ssl.create_default_context(cafile=os.environ.get("DATALOGGER_CA") or None)
            if os.environ.get("DATALOGGER_TLS_VERIFY", "1") == "0":  # so para teste: certificado autoassinado
                self.ctx.check_hostname, self.ctx.verify_mode = False, ssl.CERT_NONE
        self.profile = load_profile(profile or os.environ.get("CR1000X_PROFILE") or "programa_atual")
        self.has_flow = bool(self.profile.get("cor") or self.profile.get("flow"))  # sem variavel de vazao no programa: o Medidor de Vazao fica 'aguardando integracao'
        self.scan_ms = int(self.profile.get("scan_ms") or 1000)   # intervalo do Scan do CRBasic: resolucao temporal real dos registros
        log.info("perfil %s carregado (medidor de vazao no programa: %s; Scan de %d ms)", self.profile.get("nome"), "sim" if self.has_flow else "nao", self.scan_ms)
        # Texto bruto da balanca (so perfis sem campo numerico): BAL_REGEX tem UM grupo que captura o numero.
        self.regex = re.compile(os.environ["BAL_REGEX"]) if os.environ.get("BAL_REGEX") else None
        self.factor = float(os.environ.get("BAL_FACTOR", "1"))
        self.cursor_file = cursor_file or os.path.join(os.environ.get("ELUS_DATA_DIR") or BASE, "cursor_cr1000x.json")
        try:
            with open(self.cursor_file, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        self.next = {t: a for t, v in raw.items() if (a := _anchor(v)) is not None}   # tabela -> ancora {no, time}
        self.pending, self.seen = {}, {}   # seen = horario do ultimo registro ja entregue de cada tabela
        self.fields = {}                   # tabela -> nomes dos campos vistos na ultima resposta (quais canais o programa fornece)
        self._nojoin = {self.profile['tips']['table']} if self.profile['tips'].get('sparse') else set()   # tabelas esparsas (so tem registro quando ha evento): ausencia nao e erro
        self.join_miss = {}                # tabela -> amostras sem registro correspondente (diagnostico de horario)

    def _get(self, table, mode, p1=None):
        """Uma consulta DataQuery. Devolve (registros, more): `more` = o servidor ainda tem registros a entregar."""
        q = {"command": "DataQuery", "uri": f"dl:{table}", "mode": mode, "format": "json"}
        if p1 is not None:
            q["p1"] = p1
        req = urllib.request.Request(self.base + "/?" + urllib.parse.urlencode(q, safe=":"), headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
            d = json.load(r)
        names = [f["name"] for f in d["head"]["fields"]]
        self.fields[table] = names
        return [(rec["no"], rec["time"], dict(zip(names, rec["vals"]))) for rec in d["data"]], bool(d.get("more"))

    def _pull(self, table):
        """Registros NOVOS da tabela desde a ancora (ultimo registro ja recebido). Nunca pede um registro inexistente."""
        anc = _anchor(self.next.get(table))
        out, p1, first_page = [], (0 if anc is None else anc["no"]), True
        for _ in range(self.max_pages):
            recs, more = self._get(table, "since-record", p1=p1)
            if not recs:
                break
            if first_page and anc is not None:
                no0, t0 = recs[0][0], recs[0][1]
                if no0 == anc["no"] and (anc["time"] is None or t0 == anc["time"]):
                    recs = recs[1:]                       # a ancora veio de volta: descarta; o resto e novo
                elif no0 <= anc["no"]:                    # numeracao voltou (ou mesmo numero com outro horario): tabela recriada
                    self.restarts += 1
                    log.warning("Tabela %s reiniciada: ancora %s/%s, veio %s/%s; recomecando sem perder o historico", table, anc["no"], anc["time"], no0, t0)
                    self.seen.pop(table, None)
                else:                                     # a ancora saiu do anel: registros perdidos na memoria do datalogger
                    self.gaps += 1
                    log.warning("Lacuna em %s: ancora %s ja nao existe; o mais antigo disponivel e %s", table, anc["no"], no0)
            first_page = False
            out += recs
            if not more or not recs:  # CsiJSON: o servidor pode dividir a resposta e avisa com "more"
                break
            p1 = recs[-1][0] + 1       # proxima pagina: so quando o servidor garante que ela existe (more)
        if out:
            self.pending[table] = {"no": out[-1][0], "time": out[-1][1]}
        return out

    # ---- interpretacao de cada grandeza, conforme o perfil ----
    def _mass(self, spec, v):
        if v is None:
            return None, "no_comm"
        val = _num(v.get(spec["value"]))
        if val is not None:
            val *= spec.get("factor", 1.0)
        if "status" in spec:
            code = _num(v.get(spec["status"]))
            st = spec["status_map"].get(str(int(code)), "invalid") if code is not None else "no_comm"
            if st == "ok" and val is None:
                st = "invalid"
            return (val if st == "ok" else None), st
        raw, nbytes = (v.get(spec.get("raw", "")) or "").strip(), int(_num(v.get(spec.get("nbytes", ""))) or 0)
        if val is None and self.regex and raw:
            m = self.regex.search(raw)
            try:
                val = float(m.group(1).replace(" ", "")) * self.factor if m else None
            except ValueError:
                val = None
        if val is None:
            return None, ("no_comm" if (nbytes == 0 or not raw) else "invalid")
        return val, "ok"

    def _flow(self, fl, fv):
        """Medidor de vazao (tabela Vazao1s): os canais que o programa fornece, com o dado BRUTO de cada um.

        analogico: cor_ma = Flow_mA como veio (mesmo fora de 4-20 mA: quem classifica e o servidor); NAN => invalid.
        pulsos   : flow_pulses = Flow_Pulsos (contagem bruta do Scan), flow_pulses_total = Flow_PulsosTot; Flow_PStatus <> 0 => invalid.
        Campo ausente na tabela (programa v3) => canal indisponivel (status None), nao falha."""
        names = self.fields.get(fl["table"]) or []
        ch = {"analog": fl.get("ma") in names, "pulse": bool(fl.get("pulses")) and fl["pulses"] in names}
        out = {"flow_mode": None, "cor_ma": None, "cor_status": None, "flow_pulses": None, "flow_pulses_total": None, "flow_hz": None,
               "pulse_status": None, "flow_channels": ch}
        if fv is None:
            out["cor_status"] = "no_comm" if ch["analog"] else None
            out["pulse_status"] = "no_comm" if ch["pulse"] else None
            return out
        out["flow_mode"] = {1: "pulse", 2: "analog"}.get(int(_num(fv.get(fl["mode"])) or 0)) if fl.get("mode") else None
        if ch["analog"]:
            ma = _num(fv.get(fl["ma"]))
            code = _num(fv.get(fl["status"])) if fl.get("status") else 0
            if ma is None or code is None or int(code) == 3:   # 3 = sem leitura (NAN) no programa v4
                out["cor_status"] = "invalid"
            else:
                out["cor_ma"], out["cor_status"] = ma, "ok"
        if ch["pulse"]:
            n = _num(fv.get(fl["pulses"]))
            ps = _num(fv.get(fl["pstatus"])) if fl.get("pstatus") else 0
            tot = _num(fv.get(fl["pulses_total"])) if fl.get("pulses_total") else None
            out["flow_pulses_total"] = int(tot) if tot is not None else None
            if n is None or ps is None or int(ps) != 0:
                out["pulse_status"] = "invalid"
            else:
                out["flow_pulses"], out["pulse_status"] = n, "ok"
                out["flow_hz"] = n / (self.scan_ms / 1000.0)
        return out

    def _reading(self, ts, rows):
        P = self.profile
        mass, ms = self._mass(P["mass"], rows.get(P["mass"]["table"]))
        tv = rows.get(P["temp"]["table"])
        temp = _num(tv.get(P["temp"]["value"])) if tv else None
        ts_ = "ok" if temp is not None else ("invalid" if tv else "no_comm")
        extra = {"cor_status": None}   # sem variavel de vazao no programa: nao e falha, e "aguardando integracao"
        if P.get("cor"):   # perfis antigos (elus_calib): so o sinal em mA, sem tabela de vazao propria
            cs, ma = "no_comm", None
            cv = rows.get(P["cor"]["table"])
            if cv:
                ma = _num(cv.get(P["cor"]["ma"]))
                bad = "status" in P["cor"] and int(_num(cv.get(P["cor"]["status"])) or 0) in P["cor"].get("status_bad", [])
                cs = "ok" if ma is not None and not bad else ("invalid" if ma is None and cv else "no_comm")
                ma = ma if cs == "ok" else None
            extra = {"cor_ma": ma, "cor_status": cs, "flow_channels": {"analog": True, "pulse": False}}
        fl = P.get("flow")
        if fl:
            extra = self._flow(fl, rows.get(fl["table"]))
        return Reading(mass_g=mass, temp_c=temp, mass_status=ms, temp_status=ts_, ts=ts, **extra)

    def read(self):
        P = self.profile
        dense = {s["table"] for s in (P["mass"], P["temp"], P.get("cor"), P.get("flow")) if s}
        if not P["tips"].get("sparse"):
            dense.add(P["tips"]["table"])
        tables = sorted(dense | {P["tips"]["table"]})  # tabela "sparse" = de eventos: so tem registro quando ha basculada
        pulled = {t: self._pull(t) for t in tables}
        # As tabelas sao gravadas uma depois da outra. So entregamos ate o instante em que TODAS ja chegaram
        # (marca d'agua); o resto fica no datalogger e e lido de novo na proxima rodada, sem avancar o cursor.
        marks = [_ts_ms(pulled[t][-1][1]) if pulled[t] else self.seen.get(t) for t in sorted(dense)]
        if any(m is None for m in marks):
            self.pending = {}
            return []
        wm = max(min(marks) + JOIN_TOL_MS, max(marks) - 5000)   # tolerância do casamento; e uma tabela parada há > 5 s não segura as outras (vira "sem comunicação")
        for t in tables:
            keep = [r for r in pulled[t] if t not in dense or _ts_ms(r[1]) <= wm]  # evento esparso: entrega tudo que ja chegou
            pulled[t] = keep
            if keep:
                self.pending[t] = {"no": keep[-1][0], "time": keep[-1][1]}
                self.seen[t] = _ts_ms(keep[-1][1])
            elif pulled_any(t, self.pending):
                self.pending.pop(t, None)
        by_ts = {t: {_ts_ms(tm): v for _, tm, v in recs} for t, recs in pulled.items()}
        keys = {t: sorted(d) for t, d in by_ts.items()}
        readings = []
        for _, tm, v in pulled[P["mass"]["table"]]:
            ts = _ts_ms(tm)
            readings.append(self._reading(ts, {t: self._match(t, ts, by_ts[t], keys[t]) for t in tables}))
        ev = []
        for no, tm, v in pulled[P["tips"]["table"]]:  # cada registro = 1 segundo com N basculadas
            n = int(round(_num(v.get(P["tips"]["count"])) or 0))
            ev += [(_ts_ms(tm), f"{P['tips']['table']}:{no}:{tm}:{k}") for k in range(max(n, 0))]
        if ev:
            if not readings:
                readings = [Reading(sample=False)]
            readings[0].tips = ev   # entram antes de qualquer amostra do lote: o total por amostra já as conta
        return readings

    def channels(self):
        """Canais do medidor que o programa em execucao fornece, pelos campos vistos na ultima resposta da tabela de vazao."""
        fl = self.profile.get("flow")
        if not fl:
            return {"analog": bool(self.profile.get("cor")), "pulse": False}
        names = self.fields.get(fl["table"]) or []
        return {"analog": fl.get("ma") in names, "pulse": bool(fl.get("pulses")) and fl["pulses"] in names}

    def health(self):
        """Diagnostico SO LEITURA, fora do ciclo de aquisicao: desvio do relogio (ClockCheck) e scans perdidos (tabela Status).
        Devolve {clock_offset_s, skipped_scans, prog_name}; campo None = nao disponivel. Nunca levanta excecao."""
        out = {"clock_offset_s": None, "skipped_scans": None, "prog_name": None}
        try:
            q = urllib.parse.urlencode({"command": "ClockCheck", "format": "json"})
            req = urllib.request.Request(self.base + "/?" + q, headers={"Authorization": self.auth})
            t0 = datetime.now()
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                d = json.load(r)
            if d.get("time"):
                out["clock_offset_s"] = round((_ts_ms(d["time"]) - int(t0.timestamp() * 1000)) / 1000, 1)   # datalogger - PC
        except Exception as e:   # diagnostico nunca derruba a aquisicao
            log.debug("ClockCheck indisponivel: %s", e)
        try:
            recs, _ = self._get("Status", "most-recent", p1=1)
            if recs:
                v = recs[0][2]
                out["skipped_scans"] = _num(v.get("SkippedScan"))
                out["prog_name"] = v.get("ProgName")
        except Exception as e:
            log.debug("Tabela Status indisponivel: %s", e)
        return out

    def ack(self):
        if self.pending:
            self.next.update(self.pending)
            self.pending = {}
            tmp = self.cursor_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.next, f)
                f.flush()
                os.fsync(f.fileno())   # queda de energia não deixa o cursor vazio (senão a volta relê tudo desde o registro 0)
            for i in range(3):   # Windows: antivirus/OneDrive/indexador seguram o arquivo por ms; tenta de novo antes de desistir
                try:
                    os.replace(tmp, self.cursor_file)
                    return
                except PermissionError:
                    time.sleep(0.1)
            log.warning("Cursor nao gravado em disco (arquivo em uso por outro programa); segue em memoria e tenta no proximo ciclo")


def make_datalogger(comm: dict) -> Datalogger:
    return CR1000X(address=comm.get("address", ""), user=comm.get("user", ""), scheme=comm.get("protocol", "http"),
                   profile=comm.get("profile"))
