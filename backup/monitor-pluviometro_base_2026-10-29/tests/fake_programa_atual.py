"""Emulador do CR1000X rodando o PROGRAMA ATUAL do usuário (tabelas Balanca1s, Termopar1s, Pluviometro1s, Resumo).
Imita a API web oficial (DataQuery, since-record / most-recent, Basic auth, valores "NAN" como texto).
TODOS os dados são FICTÍCIOS; o texto da balança é INVENTADO só para o teste (o formato real da MK30K1 não é conhecido)."""
import base64, json, math, threading, time, urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = {
    "Balanca1s": [("Peso_g", "xsd:float"), ("StatusBal", "xsd:long"), ("LinhaNova", "xsd:boolean"), ("BaudInUse", "xsd:long"), ("LastLine", "xsd:string")],
    "Termopar1s": [("TempAgua_C", "xsd:float"), ("PTemp_C", "xsd:float")],
    "Pluviometro1s": [("Pluvio_Basculadas_1s", "xsd:float"), ("Pluvio_Total", "xsd:float"), ("Pluvio_Chuva_mm", "xsd:float")],
    "Resumo": [("TotalOK", "xsd:long"), ("TotalFalha", "xsd:long"), ("FalhasSeguidas", "xsd:long")],
    # programa novo (Pluviometria_Vazao.CR1X): mesmos nomes das variáveis do CRBasic
    "Vazao1s": [("Flow_Mode", "xsd:long"), ("Flow_Pulsos_1s", "xsd:float"), ("Flow_Freq_Hz", "xsd:float"), ("Flow_mV", "xsd:float"),
                ("Flow_mA", "xsd:float"), ("Flow_Status", "xsd:long")],
}


class Fake:
    def __init__(self, prefill=120, lag=0.0, tip_every=20, ring=20000):
        self.lag, self.tip_every, self.ring = lag, tip_every, ring
        self.tables = {n: [] for n in FIELDS}
        self.next_no = {n: 0 for n in FIELDS}
        self.lock = threading.Lock()
        self.outage, self.user, self.pw = False, "dash", "segredo"
        self.level, self.clock_offset = 3, 0.0   # 3 = somente leitura; deslocamento do relogio do datalogger (s)
        self.force = []          # um dict por tick: {"status": 3} ou {"temp": "NAN"}
        self.flow_mode, self.flow_hz, self.flow_ma = 1, 100.0, 12.0   # 1 = pulsos (P2) | 2 = analógico (2H/2L)
        self.flow_status = 0
        self.mass, self.i, self.tips, self.pluvio_total = 1000.0, 0, 0, 0.0
        self.t = datetime.now() - timedelta(seconds=prefill)
        self.running = False
        for _ in range(prefill):
            self.tick(sleep=False)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                fake.handle(self)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    # ---- geração de dados (1 registro por segundo em cada tabela) ----
    def tick(self, sleep=True):
        self.t += timedelta(seconds=1)
        self.i += 1
        f = self.force.pop(0) if self.force else {}
        status = f.get("status", 0)
        self.mass += 0.1
        mass = "NAN" if status != 0 else round(self.mass, 1)
        line = "" if status == 1 else "ST,GS,+%9.1f g\r\n" % self.mass
        temp = f.get("temp", round(21.8 + 0.05 * math.sin(self.i / 30), 2))
        tip = 1.0 if self.i % self.tip_every == 0 else 0.0
        self.tips += int(tip)
        self.pluvio_total += tip
        rows = {"Balanca1s": [mass, status, status == 0, 9600, line],
                "Termopar1s": [temp, 24.1],
                "Pluviometro1s": [tip, self.pluvio_total, self.pluvio_total * 0.2]}
        if self.i % 60 == 0:
            rows["Resumo"] = [self.i, 0, 0]
        nan = "NAN"
        if self.flow_status != 0:
            rows["Vazao1s"] = [self.flow_mode, nan, nan, nan, nan, self.flow_status]
        elif self.flow_mode == 1:
            rows["Vazao1s"] = [1, self.flow_hz, self.flow_hz, nan, nan, 0]
        else:
            rows["Vazao1s"] = [2, nan, nan, self.flow_ma * 100, self.flow_ma, 0]   # shunt de 100 ohm
        stamp = self.t.strftime("%Y-%m-%dT%H:%M:%S") + ".00"
        for name, vals in rows.items():   # as tabelas são gravadas uma depois da outra: dá para cair no meio
            with self.lock:
                self.tables[name].append((self.next_no[name], stamp, vals))
                self.next_no[name] += 1
                del self.tables[name][:-self.ring]
            if sleep and self.lag:
                time.sleep(self.lag)

    def reset_total(self):          # o programa do datalogger reiniciou: Pluvio_Total volta a zero
        self.pluvio_total = 0.0

    def run(self, period=1.0):
        self.running = True
        def loop():
            while self.running:
                self.tick()
                time.sleep(period)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.server.shutdown()

    # ---- API web ----
    def handle(self, h):
        q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).items()}
        if self.outage:
            return h.send_error(503)
        want = "Basic " + base64.b64encode(f"{self.user}:{self.pw}".encode()).decode()
        if h.headers.get("Authorization") != want:
            h.send_response(401); h.send_header("WWW-Authenticate", 'Basic realm="fake"'); h.end_headers(); return
        cmd = q.get("command")
        if cmd in ("CheckAuthorization", "ClockCheck", "BrowseSymbols"):
            if cmd == "CheckAuthorization":
                body = {"authorization": self.level}
            elif cmd == "ClockCheck":
                body = {"outcome": 1, "time": (datetime.now() + timedelta(seconds=self.clock_offset)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4], "description": "The clock was checked"}
            else:
                body = {"symbols": [{"name": n, "uri": "dl:" + n, "type": 6, "is_enabled": True, "is_read_only": False, "can_expand": True} for n in self.tables]}
            b = json.dumps(body).encode()
            h.send_response(200); h.send_header("Content-Type", "application/json; charset=UTF-8"); h.send_header("Content-Length", str(len(b))); h.end_headers()
            return h.wfile.write(b)
        table = q.get("uri", "").replace("dl:", "")
        if q.get("command") != "DataQuery" or table not in self.tables:
            return h.send_error(404)
        with self.lock:
            recs, mode = list(self.tables[table]), q.get("mode")
        more = False
        if mode == "most-recent":
            sel = recs[-int(q.get("p1", 1)):]
        elif mode == "since-record":
            p1, p3 = int(q.get("p1", 0)), 500   # o servidor real decide o tamanho do bloco e avisa com "more"
            sel = [r for r in recs if r[0] >= p1][:p3 + 1]
            more, sel = len(sel) > p3, sel[:p3]
        else:
            return h.send_error(400)
        body = {"head": {"transaction": 0, "signature": 1, "environment": {"table_name": table, "model": "CR1000X"},
                         "fields": [{"name": n, "type": t, "process": "Smp"} for n, t in FIELDS[table]]},
                "data": [{"time": t, "no": no, "vals": v} for no, t, v in sel], "more": more}
        b = json.dumps(body).encode()
        h.send_response(200); h.send_header("Content-Type", "application/json; charset=UTF-8"); h.send_header("Content-Length", str(len(b))); h.end_headers()
        h.wfile.write(b)
