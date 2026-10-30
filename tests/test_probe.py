"""Ferramenta de diagnostico da primeira conexao com o datalogger (emulador, dados ficticios)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from tests.fake_programa_atual import Fake
from tools.probe_cr1000x import run_probe


@pytest.fixture
def fake():
    f = Fake(prefill=30)
    yield f
    f.stop()


def probe(fake, **kw):
    return run_probe(f"127.0.0.1:{fake.port}", user="dash", password=kw.pop("password", "segredo"), profile=kw.pop("profile", "programa_atual"), **kw)


def texts(res):
    return " | ".join(m for _, m in res)


def test_datalogger_certo_passa_sem_erros_e_mostra_os_ultimos_valores(fake):
    code, res = probe(fake)
    assert code == 0 and not [m for lvl, m in res if lvl == "ERRO"]
    assert "Balanca1s" in texts(res) and "Peso_g" in texts(res) and "somente leitura" in texts(res).lower()


def test_senha_errada_e_explicada(fake):
    code, res = probe(fake, password="errada")
    assert code != 0 and "401" in texts(res) and "senha" in texts(res).lower()


def test_campo_do_perfil_que_nao_existe_no_programa_e_apontado(fake, tmp_path):
    import json
    prof = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles", "programa_atual.json")))
    prof["mass"]["value"] = "Peso_inexistente"
    path = tmp_path / "ruim.json"; path.write_text(json.dumps(prof))
    code, res = probe(fake, profile=str(path))
    assert code != 0 and "Peso_inexistente" in texts(res) and "Balanca1s" in texts(res)


def test_campo_do_medidor_com_grafia_errada_e_apontado(fake, tmp_path):
    """O perfil já esperou Flow_Mode quando o programa grava Flow_mode: o diagnóstico precisa acusar isso (antes ignorava o bloco flow)."""
    import json
    prof = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles", "programa_vazao.json")))
    prof["flow"]["optional"] = [k for k in prof["flow"]["optional"] if k != "mode"]
    prof["flow"]["mode"] = "Flow_Mode"
    path = tmp_path / "grafia.json"; path.write_text(json.dumps(prof))
    code, res = probe(fake, profile=str(path))
    assert code != 0 and "Flow_Mode" in texts(res) and "outra grafia" in texts(res) and "Flow_mode" in texts(res)


def test_programa_v3_sem_pulsos_passa_e_informa_os_campos_opcionais(tmp_path):
    f = Fake(prefill=5, schema="v3")
    try:
        code, res = probe(f, profile="programa_vazao")
        assert code == 0 and "Flow_Pulsos" in texts(res) and "programa v4" in texts(res)
    finally:
        f.stop()


def test_conta_com_acesso_total_gera_aviso(fake):
    fake.level = 1
    code, res = probe(fake)
    assert code == 0 and any(lvl == "AVISO" and "somente leitura" in m.lower() for lvl, m in res)


def test_relogio_do_datalogger_muito_diferente_gera_aviso(fake):
    fake.clock_offset = 90.0
    code, res = probe(fake)
    assert any(lvl == "AVISO" and "relogio" in m.lower() for lvl, m in res)


def test_servidor_inalcancavel_e_explicado(fake):
    fake.stop()
    code, res = run_probe(f"127.0.0.1:{fake.port}", user="dash", password="segredo", profile="programa_atual", timeout=1)
    assert code != 0 and "alcan" in texts(res).lower()
