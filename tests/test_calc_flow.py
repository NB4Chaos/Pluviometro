"""Medidor de vazão: fator K com unidade, classificação do sinal 4–20 mA e contagem bruta de pulsos. Exemplos conferidos à mão."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import calc


# ---- fator K: sempre normalizado para pulsos por litro, sem presumir unidade
@pytest.mark.parametrize("v,u,exp", [(100, "pulsos/L", 100.0), (1000, "pulsos/m³", 1.0), (0.5, "L/pulso", 2.0), (10, "mL/pulso", 100.0),
                                     (2500, "pulsos/m³", 2.5)])
def test_fator_k_convertido_para_pulsos_por_litro(v, u, exp):
    assert calc.k_to_pulses_per_l(v, u) == pytest.approx(exp)


@pytest.mark.parametrize("v,u", [(0, "pulsos/L"), (-5, "pulsos/L"), (None, "pulsos/L"), (float("nan"), "pulsos/L"), (float("inf"), "L/pulso"),
                                 (100, "pulsos/galão"), (100, None)])
def test_fator_k_invalido_nao_vira_numero(v, u):
    assert calc.k_to_pulses_per_l(v, u) is None


# ---- 4–20 mA: tolerância nos limites sem extrapolar; abaixo de 3,6 mA é falha (NAMUR NE 43), não vazão
@pytest.mark.parametrize("ma,state,clamped", [(4.011, "ok", 4.011), (12.0, "ok", 12.0), (3.99, "ok", 4.0), (20.015, "ok", 20.0),
                                              (3.97, "under", 3.97), (3.6, "under", 3.6), (20.03, "over", 20.03), (3.5, "fail", 3.5), (0.0, "fail", 0.0)])
def test_classificacao_do_sinal_4_20(ma, state, clamped):
    assert calc.classify_ma(ma) == (state, pytest.approx(clamped))


def test_classificacao_sem_sinal_e_tolerancia_configuravel():
    assert calc.classify_ma(None) == ("none", None)
    assert calc.classify_ma(3.95, tol=0.1) == ("ok", 4.0)
    assert calc.classify_ma(3.95, tol=0.0) == ("under", 3.95)


def test_vazao_analogica_dentro_da_tolerancia_e_zero_nao_negativa():
    # faixa 0–100 L/min: 3,99 mA fica preso em 4 mA → 0 L/min (não −0,06)
    assert calc.flow_from_sample("analog", "ok", None, 3.99, None, 0.0, 100.0, "L/min") == pytest.approx(0.0)
    assert calc.flow_from_sample("analog", "ok", None, 3.5, None, 0.0, 100.0, "L/min") is None
    assert calc.flow_from_sample("analog", "ok", None, 20.03, None, 0.0, 100.0, "L/min") is None
    assert calc.flow_from_sample("analog", "ok", None, 12.0, None, 0.0, 100.0, "L/min") == pytest.approx(50.0)


# ---- pulsos brutos: exemplo do pedido (1 250 pulsos em 60 s, K = 100 pulsos/L → 12,5 L → 0,20833 L/s = 12,5 L/min)
def test_vazao_por_pulsos_exemplo_do_pedido():
    assert calc.pulse_volume_l(1250, 100.0) == pytest.approx(12.5)
    assert calc.pulse_flow_l_min(1250, 60.0, 100.0) == pytest.approx(12.5)
    assert calc.pulse_flow_l_min(1250, 60.0, 100.0) / 60 == pytest.approx(0.20833, abs=1e-5)


@pytest.mark.parametrize("n,dt,k", [(1250, 0, 100.0), (1250, -1, 100.0), (1250, 60, None), (1250, 60, 0), (None, 60, 100.0)])
def test_vazao_por_pulsos_sem_divisao_por_zero_nem_k_inventado(n, dt, k):
    assert calc.pulse_flow_l_min(n, dt, k) is None


def test_zero_pulsos_e_vazao_zero_valida():
    assert calc.pulse_flow_l_min(0, 60.0, 100.0) == 0.0 and calc.pulse_volume_l(0, 100.0) == 0.0


# ---- N do ensaio: diferença do contador acumulado quando ele é monotônico; soma por registro quando o contador reinicia
def test_contagem_do_ensaio_pela_diferenca_do_acumulado():
    r = calc.pulse_count_window([100, 100, 100], [1100, 1200, 1300])
    assert r["n_delta"] == 300 and r["n_sum"] == 300 and r["n"] == 300 and r["method"] == "acumulado" and not r["reset"]


def test_lacuna_de_registros_nao_perde_pulsos_pelo_acumulado():
    # faltou o registro do meio (1200): a soma dá 200, o acumulado dá os 300 que realmente entraram
    r = calc.pulse_count_window([100, 100], [1100, 1300])
    assert r["n_sum"] == 200 and r["n_delta"] == 300 and r["n"] == 300 and r["method"] == "acumulado"


def test_contador_reiniciado_usa_a_soma_e_sinaliza():
    r = calc.pulse_count_window([100, 100, 100], [1100, 100, 200])
    assert r["reset"] and r["method"] == "soma" and r["n"] == 300 and r["n_delta"] is None


def test_sem_acumulado_no_programa_usa_a_soma():
    r = calc.pulse_count_window([5, 0, 7], [None, None, None])
    assert r["n"] == 12 and r["method"] == "soma" and r["n_delta"] is None and not r["reset"]


def test_sem_registros_nao_inventa_contagem():
    r = calc.pulse_count_window([], [])
    assert r["n"] is None and r["n_sum"] is None and r["method"] is None
