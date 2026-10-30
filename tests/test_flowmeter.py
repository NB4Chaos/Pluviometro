"""Medidor de vazão: funções puras de calc.py (sem rede, sem banco, sem relógio). Valores SINTÉTICOS de teste.

Analógico: Q = q4 + (I − 4)/16 · (q20 − q4)         Pulsos: f = N / janela real (s);  Q[L/min] = f / K[pulsos/L] · 60
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import calc

CFG = {"q4": 0.0, "q20": 100.0, "range_unit": "L/min", "density": 0.9982, "k_pulses_per_l": 1000.0, "ma_tol": 0.02}
BOTH = {"analog", "pulse"}


def an(ma, **kw):
    return calc.flow_reading("analog", BOTH, "ok", ma, None, None, None, dict(CFG, **kw))


def pu(pulses, code=0, dt_ms=1000, **kw):
    return calc.flow_reading("pulse", BOTH, "ok", None, pulses, code, dt_ms, dict(CFG, **kw))


# ---------------------------------------------------------------- 4–20 mA perto dos limites
@pytest.mark.parametrize("ma, cls, eff", [
    (0.0, "fault", None), (1.3, "fault", None), (3.0, "fault", None),     # laço aberto e alarmes do MAG 5000 (1,3 / 2 / 3 mA)
    (3.7, "under", None), (3.979, "under", None),
    (3.985, "low", 4.0), (3.9999, "low", 4.0),                              # ruído em vazão zero: preso em 4 mA, sem extrapolar
    (4.0, "ok", 4.0), (12.0, "ok", 12.0), (20.0, "ok", 20.0),
    (20.015, "high", 20.0), (20.021, "over", None), (21.0, "over", None), (None, "invalid", None)])
def test_classificacao_do_sinal_perto_dos_limites(ma, cls, eff):
    assert calc.classify_ma(ma, 0.02) == (cls, eff)


def test_tolerancia_zero_reproduz_o_criterio_antigo_exato():
    assert calc.classify_ma(3.9999, 0)[0] == "under" and calc.classify_ma(20.0001, 0)[0] == "over"
    assert calc.flow_from_sample("analog", "ok", None, 3.9999, None, 0.0, 100.0, "L/min") is None   # ma_tol padrão = 0


@pytest.mark.parametrize("ma, q", [(4.0, 0.0), (8.0, 25.0), (12.0, 50.0), (20.0, 100.0)])
def test_corrente_proxima_e_intermediaria_converte_linear(ma, q):
    r = an(ma)
    assert r["state"] == "ok" and r["lmin"] == pytest.approx(q) and r["clamp"] is None


def test_limite_inferior_dentro_da_tolerancia_da_vazao_do_limite_e_marca():
    r = an(3.99)
    assert r["state"] == "ok" and r["lmin"] == 0.0 and r["clamp"] == "low" and r["ma"] == 3.99   # o mA bruto continua visível


def test_acima_de_20_alem_da_tolerancia_nao_calcula_saturacao():
    r = an(20.5)
    assert r["state"] == "out_of_range" and r["lmin"] is None and "Qmax" in r["reason"] and r["ma"] == 20.5


def test_abaixo_da_faixa_e_falha_sao_estados_diferentes():
    assert an(3.8)["state"] == "out_of_range" and an(2.0)["state"] == "fault"


def test_corrente_sem_leitura_e_faixa_incompleta():
    assert an(None)["state"] == "invalid"
    r = an(12.0, q4=None)
    assert r["state"] == "unconfigured" and r["lmin"] is None and r["ma"] == 12.0


def test_faixa_invertida_e_unidade_m3h():
    assert an(4.0, q4=10.0, q20=0.0)["lmin"] == pytest.approx(10.0)
    assert an(12.0, q4=0.0, q20=6.0, range_unit="m³/h")["lmin"] == pytest.approx(3.0 * 1000 / 60)   # 3 m³/h = 50 L/min


def test_faixa_massica_sem_densidade_nao_inventa():
    r = an(12.0, range_unit="kg/h", density=None)
    assert r["state"] == "unconfigured" and r["lmin"] is None


# ---------------------------------------------------------------- pulsos
def test_ausencia_de_pulsos_e_vazao_zero_valida_nao_ausencia_de_dado():
    r = pu(0)
    assert r["state"] == "ok" and r["lmin"] == 0.0 and r["hz"] == 0.0


def test_um_pulso_por_janela_e_a_resolucao():
    r = pu(1)
    assert r["lmin"] == pytest.approx(0.06) and r["resolution_lmin"] == pytest.approx(0.06)   # K = 1000 pulsos/L, janela 1 s


def test_frequencia_estavel():
    r = pu(100)
    assert r["hz"] == 100.0 and r["lmin"] == pytest.approx(6.0) and r["window_s"] == 1.0 and not r["window_assumed"]


def test_contagem_nao_e_frequencia_quando_a_janela_e_maior():
    r = pu(200, dt_ms=2000)            # Scan pulado: 200 pulsos em 2 s = 100 Hz, não 200 Hz
    assert r["hz"] == 100.0 and r["lmin"] == pytest.approx(6.0)


@pytest.mark.parametrize("dt", [None, 0, 5000])
def test_janela_desconhecida_ou_com_lacuna_usa_o_scan_nominal_e_avisa(dt):
    r = pu(50, dt_ms=dt)
    assert r["window_s"] == 1.0 and r["window_assumed"] and r["hz"] == 50.0


def test_frequencia_variavel_amostra_a_amostra():
    vals = [pu(n)["lmin"] for n in (0, 10, 250, 1000)]
    assert vals == pytest.approx([0.0, 0.6, 15.0, 60.0])


@pytest.mark.parametrize("code, word", [(1, "primeiro Scan"), (2, "saturado"), (3, "acima do máximo"), (4, "NAN"), (9, "código")])
def test_codigos_do_canal_de_pulsos_invalidam_com_motivo(code, word):
    r = pu(15000, code=code)
    assert r["state"] == "invalid" and r["lmin"] is None and word in r["reason"]


@pytest.mark.parametrize("k", [None, 0, -5])
def test_fator_k_ausente_ou_invalido_nunca_vira_numero(k):
    r = pu(100, k_pulses_per_l=k)
    assert r["state"] == "unconfigured" and r["lmin"] is None and r["hz"] == 100.0   # a frequência bruta continua disponível


def test_canal_que_o_programa_nao_tem_e_indisponivel():
    r = calc.flow_reading("pulse", {"analog"}, "ok", 12.0, None, None, None, CFG)
    assert r["state"] == "unavailable" and "P2" in r["reason"]


def test_sem_registro_do_medidor_e_sem_comunicacao():
    assert calc.flow_reading("pulse", BOTH, "no_comm", None, None, None, None, CFG)["state"] == "no_comm"


def test_metodo_desconhecido_nao_e_presumido():
    assert calc.flow_reading(None, BOTH, "ok", 12.0, 10, 0, 1000, CFG)["state"] == "unconfigured"


# ---------------------------------------------------------------- fator K e unidades
@pytest.mark.parametrize("value, unit, k_l", [(1000, "pulsos/L", 1000.0), (1e6, "pulsos/m³", 1000.0), (2.5, "L/pulso", 0.4),
                                              (10, "mL/pulso", 100.0), (0.01, "pulsos/L", 0.01)])
def test_fator_k_normalizado_em_pulsos_por_litro(value, unit, k_l):
    assert calc.k_to_pulses_per_l(value, unit) == pytest.approx(k_l)
    assert calc.k_from_pulses_per_l(k_l, unit) == pytest.approx(value)


@pytest.mark.parametrize("value, unit", [(0, "pulsos/L"), (-1, "pulsos/L"), (float("nan"), "pulsos/L"), (float("inf"), "L/pulso"),
                                         ("abc", "pulsos/L"), (None, "pulsos/L"), (10, "pulsos/galão")])
def test_fator_k_invalido_vira_none(value, unit):
    assert calc.k_to_pulses_per_l(value, unit) is None


def test_mesma_vazao_com_k_em_unidades_diferentes():
    k_m3 = calc.k_to_pulses_per_l(1e6, "pulsos/m³")
    assert pu(600, k_pulses_per_l=k_m3)["lmin"] == pytest.approx(36.0)                     # 600 Hz ÷ 1000 pulsos/L × 60
    assert calc.flow_to_l_min(36.0, "m³/h") == pytest.approx(600.0)                        # conversão de exibição separada


# ---------------------------------------------------------------- volume por contador acumulado
TS = [0, 1000, 2000, 3000, 4000]


def test_volume_pelo_acumulado_nao_perde_pulsos_de_registro_ausente():
    ts = [0, 1000, 3000, 4000]                  # registro de 2000 ausente
    pulses, totals, valid = [100, 100, 100, 100], [100, 200, 400, 500], [True] * 4
    n, how, aviso = calc.pulses_between(ts, pulses, totals, valid, 0, 4000)
    assert (n, how, aviso) == (400, "acumulado", None)                                     # a soma daria 300
    assert calc.pulses_between(ts, pulses, [None] * 4, valid, 0, 4000)[:2] == (300, "soma")


def test_acumulado_reiniciado_no_meio_volta_para_a_soma_e_avisa():
    n, how, aviso = calc.pulses_between(TS, [10] * 5, [50, 60, 5, 15, 25], [True] * 5, 0, 4000)
    assert how == "soma" and n == 40 and "reiniciado" in aviso


def test_soma_ignora_contagens_invalidas():
    n, how, _ = calc.pulses_between(TS, [10, 10, 99999, 10, 10], [None] * 5, [True, True, False, True, True], 0, 4000)
    assert (n, how) == (30, "soma")


def test_estado_gravado_separa_dado_de_configuracao():
    assert calc.stored_status(pu(10, k_pulses_per_l=None)) == "ok"      # contagem válida; falta só o K
    assert calc.stored_status(an(2.0)) == "out_of_range" and calc.stored_status(an(None)) == "invalid"
    assert math.isclose(calc.pulse_resolution_l_min(1000, 2.0), 0.03)
