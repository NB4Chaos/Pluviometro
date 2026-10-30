"""Adaptador lendo a tabela Vazao1s dos programas reais (emulador com dados FICTÍCIOS, só para testar a lógica).
v3 = programa em uso (só 4–20 mA); v4 = programa novo (4–20 mA + pulsos em P2). O adaptador entrega o dado BRUTO;
classificar faixa, alarme e validade é do servidor (calc.flow_reading)."""
import os, sys
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from datalogger import CR1000X, load_profile
from tests.fake_programa_atual import Fake, VAZAO_V3, VAZAO_V4


@pytest.fixture
def fake():
    f = Fake(prefill=30, tip_every=20, schema="v4")
    yield f
    f.stop()


@pytest.fixture
def fake_v3():
    f = Fake(prefill=30, tip_every=20, schema="v3")
    yield f
    f.stop()


def adapter(fake, tmp_path, name="c.json"):
    return CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo", cursor_file=str(tmp_path / name), profile="programa_vazao")


def fresh(fake, tmp_path):
    a = adapter(fake, tmp_path); a.read(); a.ack()
    return a


# ---------------------------------------------------------------- campos e nomes (o erro Flow_Mode × Flow_mode não volta)
def test_campos_obrigatorios_do_perfil_existem_no_programa_em_uso_com_a_grafia_exata():
    fl = load_profile("programa_vazao")["flow"]
    v3 = {n for n, _ in VAZAO_V3}
    required = {fl[k] for k in ("ma", "status") if k not in fl.get("optional", [])}
    assert required <= v3, required - v3
    assert fl["mode"] == "Flow_mode" and "Flow_Mode" not in v3   # grafia real do campo: 'm' minúsculo
    assert {fl["pulses"], fl["pulses_total"], fl["pulse_status"]} <= {n for n, _ in VAZAO_V4}


def test_programa_v4_traz_os_dois_canais_brutos(fake, tmp_path):
    a = fresh(fake, tmp_path)
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.flow_has == ("analog", "pulse") and a.flow_has == ("analog", "pulse")
    assert r.cor_status == "ok" and r.cor_ma == pytest.approx(12.0) and r.flow_ma_code == 0
    assert r.flow_pulses == 100.0 and r.flow_pulse_code == 0 and r.flow_pulses_total == fake.ptotal
    assert r.flow_dt_ms == 1000 and r.flow_hz is None      # frequência é calculada no servidor, com a janela real


def test_programa_v3_em_uso_so_tem_o_canal_analogico(fake_v3, tmp_path):
    r = adapter(fake_v3, tmp_path).read()[-1]
    assert r.flow_has == ("analog",) and r.cor_ma == pytest.approx(12.0)
    assert r.flow_pulses is None and r.flow_pulses_total is None and r.flow_pulse_code is None


@pytest.mark.parametrize("ma, code", [(3.2, 1), (0.02, 1), (20.6, 2), (3.99, 1)])
def test_corrente_fora_da_faixa_chega_bruta_e_com_o_codigo(fake, tmp_path, ma, code):
    a = fresh(fake, tmp_path)
    fake.flow_ma = ma
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_status == "ok" and r.cor_ma == pytest.approx(ma) and r.flow_ma_code == code   # antes: mA descartado, vira "inválida"


def test_corrente_nan_nao_vira_numero(fake, tmp_path):
    a = fresh(fake, tmp_path)
    fake.flow_ma = "NAN"
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_ma is None and r.flow_ma_code == 3


def test_primeiro_scan_do_programa_marca_a_contagem(tmp_path):
    f = Fake(prefill=3, schema="v4")
    try:
        rs = adapter(f, tmp_path).read()
        assert rs[0].flow_pulse_code == 1 and all(r.flow_pulse_code == 0 for r in rs[1:])
    finally:
        f.stop()


def test_zero_pulsos_e_leitura_valida_nao_ausencia(fake, tmp_path):
    a = fresh(fake, tmp_path)
    fake.flow_hz = 0.0
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_status == "ok" and r.flow_pulses == 0.0 and r.flow_pulse_code == 0


def test_scan_pulado_aumenta_a_janela_de_contagem(fake, tmp_path):
    a = fresh(fake, tmp_path)
    fake.t += timedelta(seconds=1)                 # um Scan pulado: o registro seguinte cobre 2 s
    fake.tick(sleep=False)
    assert a.read()[-1].flow_dt_ms == 2000


def test_programa_atual_sem_tabela_de_vazao_fica_sem_modo(fake, tmp_path):
    a = CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo", cursor_file=str(tmp_path / "x.json"), profile="programa_atual")
    r = a.read()[-1]
    assert r.flow_mode is None and r.cor_status is None and r.flow_has == ()


# ---------------------------------------------------------------- registro âncora: o defeito do histórico regravado
def test_consulta_antes_da_gravacao_nao_vira_reinicio_falso(fake, tmp_path):
    """A API real responde a partir do registro MAIS ANTIGO quando se pede um registro ainda não gravado. Antes isso era lido
    como 'tabela reiniciada': relia a tabela inteira e regravava horas de histórico com temperatura e vazão vazias."""
    a = fresh(fake, tmp_path)
    for _ in range(3):
        assert a.read() == []                      # nada novo: só a âncora volta e é descartada
        a.ack()
    assert a.restarts == 0 and a.gaps == 0 and not a.join_miss
    fake.tick(sleep=False)
    got = a.read()
    assert len(got) == 1 and got[0].temp_status == "ok" and got[0].cor_status == "ok"


def test_reinicio_real_do_programa_e_detectado_e_so_entrega_dados_novos(fake, tmp_path):
    a = fresh(fake, tmp_path)
    last = a.seen["Balanca1s"]
    fake.restart_program()
    for _ in range(5):
        fake.tick(sleep=False)
    got = a.read()
    assert a.restarts >= 1 and len(got) == 5 and all(r.ts > last for r in got)
    assert all(r.temp_status == "ok" and r.cor_status == "ok" for r in got)
    assert got[0].flow_pulse_code == 1 and got[0].flow_dt_ms is None   # contador zerado: 1o Scan e janela desconhecida


def test_tabela_recriada_que_ja_passou_do_numero_antigo_e_relida_desde_o_inicio(fake, tmp_path):
    a = fresh(fake, tmp_path)
    n = fake.next_no["Balanca1s"]
    fake.restart_program()
    for _ in range(n + 5):                         # a tabela nova já tem mais registros que o cursor antigo
        fake.tick(sleep=False)
    got = a.read()
    assert a.restarts >= 1 and len(got) == n + 5


def test_ancora_sobrescrita_na_memoria_circular_vira_lacuna(tmp_path):
    f = Fake(prefill=20, ring=30, schema="v4")
    try:
        a = adapter(f, tmp_path); a.read(); a.ack()
        for _ in range(60):                        # 60 registros novos numa memória de 30: a âncora some
            f.tick(sleep=False)
        got = a.read()
        assert a.gaps >= 1 and a.restarts == 0 and len(got) == 30
    finally:
        f.stop()


def test_cursor_guarda_o_horario_da_ancora(fake, tmp_path):
    import json
    a = fresh(fake, tmp_path)
    saved = json.load(open(tmp_path / "c.json", encoding="utf-8"))
    assert saved["Balanca1s"] == fake.next_no["Balanca1s"] and saved["_anchor_time"]["Balanca1s"] == fake.tables["Balanca1s"][-1][1]
    b = adapter(fake, tmp_path)                    # servidor reiniciado: continua do cursor, sem reler
    fake.tick(sleep=False)
    assert len(b.read()) == 1 and b.restarts == 0


# ---------------------------------------------------------------- junção entre tabelas
def _shift_table(fake, table, ms):
    from datetime import datetime
    def sh(t):
        return (datetime.strptime(t[:21], "%Y-%m-%dT%H:%M:%S.%f") + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4]
    fake.tables[table] = [(no, sh(t), v) for no, t, v in fake.tables[table]]


def test_juncao_tolera_diferenca_de_ms_entre_tabelas(fake, tmp_path):
    # horário do termopar deslocado 300 ms em relação ao da balança: antes virava "sem comunicação" em TODAS as linhas
    _shift_table(fake, "Termopar1s", 300)
    a = adapter(fake, tmp_path)
    r = a.read()
    assert len(r) >= 25 and all(x.temp_status == "ok" and x.temp_c is not None for x in r)
    assert not a.join_miss


def test_juncao_alem_da_tolerancia_continua_sendo_sem_comunicacao_e_conta(fake, tmp_path):
    _shift_table(fake, "Termopar1s", 2000)       # 2 s: fora da tolerância de 0,5 s
    a = adapter(fake, tmp_path)
    r = a.read()
    assert any(x.temp_status == "no_comm" for x in r) and a.join_miss.get("Termopar1s", 0) > 0


# ---------------------------------------------------------------- leitura das tabelas em paralelo (DATALOGGER_PARALLEL=1, desligada por padrão)
def test_leitura_paralela_entrega_o_mesmo_que_a_sequencial(fake, tmp_path, monkeypatch):
    seq = adapter(fake, tmp_path, "seq.json")
    monkeypatch.setenv("DATALOGGER_PARALLEL", "1")
    par = adapter(fake, tmp_path, "par.json")
    assert par.parallel and not seq.parallel
    for _ in range(3):   # leitura inicial e mais duas rodadas com registros novos
        a, b = seq.read(), par.read()
        assert a and a == b
        assert (seq.pending, seq.gaps, seq.restarts) == (par.pending, par.gaps, par.restarts)
        seq.ack(); par.ack()
        fake.tick(sleep=False)
