"""Adaptador CR1000X lendo a tabela Vazao1s dos programas v3 (em uso) e v4 (pulsos), e o cursor por registro-âncora.
Emulador com dados fictícios: só a lógica é testada."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from datalogger import CR1000X, _ts_ms
from tests.fake_programa_atual import Fake


@pytest.fixture
def v4():
    f = Fake(prefill=30, tip_every=20, schema="v4")
    yield f
    f.stop()


@pytest.fixture
def v3():
    f = Fake(prefill=30, tip_every=20, schema="v3")
    yield f
    f.stop()


def adapter(fake, tmp_path, name="c.json", profile="programa_vazao"):
    return CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo", cursor_file=str(tmp_path / name), profile=profile)


# ---------------- programa v3 em uso: só o canal analógico existe
def test_v3_traz_corrente_bruta_e_declara_so_o_canal_analogico(v3, tmp_path):
    r = adapter(v3, tmp_path).read()[-1]
    assert r.cor_ma == pytest.approx(12.0) and r.cor_status == "ok"
    assert r.flow_channels == {"analog": True, "pulse": False}
    assert r.flow_pulses is None and r.flow_pulses_total is None and r.pulse_status is None


def test_v3_corrente_fora_da_faixa_chega_bruta_ao_servidor(v3, tmp_path):
    a = adapter(v3, tmp_path); a.read(); a.ack()
    v3.flow_ma = 3.2                     # Flow_Status = 1 no datalogger; quem classifica (tolerância, falha) é o servidor
    v3.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_ma == pytest.approx(3.2) and r.cor_status == "ok"


def test_v3_corrente_nan_e_leitura_invalida_nao_zero(v3, tmp_path):
    a = adapter(v3, tmp_path); a.read(); a.ack()
    v3.flow_ma = "NAN"
    v3.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_ma is None and r.cor_status == "invalid"


# ---------------- programa v4: os dois canais chegam em todo Scan
def test_v4_traz_pulsos_brutos_acumulado_e_corrente(v4, tmp_path):
    rs = adapter(v4, tmp_path).read()
    r = rs[-1]
    assert r.flow_channels == {"analog": True, "pulse": True}
    assert r.flow_pulses == 100 and r.pulse_status == "ok" and r.flow_hz == pytest.approx(100.0)   # Scan de 1 s
    assert r.flow_pulses_total == v4.pulses_total and rs[-2].flow_pulses_total == v4.pulses_total - 100
    assert r.cor_ma == pytest.approx(12.0) and r.cor_status == "ok"


def test_v4_zero_pulsos_e_leitura_valida(v4, tmp_path):
    a = adapter(v4, tmp_path); a.read(); a.ack()
    v4.pulses_per_s = 0
    v4.tick(sleep=False)
    r = a.read()[-1]
    assert r.pulse_status == "ok" and r.flow_pulses == 0 and r.flow_hz == 0.0


@pytest.mark.parametrize("code", [1, 2, 3, 4])
def test_v4_pstatus_diferente_de_zero_invalida_so_o_canal_de_pulsos(v4, tmp_path, code):
    a = adapter(v4, tmp_path); a.read(); a.ack()
    v4.pstatus = code
    v4.tick(sleep=False)
    r = a.read()[-1]
    assert r.pulse_status == "invalid" and r.flow_pulses is None and r.flow_hz is None
    assert r.cor_status == "ok" and r.cor_ma == pytest.approx(12.0)      # canais independentes


def test_programa_sem_vazao_nao_declara_canal_nenhum(v4, tmp_path):
    r = adapter(v4, tmp_path, profile="programa_atual").read()[-1]
    assert r.flow_channels == {"analog": False, "pulse": False} and r.cor_status is None and r.pulse_status is None


# ---------------- cursor por registro-âncora (o defeito de produção: pedir registro inexistente → API devolve do mais antigo)
def test_sem_registro_novo_nao_rele_o_historico_nem_declara_reinicio(v4, tmp_path):
    a = adapter(v4, tmp_path)
    assert len(a.read()) >= 25; a.ack()
    for _ in range(3):                      # o emulador responderia "do mais antigo" a um pedido de registro inexistente
        assert a.read() == []
        a.ack()
    assert a.restarts == 0 and a.gaps == 0 and all(a.join_miss.get(t, 0) == 0 for t in a.join_miss)
    v4.tick(sleep=False)
    new = a.read()
    assert len(new) == 1 and a.restarts == 0


def test_cursor_guardado_e_o_ultimo_registro_recebido_com_horario(v4, tmp_path):
    a = adapter(v4, tmp_path); rs = a.read(); a.ack()
    cur = json.load(open(tmp_path / "c.json"))
    anc = cur["Balanca1s"]
    assert anc["no"] == v4.tables["Balanca1s"][-1][0] and _ts_ms(anc["time"]) == rs[-1].ts


def test_cursor_antigo_proximo_registro_e_migrado_sem_reler(v4, tmp_path):
    nxt = v4.tables["Balanca1s"][-1][0] - 4              # formato antigo: "próximo registro a pedir"
    json.dump({t: v4.tables[t][-1][0] - 4 for t in ("Balanca1s", "Termopar1s", "Pluviometro1s", "Vazao1s")}, open(tmp_path / "c.json", "w"))
    rs = adapter(v4, tmp_path).read()
    assert len(rs) == 5 and rs[0].ts == _ts_ms(v4.tables["Balanca1s"][nxt][1])


def test_reinicio_real_do_programa_e_detectado_sem_duplicar(v4, tmp_path):
    a = adapter(v4, tmp_path); a.read(); a.ack()
    v4.restart_program()
    for _ in range(5):
        v4.tick(sleep=False)
    rs = a.read(); a.ack()
    assert len(rs) == 5 and a.restarts >= 1 and len({r.ts for r in rs}) == 5
    assert rs[-1].flow_pulses_total == 500                  # acumulado voltou a zero com o programa


def test_registros_perdidos_no_anel_sao_contados_como_lacuna(v4, tmp_path):
    a = adapter(v4, tmp_path); a.read(); a.ack()
    for _ in range(10):
        v4.tick(sleep=False)
    for t in v4.tables:                                      # os 35 mais antigos saíram do anel, inclusive a âncora
        v4.drop_oldest(t, 35)
    rs = a.read()
    assert a.gaps >= 1 and a.restarts == 0 and len(rs) >= 1


def _shift_table(fake, table, ms):
    from datetime import datetime, timedelta

    def sh(t):
        return (datetime.strptime(t[:21], "%Y-%m-%dT%H:%M:%S.%f") + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4]
    fake.tables[table] = [(no, sh(t), v) for no, t, v in fake.tables[table]]


def test_juncao_tolera_diferenca_de_ms_entre_tabelas(v4, tmp_path):
    _shift_table(v4, "Termopar1s", 300)
    a = adapter(v4, tmp_path)
    r = a.read()
    assert len(r) >= 25 and all(x.temp_status == "ok" and x.temp_c is not None for x in r)
    assert not a.join_miss


def test_juncao_alem_da_tolerancia_continua_sendo_sem_comunicacao_e_conta(v4, tmp_path):
    _shift_table(v4, "Termopar1s", 2000)
    a = adapter(v4, tmp_path)
    r = a.read()
    assert any(x.temp_status == "no_comm" for x in r) and a.join_miss.get("Termopar1s", 0) > 0
