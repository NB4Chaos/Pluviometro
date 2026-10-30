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
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
    cor_ma: float | None = None  # sinal 4–20 mA do Medidor de Vazão, exatamente como o datalogger entrega (sem conversão), MESMO fora da faixa
    cor_status: str | None = "ok"  # perfil "flow": ok = havia registro do medidor | no_comm; None = sem variavel no programa. A classificacao (faixa, alarme) e do servidor
    flow_mode: str | None = None    # modo informado pelo PROGRAMA (Flow_mode: 1 pulso, 2 analogico). Legado: o metodo do calculo e escolhido no servidor
    flow_pulses: float | None = None  # pulsos brutos contados no Scan (contagem, NAO frequencia)
    flow_hz: float | None = None      # so programas antigos que gravavam Hz; nos demais o servidor calcula pulsos / janela real
    flow_pulses_total: int | None = None  # contador acumulado do datalogger (Flow_PulsosTot), quando o programa tem
    flow_ma_code: int | None = None       # codigo bruto do canal analogico (Flow_Status)
    flow_pulse_code: int | None = None    # codigo bruto do canal de pulsos (Flow_PStatus)
    flow_dt_ms: int | None = None         # janela de contagem: intervalo ate o registro anterior da tabela do medidor
    flow_has: tuple = ()                  # canais que o programa fornece: ("analog", "pulse")
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


def _int(v):
    x = _num(v)
    return None if x is None else int(x)


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


class CR1000X(Datalogger):
    """Le as tabelas do CR1000X pela API web (DataQuery, mode=since-record), sempre pelo numero do registro.

    Quais tabelas/campos usar vem do perfil (profiles/*.json; padrao: programa_atual, ou a variavel CR1000X_PROFILE).
    Se a rede cair, o datalogger continua gravando e na volta recuperamos tudo a partir do ultimo registro confirmado
    (cursor guardado em disco). Senha: variavel de ambiente DATALOGGER_PASSWORD. Use conta SOMENTE LEITURA. Prefira HTTPS.
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
        # canais do medidor que o PROGRAMA carregado fornece (lidos do cabecalho da tabela; perfil "cor" antigo = so 4-20 mA)
        self.flow_has = ("analog",) if self.profile.get("cor") else ()
        # Texto bruto da balanca (so perfis sem campo numerico): BAL_REGEX tem UM grupo que captura o numero.
        self.regex = re.compile(os.environ["BAL_REGEX"]) if os.environ.get("BAL_REGEX") else None
        self.factor = float(os.environ.get("BAL_FACTOR", "1"))
        self.cursor_file = cursor_file or os.path.join(os.environ.get("ELUS_DATA_DIR") or BASE, "cursor_cr1000x.json")
        try:
            with open(self.cursor_file, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.next = {k: v for k, v in saved.items() if not k.startswith("_")}
        self.anchor_time = dict(saved.get("_anchor_time") or {})   # horario do ultimo registro entregue de cada tabela (prova de continuidade)
        self.pending, self.pending_time, self.seen = {}, {}, {}    # seen = horario (ms) do ultimo registro ja entregue de cada tabela
        self.fields = {}                   # tabela -> nomes dos campos do programa carregado (cabecalho da ultima resposta)
        self._nojoin = {self.profile['tips']['table']} if self.profile['tips'].get('sparse') else set()   # tabelas esparsas (so tem registro quando ha evento): ausencia nao e erro
        self.join_miss = {}                # tabela -> amostras sem registro correspondente (diagnostico de horario)
        # Leitura das tabelas em paralelo: o mesmo numero de consultas por ciclo, em menos tempo SE o datalogger atender
        # requisicoes simultaneas. Desligada por padrao; ligar com DATALOGGER_PARALLEL=1 e comparar "consulta p50" no log.
        self.parallel = os.environ.get("DATALOGGER_PARALLEL", "0") == "1"
        self._pool = None
        self._lock = threading.Lock()      # contadores de diagnostico (lacunas, reinicios) compartilhados entre as tabelas
        if self.parallel:
            log.info("Leitura das tabelas do datalogger em paralelo (DATALOGGER_PARALLEL=1)")

    def _get(self, table, mode, p1=None):
        """Uma consulta DataQuery. Devolve (registros, more): `more` = o servidor ainda tem registros a entregar."""
        q = {"command": "DataQuery", "uri": f"dl:{table}", "mode": mode, "format": "json"}
        if p1 is not None:
            q["p1"] = p1
        req = urllib.request.Request(self.base + "/?" + urllib.parse.urlencode(q, safe=":"), headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
            d = json.load(r)
        names = [f["name"] for f in d["head"]["fields"]]
        self.fields[table] = tuple(names)
        return [(rec["no"], rec["time"], dict(zip(names, rec["vals"]))) for rec in d["data"]], bool(d.get("more"))

    def _pull(self, table):
        """Registros novos da tabela, pelo numero do registro.

        Pede SEMPRE a partir do ultimo registro ja entregue (ancora) e o descarta. Assim nunca se pede um registro que o
        datalogger ainda nao gravou: nesse caso a API responde a partir do registro MAIS ANTIGO da tabela, o que antes era
        confundido com "tabela reiniciada" (relia a tabela inteira e regravava o historico com juncoes vazias).
          1o registro = ancora (mesmo no e mesmo horario) -> continuidade comprovada; descarta a ancora
          1o registro < ancora                            -> tabela recriada (programa reenviado): os registros ja sao da nova
          1o registro = ancora, mas com outro horario     -> tabela recriada que ja passou do no antigo: rele desde o inicio
          1o registro > ancora                            -> a ancora foi sobrescrita na memoria circular: lacuna (dados perdidos)
        """
        out, nxt = [], self.next.get(table)
        anchor = nxt - 1 if nxt else None
        for _ in range(self.max_pages):
            recs, more = self._get(table, "since-record", p1=anchor if anchor is not None else (nxt or 0))
            if anchor is not None:
                known = self.anchor_time.get(table)
                if not recs:   # a ancora nao existe e nada veio: tabela recriada (com menos registros que o cursor) ou vazia
                    last, _ = self._get(table, "most-recent", p1=1)
                    self._restart(table, anchor, last[0][0] if last else None)
                    nxt = anchor = None
                    if last:
                        continue   # rele desde o primeiro registro nesta mesma consulta
                    break
                no, tm = recs[0][0], recs[0][1]
                if no == anchor and known not in (None, tm):
                    self._restart(table, anchor, f"{no} com outro horario ({tm} em vez de {known})")
                    nxt = anchor = None
                    continue
                if no < anchor:
                    self._restart(table, anchor, no)
                    nxt = None
                elif no > anchor:
                    with self._lock:
                        self.gaps += 1
                    log.warning("Lacuna em %s: o ultimo registro lido (%s) nao existe mais no datalogger; o mais antigo disponivel e %s",
                                table, anchor, no)
                else:
                    recs = recs[1:]
                anchor = None
            out += recs
            if recs:
                nxt = recs[-1][0] + 1
            if not more:  # CsiJSON: o servidor pode dividir a resposta e avisa com "more"
                break
        self.pending[table] = nxt
        return out

    def _pull_all(self, tables):
        """Registros novos de todas as tabelas do ciclo: uma depois da outra (padrao) ou ao mesmo tempo (DATALOGGER_PARALLEL=1).
        Cada tabela tem cursor e ancora proprios; erro em qualquer uma derruba o ciclo inteiro, como na leitura sequencial."""
        if not self.parallel or len(tables) < 2:
            return {t: self._pull(t) for t in tables}
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=len(tables), thread_name_prefix="datalogger")
        return dict(zip(tables, self._pool.map(self._pull, tables)))

    def _restart(self, table, anchor, got):
        with self._lock:
            self.restarts += 1
        log.warning("Tabela %s reiniciada (programa reenviado?): o ultimo registro lido era %s e o datalogger devolveu %s; "
                    "recomecando do primeiro registro", table, anchor, got)
        self.seen.pop(table, None)
        self.anchor_time.pop(table, None)

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

    def _reading(self, ts, rows):
        P = self.profile
        mass, ms = self._mass(P["mass"], rows.get(P["mass"]["table"]))
        tv = rows.get(P["temp"]["table"])
        temp = _num(tv.get(P["temp"]["value"])) if tv else None
        ts_ = "ok" if temp is not None else ("invalid" if tv else "no_comm")
        ma, cs = None, None   # None = o programa nao tem variavel de vazao: nao e falha, e "aguardando integracao"
        if P.get("cor"):
            cs = "no_comm"
            cv = rows.get(P["cor"]["table"])
            if cv:
                ma = _num(cv.get(P["cor"]["ma"]))
                bad = "status" in P["cor"] and int(_num(cv.get(P["cor"]["status"])) or 0) in P["cor"].get("status_bad", [])
                cs = "ok" if ma is not None and not bad else "no_comm"
                ma = ma if cs == "ok" else None
        mode = pulses = hz = ptot = mcode = pcode = dt = None
        has = self.flow_has
        fl = P.get("flow")
        if fl:   # medidor de vazao: canal 4-20 mA e, se o programa tiver, canal de pulsos, tudo da MESMA tabela e SEM classificar aqui
            names = self.fields.get(fl["table"]) or ()
            has = self.flow_has = tuple(c for c, key in (("analog", "ma"), ("pulse", "pulses")) if fl.get(key) and fl[key] in names)
            fv = rows.get(fl["table"])
            if fv is None:
                cs = "no_comm"
            else:
                cs = "ok"   # o registro chegou; faixa, alarme e validade de cada canal sao decididos no servidor (calc.flow_reading)
                ma = _num(fv.get(fl["ma"])) if "analog" in has else None
                mcode = _int(fv.get(fl.get("status", "")))
                mode = {1: "pulse", 2: "analog"}.get(_int(fv.get(fl.get("mode", ""))))
                if "pulse" in has:
                    pulses = _num(fv.get(fl["pulses"]))
                    ptot = _int(fv.get(fl.get("pulses_total", "")))
                    pcode = _int(fv.get(fl.get("pulse_status", "")))
                if fl.get("freq") and fl["freq"] in names:   # programas antigos que gravavam a frequencia pronta
                    hz = _num(fv.get(fl["freq"]))
                dt = fv.get("__dt_ms")
        return Reading(mass_g=mass, temp_c=temp, mass_status=ms, temp_status=ts_, cor_ma=ma, cor_status=cs, ts=ts,
                       flow_mode=mode, flow_pulses=pulses, flow_hz=hz, flow_pulses_total=ptot, flow_ma_code=mcode,
                       flow_pulse_code=pcode, flow_dt_ms=dt, flow_has=has)

    def read(self):
        P = self.profile
        dense = {s["table"] for s in (P["mass"], P["temp"], P.get("cor"), P.get("flow")) if s}
        if not P["tips"].get("sparse"):
            dense.add(P["tips"]["table"])
        tables = sorted(dense | {P["tips"]["table"]})  # tabela "sparse" = de eventos: so tem registro quando ha basculada
        pulled = self._pull_all(tables)
        # As tabelas sao gravadas uma depois da outra. So entregamos ate o instante em que TODAS ja chegaram
        # (marca d'agua); o resto fica no datalogger e e lido de novo na proxima rodada, sem avancar o cursor.
        marks = [_ts_ms(pulled[t][-1][1]) if pulled[t] else self.seen.get(t) for t in sorted(dense)]
        if any(m is None for m in marks):
            self.pending, self.pending_time = {}, {}
            return []
        wm = max(min(marks) + JOIN_TOL_MS, max(marks) - 5000)   # tolerância do casamento; e uma tabela parada há > 5 s não segura as outras (vira "sem comunicação")
        ft = P["flow"]["table"] if P.get("flow") else None
        for t in tables:
            keep = [r for r in pulled[t] if t not in dense or _ts_ms(r[1]) <= wm]  # evento esparso: entrega tudo que ja chegou
            pulled[t] = keep
            if t == ft:   # janela de contagem de cada registro do medidor = intervalo real ate o registro anterior da tabela
                prev = self.seen.get(t)
                for _, tm, v in keep:
                    cur = _ts_ms(tm)
                    v["__dt_ms"] = None if prev is None else cur - prev
                    prev = cur
            if keep:
                self.pending[t] = keep[-1][0] + 1
                self.pending_time[t] = keep[-1][1]
                self.seen[t] = _ts_ms(keep[-1][1])
            elif pulled_any(t, self.pending):
                self.pending.pop(t, None)
                self.pending_time.pop(t, None)
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
            self.anchor_time.update(self.pending_time)
            self.pending, self.pending_time = {}, {}
            tmp = self.cursor_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({**self.next, "_anchor_time": self.anchor_time}, f)
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
