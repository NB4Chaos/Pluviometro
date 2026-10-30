"""Cálculos de precipitação, intensidade, média móvel, vazão e gravimetria. Exemplos conferidos à mão."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import calc

S = 1000


def samples(a, b, step=S):
    return list(range(a, b, step))


# ---- intervalos semiabertos [início, fim)
def test_evento_na_fronteira_conta_so_no_periodo_seguinte():
    tips = [0, 10 * S, 20 * S]
    assert calc.count_in(tips, 0, 10 * S) == 1          # 10 s fica de fora
    assert calc.count_in(tips, 10 * S, 20 * S) == 1     # 10 s entra aqui; 20 s fica de fora
    assert calc.count_in(tips, 0, 10 * S) + calc.count_in(tips, 10 * S, 20 * S) + calc.count_in(tips, 20 * S, 30 * S) == 3


# ---- precipitação e intensidade (exemplo do enunciado: 0,5 mm em 15 min = 2 mm/h; em 1 h = 0,5 mm/h)
def test_intensidade_media_exemplo_do_enunciado():
    res = 0.25                                            # 2 basculadas de 0,25 mm = 0,5 mm
    end = 900 * S
    r = calc.precip_period([100 * S, 500 * S], samples(0, end), 0, end, res)
    assert r["precip_mm"] == pytest.approx(0.5)
    assert r["complete"] and r["covered_s"] == pytest.approx(900)
    assert r["intensity_mm_h"] == pytest.approx(2.0)
    end = 3600 * S
    r = calc.precip_period([100 * S, 500 * S], samples(0, end), 0, end, res)
    assert r["intensity_mm_h"] == pytest.approx(0.5)


def test_lacuna_nao_vira_chuva_zero_e_marca_parcial():
    # 10 min de dados, 10 min SEM dados, 10 min de dados; 1 basculada em cada trecho coberto
    smp = samples(0, 600 * S) + samples(1200 * S, 1800 * S)
    r = calc.precip_period([300 * S, 1500 * S], smp, 0, 1800 * S, 0.2)
    assert not r["complete"] and r["gaps"] == 1
    assert r["covered_s"] == pytest.approx(1200)
    assert r["intensity_mm_h"] == pytest.approx(2 * 0.2 / (1200 / 3600))   # tempo coberto, não 30 min


def test_sem_amostras_e_sem_eventos_e_indisponivel_nao_zero():
    r = calc.precip_period([], [], 0, 60 * S, 0.2)
    assert r["precip_mm"] is None and r["intensity_mm_h"] is None and not r["complete"]


def test_sem_resolucao_nao_inventa_mm():
    r = calc.precip_period([5 * S], samples(0, 60 * S), 0, 60 * S, None)
    assert r["precip_mm"] is None and r["intensity_mm_h"] is None and r["tips"] == 1


def test_periodo_sem_chuva_com_cobertura_e_zero_valido():
    r = calc.precip_period([], samples(0, 60 * S), 0, 60 * S, 0.2)
    assert r["precip_mm"] == 0 and r["intensity_mm_h"] == 0 and r["complete"]


def test_cobertura_uma_amostra_ausente_ainda_e_completa():
    smp = [t for t in samples(0, 60 * S) if t != 30 * S]
    cov, gaps, complete = calc.window_coverage(smp, 0, 60 * S)
    assert complete and cov >= 58 * S


# ---- média móvel
def test_media_movel_responde_ao_degrau_em_uma_janela():
    ts = samples(0, 200 * S)
    vals = [0.0] * 100 + [120.0] * 100                    # degrau 0 -> 120 em t = 100 s
    ma = calc.rolling_mean(ts, vals, 30 * S, min_n=3)
    assert ma[99] == 0.0
    assert ma[100 + 29] == pytest.approx(120.0)           # 30 s depois a janela só tem 120
    assert 0 < ma[110] < 120
    # a média de TODO o período ainda estaria longe: é o comportamento antigo que atrasava
    assert calc.stats(vals)[0] == pytest.approx(60.0)


def test_media_movel_ignora_nan_e_exige_minimo():
    ts = samples(0, 10 * S)
    vals = [None, None, 5.0, None, 7.0, None, None, None, None, None]
    ma = calc.rolling_mean(ts, vals, 5 * S, min_n=2)
    assert ma[2] is None                                  # só 1 válido
    assert ma[4] == pytest.approx(6.0)
    assert ma[9] is None                                  # janela sem válidos
    assert calc.rolling_mean([], [], 5 * S) == []


def test_media_movel_zero_e_valor_valido():
    assert calc.rolling_mean(samples(0, 5 * S), [0.0] * 5, 5 * S, min_n=3)[-1] == 0.0


# ---- inclinação (vazão pela balança)
def test_inclinacao_da_massa():
    ts = samples(0, 120 * S)
    vals = [100 + 0.5 * (t / S) for t in ts]              # 0,5 g/s
    sl = calc.rolling_slope(ts, vals, 60 * S)
    assert sl[-1] == pytest.approx(0.5)
    assert sl[2] is None                                  # poucos pontos
    # 0,5 g/s = 30 g/min = 0,03 L/min com ρ = 1
    assert calc.mass_slope_to_l_min(0.5, 1.0) == pytest.approx(0.03)
    assert calc.mass_slope_to_l_min(0.5, None) is None


# ---- gravimetria
def test_gravimetria_massa_inicial_nao_zero_usa_so_a_variacao():
    # balança já tinha 500 g; durante 10 min entraram 600 g de água (ρ = 1,0 g/cm³), área 200 cm²
    g = calc.gravimetric(500.0, 1100.0, 0, 600 * S, 1.0, 200.0, pulses=30, res_mm=0.2)
    assert g["delta_mass_g"] == pytest.approx(600)
    assert g["volume_ml"] == pytest.approx(600) and g["volume_l"] == pytest.approx(0.6)
    assert g["precip_ref_mm"] == pytest.approx(10 * 600 / 200)          # 30 mm
    assert g["intensity_ref_mm_h"] == pytest.approx(30 / (10 / 60))     # 180 mm/h
    assert g["flow_ref_l_min"] == pytest.approx(0.06)
    assert g["pluv_precip_mm"] == pytest.approx(6.0)                    # 30 × 0,2: NÃO aplica a resolução duas vezes
    assert g["diff_mm"] == pytest.approx(6.0 - 30.0)
    assert g["error_pct"] == pytest.approx(-80.0)


def test_gravimetria_densidade_diferente_de_1():
    g = calc.gravimetric(0.0, 998.1, 0, 60 * S, 0.9981, 100.0)
    assert g["volume_ml"] == pytest.approx(1000.0)
    assert g["precip_ref_mm"] == pytest.approx(100.0)


def test_gravimetria_balanca_sem_variacao_da_zero_valido():
    g = calc.gravimetric(250.0, 250.0, 0, 60 * S, 1.0, 100.0, pulses=0, res_mm=0.2)
    assert g["volume_l"] == 0 and g["precip_ref_mm"] == 0 and g["flow_ref_l_min"] == 0
    assert g["error_pct"] is None                                         # 0/0: erro percentual não definido


def test_gravimetria_massa_diminuiu_e_invalida():
    g = calc.gravimetric(500.0, 100.0, 0, 60 * S, 1.0, 100.0)
    assert g["volume_ml"] is None and g["issues"]


def test_gravimetria_sem_area_ou_densidade_nao_inventa():
    g = calc.gravimetric(0.0, 100.0, 0, 60 * S, 1.0, None)
    assert g["volume_ml"] == pytest.approx(100) and g["precip_ref_mm"] is None and g["issues"]
    g = calc.gravimetric(0.0, 100.0, 0, 60 * S, None, 100.0)
    assert g["volume_ml"] is None and g["flow_ref_l_min"] is None


def test_gravimetria_sem_leituras_ou_mesmo_instante():
    assert calc.gravimetric(None, None, None, None, 1.0, 100.0)["issues"]
    assert calc.gravimetric(1.0, 2.0, 5, 5, 1.0, 100.0)["volume_ml"] is None


def test_usa_tempo_efetivo_entre_as_leituras_de_massa():
    # janela de 60 s, mas a massa válida só vai de 10 s a 50 s: o tempo é 40 s
    g = calc.gravimetric(0.0, 40.0, 10 * S, 50 * S, 1.0, 100.0)
    assert g["duration_s"] == 40 and g["flow_ref_l_min"] == pytest.approx(0.04 / (40 / 60))


# ---- unidades
@pytest.mark.parametrize("v,u,rho,exp", [(1, "L/min", None, 1), (60, "L/h", None, 1), (1000, "mL/min", None, 1),
                                         (1, "mL/s", None, 0.06), (0.06, "m³/h", None, 1), (1, "kg/h", 1.0, 1 / 60),
                                         (1, "kg/s", 0.9982, 60 / 0.9982)])
def test_conversao_de_vazao(v, u, rho, exp):
    assert calc.flow_to_l_min(v, u, rho) == pytest.approx(exp)


def test_vazao_massica_sem_densidade_e_none():
    assert calc.flow_to_l_min(1, "kg/h", None) is None and calc.flow_to_l_min(None, "L/min") is None
