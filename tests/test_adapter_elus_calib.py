"""Perfil elus_calib: a tabela de basculadas e de EVENTOS (so tem registro quando ha basculada).
Ela nao pode segurar a entrega das medicoes, que chegam todo segundo."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import fake_cr1000x as F
from datalogger import CR1000X

SRV = F.start(prefill=90, oor_every=0)       # 90 s de historico (1 basculada a cada ~60 s), dados ficticios


def adapter(tmp_path, name):
    return CR1000X(address=f"127.0.0.1:{SRV.server_address[1]}", user="dash", password="segredo",
                   cursor_file=str(tmp_path / name), profile="elus_calib")


def test_tabela_de_eventos_esparsa_nao_trava_as_medicoes(tmp_path):
    rs = adapter(tmp_path, "a.json").read()
    events = [e for r in rs for e in r.tips]
    assert len(rs) >= 85                                  # todas as medicoes de 1 Hz chegam
    assert len(events) >= 1 and len({k for _, k in events}) == len(events)


def test_sem_nenhuma_basculada_ainda_as_medicoes_continuam_chegando(tmp_path):
    F.TABLES["Basculadas"].clear()                        # nenhum evento registrado ate agora
    rs = adapter(tmp_path, "b.json").read()
    assert len(rs) >= 85 and not [e for r in rs for e in r.tips]
