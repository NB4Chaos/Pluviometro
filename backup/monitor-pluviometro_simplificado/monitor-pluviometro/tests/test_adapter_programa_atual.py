"""Adaptador do CR1000X lendo as tabelas do PROGRAMA ATUAL do usuário (emulador, dados fictícios)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from datalogger import CR1000X
from tests.fake_programa_atual import Fake


@pytest.fixture
def fake():
    f = Fake(prefill=120, tip_every=20)
    yield f
    f.stop()


def adapter(fake, tmp_path, name="cursor.json"):
    return CR1000X(address=f"127.0.0.1:{fake.port}", user="dash", password="segredo",
                   cursor_file=str(tmp_path / name), profile="programa_atual")


def test_le_balanca_temperatura_e_pluviometro_das_tabelas_do_usuario(fake, tmp_path):
    readings = adapter(fake, tmp_path).read()
    last = readings[-1]
    assert len(readings) >= 100                       # backlog do datalogger recuperado
    assert last.mass_g == pytest.approx(round(fake.mass, 1), abs=0.11)
    assert last.mass_status == "ok"
    assert 21.0 < last.temp_c < 22.5 and last.temp_status == "ok"


def test_status_da_balanca_vira_estado_do_dashboard(fake, tmp_path):
    a = adapter(fake, tmp_path); a.read(); a.ack()
    fake.force = [{"status": 1}, {"status": 3}, {"status": 4}, {"status": 2}]
    for _ in range(4):
        fake.tick(sleep=False)
    got = [(r.mass_g, r.mass_status) for r in a.read()]
    assert got == [(None, "no_comm"), (None, "invalid"), (None, "invalid"), (None, "invalid")]


def test_temperatura_nan_vira_leitura_invalida(fake, tmp_path):
    a = adapter(fake, tmp_path); a.read(); a.ack()
    fake.force = [{"temp": "NAN"}]
    fake.tick(sleep=False)
    r = a.read()[-1]
    assert r.temp_c is None and r.temp_status == "invalid"


def test_cada_basculada_vira_um_evento_com_chave_unica(fake, tmp_path):
    readings = adapter(fake, tmp_path).read()
    events = [e for r in readings for e in r.tips]
    assert len(events) == fake.tips and fake.tips > 0
    assert len({key for _, key in events}) == len(events)


def test_reinicio_do_programa_do_datalogger_nao_perde_nem_inventa_basculadas(fake, tmp_path):
    a = adapter(fake, tmp_path)
    a.read(); a.ack()
    fake.reset_total()                                # Pluvio_Total volta a 0; as basculadas por segundo continuam
    before = fake.tips
    for _ in range(45):
        fake.tick(sleep=False)
    events = [e for r in a.read() for e in r.tips]
    assert len(events) == fake.tips - before and fake.tips - before >= 2


def test_cursor_nao_repete_registros_nem_depois_de_reiniciar_o_adaptador(fake, tmp_path):
    a = adapter(fake, tmp_path)
    first = a.read(); a.ack()
    assert a.read() == [] or len(a.read()) == 0       # nada novo
    for _ in range(5):
        fake.tick(sleep=False)
    new = adapter(fake, tmp_path).read()              # novo objeto = servidor reiniciado, cursor veio do disco
    assert len(new) == 5 and new[0].ts > first[-1].ts


def test_medidor_de_vazao_ausente_nao_inventa_vazao(fake, tmp_path):
    r = adapter(fake, tmp_path).read()[-1]
    assert r.cor_ma is None and r.cor_status is None  # sem variável no programa: aguardando integração, não falha


def test_nao_emite_linha_incompleta_quando_as_tabelas_chegam_em_momentos_diferentes(tmp_path):
    """O datalogger grava Balanca1s, depois Termopar1s, depois Pluviometro1s. Uma leitura no meio disso
    nao pode virar uma linha com temperatura 'sem comunicacao' que na verdade so atrasou."""
    import time
    f = Fake(prefill=5, lag=0.05, tip_every=7)
    f.run(period=0.15)
    a = adapter(f, tmp_path)
    got, t_end = [], time.time() + 4
    while time.time() < t_end:
        got += a.read()
        a.ack()
        time.sleep(0.01)
    f.running = False
    time.sleep(0.5)
    got += a.read()
    a.ack()
    f.server.shutdown()
    assert len(got) >= 10
    assert all(r.temp_status == "ok" and r.mass_status == "ok" for r in got)
    assert len({r.ts for r in got}) == len(got) == f.i
    events = [e for r in got for e in r.tips]
    assert len(events) == f.tips and len({k for _, k in events}) == len(events)


def test_cursor_bloqueado_nao_derruba_a_aquisicao(tmp_path, monkeypatch):
    """Windows: outro programa segura o cursor por instantes. ack() tenta de novo e, se nao der, segue em memoria sem excecao."""
    import datalogger as dlm
    d = dlm.CR1000X(address="127.0.0.1:1", user="u", password="p", cursor_file=str(tmp_path / "c.json"))
    d.pending = {"Balanca1s": 10}
    calls = {"n": 0}
    real = dlm.os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("Acesso negado")
        real(src, dst)
    monkeypatch.setattr(dlm.os, "replace", flaky)
    monkeypatch.setattr(dlm.time, "sleep", lambda s: None)
    d.ack()                                                  # 2 falhas, depois grava
    assert calls["n"] == 3 and (tmp_path / "c.json").exists() and d.next == {"Balanca1s": 10}
    d.pending = {"Balanca1s": 11}
    monkeypatch.setattr(dlm.os, "replace", lambda s, t: (_ for _ in ()).throw(PermissionError("sempre")))
    d.ack()                                                  # nunca grava: nao levanta excecao e o cursor fica em memoria
    assert d.next == {"Balanca1s": 11}
