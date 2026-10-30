"""Diagnostico da PRIMEIRA conexao com o datalogger (so le; nao altera nada no datalogger).

Uso (na pasta do projeto):
    set DATALOGGER_PASSWORD=sua_senha            (Windows)   |   export DATALOGGER_PASSWORD=sua_senha   (Linux/Mac)
    python tools/probe_cr1000x.py --host 192.168.1.50 --user dash [--https] [--profile programa_atual]

Verifica, em ordem: se o endereco responde, se usuario/senha servem e qual o nivel de acesso, se o relogio do datalogger
bate com o do PC, quais tabelas existem e se as tabelas/campos que o perfil espera estao no programa que esta rodando.
"""
import argparse, base64, getpass, json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datalogger import load_profile


def _needed(profile):
    """{tabela: [campos que o perfil le]}"""
    need = {}
    for key, fields in (("mass", ("value", "status")), ("temp", ("value",)), ("tips", ("count",)), ("cor", ("ma", "status"))):
        spec = profile.get(key)
        if spec:
            need.setdefault(spec["table"], [])
            need[spec["table"]] += [spec[f] for f in fields if f in spec]
    return need


def run_probe(host, user="", password="", profile="programa_atual", https=False, timeout=5, ca=None, verify=True):
    res = []
    add = lambda lvl, msg: res.append((lvl, msg))
    base = f"{'https' if https else 'http'}://{host}"
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    ctx = None
    if https:
        ctx = ssl.create_default_context(cafile=ca)
        if not verify:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE

    def get(**q):
        url = base + "/?" + urllib.parse.urlencode(q, safe=":")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": auth}), timeout=timeout, context=ctx) as r:
            return json.load(r)

    try:
        prof = load_profile(profile)
    except ValueError as e:
        add("ERRO", str(e))
        return 1, res
    # 1) alcance + autenticacao
    try:
        level = get(command="CheckAuthorization", format="json").get("authorization")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            add("ERRO", "HTTP 401: usuario ou senha incorretos, ou a conta nao tem acesso. Confira em Device Configuration Utility > Network Services > Edit Accounts.")
        else:
            add("ERRO", f"HTTP {e.code} em {base}. Se for 404, o datalogger pode estar sem contas de usuario com os 3 niveis de codigo numerico definidos (crie uma conta).")
        return 1, res
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        add("ERRO", f"Nao consegui alcancar {host} ({getattr(e, 'reason', e)}). Confira IP, cabo de rede, mesma sub-rede/gateway, porta ({'443' if https else '80'}) e firewall do PC.")
        return 1, res
    add("OK", f"{host} respondeu e a conta '{user}' foi aceita.")
    if level in (3, 4):
        add("OK", "Acesso somente leitura: e o adequado para o dashboard.")
    else:
        add("AVISO", f"A conta tem nivel de acesso {level} (escrita/total). Para o dashboard crie e use uma conta SOMENTE LEITURA.")
    # 2) relogio
    try:
        clk = get(command="ClockCheck", format="json")
        dl_time = datetime.strptime(clk["time"][:19], "%Y-%m-%dT%H:%M:%S")
        diff = (dl_time - datetime.now()).total_seconds()
        if abs(diff) > 5:
            add("AVISO", f"O relogio do datalogger difere {diff:+.0f} s do relogio do PC. Os horarios gravados virao deslocados; ajuste o relogio (e confira o fuso: os dois devem estar na mesma hora local).")
        else:
            add("OK", f"Relogio do datalogger confere com o do PC (diferenca {diff:+.1f} s).")
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        add("AVISO", f"Nao consegui ler o relogio do datalogger ({e}).")
        dl_time = None
    # 3) tabelas
    try:
        tables = [s["name"] for s in get(command="BrowseSymbols", format="json")["symbols"]]
        add("INFO", "Tabelas no programa em execucao: " + ", ".join(tables))
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        tables = None
        add("AVISO", f"Nao consegui listar as tabelas ({e}).")
    # 4) tabelas/campos que o perfil espera
    for table, fields in _needed(prof).items():
        if tables is not None and table not in tables:
            add("ERRO", f"A tabela '{table}' (esperada pelo perfil '{prof['nome']}') nao existe no programa em execucao. Confira o nome da DataTable no CRBasic ou escolha outro perfil.")
            continue
        try:
            d = get(command="DataQuery", uri=f"dl:{table}", mode="most-recent", p1=1, format="json")
        except (urllib.error.URLError, OSError, ValueError) as e:
            add("ERRO", f"Nao consegui ler a tabela '{table}': {e}")
            continue
        names = [f["name"] for f in d["head"]["fields"]]
        missing = [f for f in fields if f not in names]
        if missing:
            add("ERRO", f"Tabela '{table}': o campo '{', '.join(missing)}' nao existe. Campos disponiveis: {', '.join(names)}.")
            continue
        if not d["data"]:
            add("AVISO", f"Tabela '{table}' existe, mas ainda nao tem registros.")
            continue
        rec = d["data"][0]
        vals = dict(zip(names, rec["vals"]))
        add("INFO", f"{table}: registro {rec['no']} de {rec['time']} -> " + ", ".join(f"{f}={vals[f]!r}" for f in fields))
        if dl_time is not None:
            age = (dl_time - datetime.strptime(rec["time"][:19], "%Y-%m-%dT%H:%M:%S")).total_seconds()
            if age > 10:
                add("AVISO", f"O ultimo registro de '{table}' tem {age:.0f} s. O programa esta rodando? A tabela esta sendo gravada?")
    code = 1 if any(l == "ERRO" for l, _ in res) else 0
    add("OK" if code == 0 else "ERRO", "Diagnostico concluido sem erros." if code == 0 else "Diagnostico concluido COM erros: corrija os itens marcados ERRO.")
    return code, res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="IP ou nome do datalogger (pode incluir :porta)")
    ap.add_argument("--user", default="")
    ap.add_argument("--profile", default=os.environ.get("CR1000X_PROFILE", "programa_atual"))
    ap.add_argument("--https", action="store_true")
    ap.add_argument("--insecure", action="store_true", help="com --https: nao validar o certificado (so para teste)")
    a = ap.parse_args()
    pw = os.environ.get("DATALOGGER_PASSWORD") or getpass.getpass("Senha do datalogger: ")
    code, res = run_probe(a.host, a.user, pw, a.profile, a.https, ca=os.environ.get("DATALOGGER_CA"), verify=not a.insecure)
    for lvl, msg in res:
        print(f"[{lvl:5s}] {msg}")
    sys.exit(code)


if __name__ == "__main__":
    main()
