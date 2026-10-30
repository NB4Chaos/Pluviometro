"""Bloco de temporização do ensaio: carimbos do datalogger, tempo configurado × efetivamente medido, resolução efetiva e relógio do PC.
Nada aqui declara o temporizador calibrado: só registra o que é necessário para comparar com uma referência externa."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from tests.test_trials_pulsos import Env, T0


def test_ensaio_completo_registra_carimbos_cfg_efetivo_e_resolucao():
    e = Env()
    r = e.run(pulses=100)                      # 60 s configurados, Scan de 1 s, amostras a cada segundo
    t = r["result"]["timing"]
    assert t["start_ts"] == T0 + 4 * 1000 + 1 and t["end_ts"] == t["start_ts"] + 60000   # início = 1 ms após a última amostra vista
    assert t["cfg_ms"] == 60000 and t["window_ms"] == 60000 and t["resolution_ms"] == 1000
    assert t["first_sample_ts"] == T0 + 5000 and t["last_sample_ts"] == T0 + 64000
    assert t["eff_ms"] == 60000 and t["diff_ms"] == 0 and t["samples"] == 60
    assert t["wall_ms"] is not None and t["wall_ms"] >= 0      # relógio do PC: informativo, nunca usado no cálculo


def test_duracao_nao_multipla_do_scan_mostra_a_quantizacao_sem_arredondar_a_configuracao():
    e = Env({"trial_duration_ms": 1500})
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    e.feed(5, 10)
    tm = e.tr.get(t["id"])["result"]["timing"]
    assert tm["cfg_ms"] == 1500 and tm["window_ms"] == 1500           # o configurado é preservado em ms
    assert tm["eff_ms"] in (1000, 2000) and tm["diff_ms"] == tm["eff_ms"] - 1500 and tm["resolution_ms"] == 1000


def test_lacuna_no_fim_reduz_o_tempo_efetivo_e_aparece_na_diferenca():
    e = Env()
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    e.feed(5, 50)                                                     # 45 registros; depois o datalogger fica mudo
    e.feed(70, 72)                                                    # volta só depois do fim previsto: encerra pelo carimbo
    tm = e.tr.get(t["id"])["result"]["timing"]
    assert tm["samples"] == 45 and tm["eff_ms"] == 45000 and tm["diff_ms"] == -15000 and tm["window_ms"] == 60000


def test_sem_amostras_nao_inventa_tempo_efetivo():
    e = Env()
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    e.tr.stop()
    tm = e.tr.get(t["id"])["result"]["timing"]
    assert tm["samples"] == 0 and tm["eff_ms"] is None and tm["diff_ms"] is None and tm["first_sample_ts"] is None
