"""Emulador do servidor web do CR1000X (só para teste). Imita o que a documentação oficial descreve:
GET /?command=DataQuery&uri=dl:<tabela>&mode=most-recent|since-record&p1=..&p3=..&format=json
-> CSIJSON {head:{fields:[...]}, data:[{time,no,vals}]}, "NAN" como texto, autenticação Basic.
Os dados são FICTÍCIOS. Controle de teste: ?command=_outage&on=1|0 , ?command=_state"""
import base64, json, threading, time, urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TABLES = {"Medidas": [], "Basculadas": []}
MEAS = ["Mass_g", "Temp_C", "Cor_mA", "Cor_Flow", "Cor_Status", "TipsTotal", "NBytesBal", "BalRaw", "Batt_V"]
TIPS = ["TipsInScan", "TipsTotal"]
S = {"outage": False, "mass": 1000.0, "tips": 0, "no_m": 0, "no_t": 0, "ring": 100000, "user": "dash", "pw": "segredo", "t": None, "i": 0, "oor_every": 0}
lock = threading.Lock()


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S") + ".00"


def step(t):
    """Gera 1 registro por segundo; 1 basculada a cada 6 g (fictício). Formato da balança INVENTADO só para o teste."""
    S["i"] += 1
    S["mass"] += 0.1
    tips_now = 0
    if int(S["mass"] // 6) > int((S["mass"] - 0.1) // 6):
        tips_now, S["tips"] = 1, S["tips"] + 1
    ma = 12.0 + (S["i"] % 40) / 10.0
    if S["oor_every"] and S["i"] % S["oor_every"] == 0:
        ma = 3.6
    raw = "ST,GS,+%9.1f g" % S["mass"]
    vals = [None, 21.8, ma, "NAN", 0 if 4 <= ma <= 20 else 1, S["tips"], len(raw) + 2, raw, 12.6]
    vals[0] = "NAN"  # fase 1: a balança vem só como texto bruto
    with lock:
        for name, recs, v in (("Medidas", TABLES["Medidas"], vals),):
            S["no_m"] += 1
            recs.append((S["no_m"] - 1, stamp(t), v))
            del recs[:-S["ring"]]
        if tips_now:
            S["no_t"] += 1
            TABLES["Basculadas"].append((S["no_t"] - 1, stamp(t), [tips_now, S["tips"]]))


def run_generator(seconds_per_tick=1.0):
    while True:
        S["t"] += timedelta(seconds=1)
        step(S["t"])
        time.sleep(seconds_per_tick)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if q.get("command") == "_outage":
            S["outage"] = q.get("on") == "1"
            return self._send(200, "{}")
        if q.get("command") == "_state":
            with lock:
                return self._send(200, json.dumps({"no_m": S["no_m"], "no_t": S["no_t"], "tips": S["tips"]}))
        if S["outage"]:
            return self.send_error(503)
        want = "Basic " + base64.b64encode(f"{S['user']}:{S['pw']}".encode()).decode()
        if self.headers.get("Authorization") != want:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="fake"')
            self.end_headers()
            return
        if q.get("command") != "DataQuery":
            return self.send_error(404)
        table = q.get("uri", "").replace("dl:", "")
        if table not in TABLES:
            return self.send_error(404)
        with lock:
            recs, mode = list(TABLES[table]), q.get("mode")
        more = False
        if mode == "most-recent":
            sel = recs[-int(q.get("p1", 1)):]
        elif mode == "since-record":
            p1, p3 = int(q.get("p1", 0)), 500   # o servidor real decide o tamanho do bloco e avisa com "more"
            sel = [r for r in recs if r[0] >= p1]
            if not sel and recs and p1 > recs[-1][0]:   # 30/10: como a API real (e o emulador v3/v4), um registro que AINDA NAO existe responde do mais antigo
                sel = list(recs)
            sel = sel[:p3 + 1]
            more, sel = len(sel) > p3, sel[:p3]  # pedido mais antigo que o disponível é "avançado" ao mais antigo (clamp)
        else:
            return self.send_error(400)
        names = MEAS if table == "Medidas" else TIPS
        body = {"head": {"transaction": 0, "signature": 1, "environment": {"table_name": table, "model": "CR1000X"},
                         "fields": [{"name": n, "type": "xsd:float", "process": "Smp"} for n in names]},
                "data": [{"time": t, "no": no, "vals": v} for no, t, v in sel], "more": more}
        self._send(200, json.dumps(body))

    def _send(self, code, text):
        b = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=UTF-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def start(port=0, prefill=600, **kw):
    S.update(kw)
    S["t"] = datetime.now() - timedelta(seconds=prefill)
    for _ in range(prefill):
        S["t"] += timedelta(seconds=1)
        step(S["t"])
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=run_generator, daemon=True).start()
    return srv
