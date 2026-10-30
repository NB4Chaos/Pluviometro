"""Adaptador lendo a tabela Vazao1s do programa novo (emulador com dados fictícios, só para testar a lógica)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from datalogger import CR1000X
from tests.fake_programa_atual import Fake


@pytest.fixture
def fake():
    f = Fake(prefill=30, tip_every=20)
    yield f
    f.stop()


def adapter(fake, tmp_path, name="c.json"):
    return CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo", cursor_file=str(tmp_path / name), profile="programa_vazao")


def test_modo_pulsos_traz_pulsos_brutos_e_frequencia_sem_ma(fake, tmp_path):
    r = adapter(fake, tmp_path).read()[-1]
    assert r.flow_mode == "pulse" and r.cor_status == "ok"
    assert r.flow_pulses == 100.0 and r.flow_hz == 100.0 and r.cor_ma is None


def test_modo_analogico_traz_ma_e_nao_traz_pulsos(fake, tmp_path):
    fake.flow_mode, fake.flow_ma = 2, 7.5
    a = adapter(fake, tmp_path); a.read(); a.ack()
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.flow_mode == "analog" and r.cor_ma == pytest.approx(7.5) and r.flow_pulses is None and r.flow_hz is None


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5])
def test_status_diferente_de_zero_nao_vira_medicao(fake, tmp_path, code):
    a = adapter(fake, tmp_path); a.read(); a.ack()
    fake.flow_status = code
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_status == "invalid" and r.cor_ma is None and r.flow_pulses is None and r.flow_hz is None


def test_zero_pulsos_e_leitura_valida_nao_ausencia(fake, tmp_path):
    a = adapter(fake, tmp_path); a.read(); a.ack()
    fake.flow_hz = 0.0
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.cor_status == "ok" and r.flow_pulses == 0.0 and r.flow_hz == 0.0


def test_programa_atual_sem_tabela_de_vazao_fica_sem_modo(fake, tmp_path):
    a = CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo", cursor_file=str(tmp_path / "x.json"), profile="programa_atual")
    r = a.read()[-1]
    assert r.flow_mode is None and r.cor_status is None


def _shift_table(fake, table, ms):
    from datetime import datetime, timedelta
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
