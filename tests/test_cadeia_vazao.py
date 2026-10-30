"""Cadeia completa da vazão por pulsos: pulsos reais → N acumulado → volume (N ÷ K) → tempo efetivo → vazão → frequência → incerteza.
Cenários pedidos em 31/10 (volume, vazão, frequência, temporização, incerteza/arredondamento). Funções puras + banco em memória;
a parte de API usa o emulador v4 com dados fictícios e pasta temporária. Nenhum teste aqui valida a resolução FÍSICA do CR1000Xe:
o Scan real é de 1000 ms; o Scan de 100 ms abaixo só mostra que o software acompanha um programa mais rápido."""
import json, math, os, sqlite3, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import calc
from trials import Trials, TrialError
from tests.test_pulsos_brutos_timing import Env, CFG, COLS, T0
from tests.test_flow_api import boot, cycle, post
from tests.fake_programa_atual import Fake

K = calc.k_to_pulses_per_l
S = 1000


# ---------------- volume: N ÷ K em cada unidade aceita para K
@pytest.mark.parametrize("n,expect_l", [(0, 0.0), (1, 0.01), (100, 1.0), (1250, 12.5)])
def test_volume_com_k_em_pulsos_por_litro(n, expect_l):
    assert n / K(100, "pulsos/L") == pytest.approx(expect_l)


@pytest.mark.parametrize("value,unit,n,expect_l", [
    (100, "pulsos/L", 1250, 12.5), (100_000, "pulsos/m³", 1250, 12.5), (0.01, "L/pulso", 1250, 12.5), (10, "mL/pulso", 1250, 12.5),
    (1000, "pulsos/L", 1, 0.001), (2.5, "mL/pulso", 400, 1.0)])
def test_volume_em_cada_unidade_do_fator_k(value, unit, n, expect_l):
    assert n / K(value, unit) == pytest.approx(expect_l)


def test_k_invalido_nunca_vira_k_presumido():
    assert K(None) is None and K(0) is None and K(-5) is None and K("abc") is None and K(100, "pulsos/galão") is None
    assert calc.k_from_pulses_per_l(K(10, "mL/pulso"), "mL/pulso") == pytest.approx(10)   # ida e volta sem perda


# ---------------- vazão instantânea: Q = pulsos ÷ janela ÷ K × 60, janela REAL (inclusive < 1 s)
CFG_R = {"k_pulses_per_l": 100.0, "q4": 0.0, "q20": 100.0, "range_unit": "L/min", "density": 1.0, "ma_tol": 0.02}


@pytest.mark.parametrize("pulses,dt_ms,hz,lmin", [
    (0, 1000, 0.0, 0.0), (1, 1000, 1.0, 0.6), (10, 1000, 10.0, 6.0), (50, 1000, 50.0, 30.0), (100, 1000, 100.0, 60.0),
    (100, 2000, 50.0, 30.0),      # Scan pulado: o contador de hardware acumulou 2 s → a janela real é 2 s
    (5, 500, 10.0, 6.0),          # janela de 500 ms (programa mais rápido): 5 pulsos em 0,5 s = 10 Hz
    (1, 100, 10.0, 6.0),          # 100 ms
    (10_000, 1000, 10_000.0, 6000.0)])   # frequência alta (limite do medidor)
def test_vazao_instantanea_usa_a_janela_real(pulses, dt_ms, hz, lmin):
    r = calc.flow_reading("pulse", {"pulse", "analog"}, "ok", None, pulses, 0, dt_ms, CFG_R)
    assert r["state"] == "ok" and r["hz"] == pytest.approx(hz) and r["lmin"] == pytest.approx(lmin) and r["window_s"] == dt_ms / 1000 and r["window_assumed"] is False


def test_zero_pulsos_valido_e_0_hz_mas_sem_dado_e_indisponivel():
    ok = calc.flow_reading("pulse", {"pulse"}, "ok", None, 0, 0, 1000, CFG_R)
    assert ok["state"] == "ok" and ok["hz"] == 0.0 and ok["lmin"] == 0.0
    nc = calc.flow_reading("pulse", {"pulse"}, "no_comm", None, None, None, None, CFG_R)
    assert nc["state"] == "no_comm" and nc["hz"] is None and nc["lmin"] is None
    nan = calc.flow_reading("pulse", {"pulse"}, "ok", None, None, 4, 1000, CFG_R)
    assert nan["state"] == "invalid" and nan["hz"] is None
    sem_k = calc.flow_reading("pulse", {"pulse"}, "ok", None, 100, 0, 1000, dict(CFG_R, k_pulses_per_l=None))
    assert sem_k["state"] == "unconfigured" and sem_k["hz"] == 100.0 and sem_k["lmin"] is None   # a contagem/frequência sobrevive sem K


def test_janela_sem_registro_anterior_e_presumida_igual_ao_scan():
    r = calc.flow_reading("pulse", {"pulse"}, "ok", None, 100, 0, None, CFG_R)
    assert r["window_assumed"] is True and r["window_s"] == 1.0 and r["hz"] == 100.0


@pytest.mark.parametrize("unit,factor", [("L/min", 1), ("L/h", 60), ("mL/min", 1000), ("mL/s", 1000 / 60), ("m³/h", 0.06), ("m³/s", 1 / 60000), ("m³/min", 0.001)])
def test_conversao_de_unidades_de_vazao_e_consistente_com_a_tabela_do_frontend(unit, factor):
    # 12,5 L/min expressos em `unit` devem voltar a 12,5 L/min pela tabela do servidor (mesma tabela de util.js)
    assert calc.flow_to_l_min(12.5 * factor, unit) == pytest.approx(12.5, rel=1e-12)


def test_unidade_massica_exige_densidade():
    assert calc.flow_to_l_min(60, "kg/h", 1.0) == pytest.approx(1.0) and calc.flow_to_l_min(60, "kg/h", None) is None


# ---------------- ensaio: N, V, Q e f a partir dos registros (banco em memória)
def test_exemplo_de_validacao_1250_pulsos_60_s_k_100():
    e = Env({"flow_k_pulses_per_l": 100.0})
    pulses = {s: 21 if s - 5 < 50 else 20 for s in range(5, 65)}      # 50×21 + 10×20 = 1250 nos 60 registros do ensaio
    f = e.run(pulses=lambda s: pulses.get(s, 0))["result"]["flow"]
    assert f["pulses_total"] == 1250 and f["time_eff_ms"] == 60_000
    assert f["volume_l"] == pytest.approx(12.5) and f["flow_l_min"]["mean"] == pytest.approx(12.5) and f["freq_mean_hz"] == pytest.approx(1250 / 60)


@pytest.mark.parametrize("k_value,k_unit", [(100, "pulsos/L"), (100_000, "pulsos/m³"), (0.01, "L/pulso"), (10, "mL/pulso")])
def test_ensaio_com_k_em_cada_unidade_da_o_mesmo_volume(k_value, k_unit):
    e = Env({"flow_k_pulses_per_l": K(k_value, k_unit), "flow_k_unit": k_unit})
    f = e.run(pulses=10, after=70)["result"]["flow"]          # 60 registros × 10 = 600 pulsos (o ensaio só fecha com um registro além do fim)
    assert f["pulses_total"] == 600 and f["volume_l"] == pytest.approx(6.0) and f["flow_l_min"]["mean"] == pytest.approx(6.0)


def test_frequencia_variavel_no_ensaio_media_e_N_sobre_tempo_efetivo():
    e = Env({"flow_k_pulses_per_l": 1000.0})
    seq = {s: [0, 1, 10, 50, 100, 100, 50, 10, 1, 0][(s - 5) % 10] for s in range(5, 65)}
    f = e.run(pulses=lambda s: seq.get(s, 0))["result"]["flow"]
    n = sum(seq.values())
    assert f["pulses_total"] == n and f["freq_mean_hz"] == pytest.approx(n / 60) and f["flow_l_min"]["mean"] == pytest.approx(n / 1000 / 60 * 60)
    assert f["flow_l_min"]["max"] == pytest.approx(100 / 1000 * 60) and f["flow_l_min"]["min"] == 0.0   # instantâneas: 0 e 100 Hz


def test_vazao_proxima_de_zero_nao_e_arredondada_no_servidor():
    e = Env({"flow_k_pulses_per_l": 1000.0})
    f = e.run(pulses=lambda s: 1 if s == 30 else 0)["result"]["flow"]
    assert f["volume_l"] == pytest.approx(0.001) and f["flow_l_min"]["mean"] == pytest.approx(0.001)   # 1 mL/min: não vira 0,000


def test_cobertura_do_ensaio_conta_o_scan_de_cada_registro():
    """5 registros a cada 1 s cobrem 5 s de ensaio (antes: 4,001 s, porque o registro em t era tratado como [t, t+Scan))."""
    e = Env({"trial_duration_ms": 5000})
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    e.feed(5, 12)
    q = e.tr.get(t["id"])["result"]["quality"]
    assert q["rows"] == 5 and q["covered_s"] == pytest.approx(4.999, abs=0.001) and q["gaps"] == 0 and q["coverage_complete"]


def test_convencao_antiga_de_cobertura_continua_para_os_periodos_da_tela():
    ts = [1000, 2000, 3000]
    assert calc.covered_intervals(ts, 0, 4000) == [(1000, 4000)]                   # [t, t+Δ)
    assert calc.covered_intervals(ts, 0, 4000, backward=True) == [(0, 3000)]       # (t−Δ, t]
    assert calc.covered_intervals([1000, 2000, 10_000], 0, 11_000, backward=True) == [(0, 2000), (9000, 10_000)]   # lacuna


# ---------------- temporização: resolução = Scan; durações aceitas e tempo efetivo
class EnvMs(Env):
    """Registros em qualquer instante (ms) com a janela de contagem informada: imita um programa com Scan menor que 1 s."""
    def add_ms(self, ms, pulses, dt_ms):
        self.total += pulses
        self.db.execute(f"INSERT OR REPLACE INTO samples({COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (T0 + ms, 500.0, 22.0, "ok", "ok", 0, 12.0, "ok", "pulse", pulses, pulses / (dt_ms / 1000), self.total, 0, 0, dt_ms))
        self.db.commit()


@pytest.mark.parametrize("scan_ms,dur_ms,aceita", [(1000, 10, False), (1000, 100, False), (1000, 500, False), (1000, 1000, True), (1000, 10_000, True), (1000, 60_000, True),
                                                   (100, 10, False), (100, 100, True), (100, 500, True), (100, 1000, True)])
def test_duracao_aceita_so_a_partir_de_um_scan(scan_ms, dur_ms, aceita):
    e = Env({"trial_duration_ms": dur_ms}, scan_ms=scan_ms)
    e.feed(0, 5)
    if aceita:
        t = e.tr.start("flow", True)
        assert t["end_ts"] - t["start_ts"] == dur_ms and t["duration_cfg_ms"] == dur_ms
    else:
        with pytest.raises(TrialError) as x:
            e.tr.start("flow", True)
        assert x.value.status == 400 and f"{scan_ms} ms" in x.value.msg


@pytest.mark.parametrize("scan_ms,dur_ms,n_rows", [(100, 100, 1), (100, 500, 5), (100, 1000, 10), (1000, 10_000, 10), (1000, 60_000, 60)])
def test_tempo_efetivo_segue_a_resolucao_do_programa(scan_ms, dur_ms, n_rows):
    e = EnvMs({"trial_duration_ms": dur_ms, "flow_k_pulses_per_l": 100.0}, scan_ms=scan_ms)
    e.feed(0, 5)                                            # 5 registros antes, em segundos inteiros
    t = e.tr.start("flow", True)
    base = t["start_ts"] - 1                                # último carimbo antes do ensaio
    for i in range(1, n_rows + 2):                          # +1 registro depois do fim: é ele que fecha o ensaio (relógio do datalogger)
        e.add_ms(base - T0 + i * scan_ms, 2, scan_ms)       # 2 pulsos por Scan
    e.tr.tick(int(time.time() * 1000))
    r = e.tr.get(t["id"])
    f, tm = r["result"]["flow"], r["result"]["timing"]
    assert tm["resolution_ms"] == scan_ms and tm["samples"] == n_rows and tm["eff_ms"] == dur_ms and f["time_eff_ms"] == dur_ms
    assert f["pulses_total"] == 2 * n_rows and f["volume_l"] == pytest.approx(2 * n_rows / 100) and f["flow_l_min"]["mean"] == pytest.approx(2 * n_rows / 100 / (dur_ms / 60000))
    assert f["freq_mean_hz"] == pytest.approx(2 / (scan_ms / 1000))


def test_tempo_configurado_nao_substitui_o_tempo_medido():
    """Ensaio parado antes do fim: Q usa o tempo coberto pelos registros, não os 60 s configurados."""
    e = Env({"flow_k_pulses_per_l": 100.0})
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    e.feed(5, 35)                                           # 30 registros × 100 pulsos
    e.tr.stop()
    f = e.tr.get(t["id"])["result"]["flow"]
    assert f["pulses_total"] == 3000 and f["time_eff_ms"] == 30_000 and f["volume_l"] == pytest.approx(30.0) and f["flow_l_min"]["mean"] == pytest.approx(60.0)


# ---------------- sem incerteza no sistema (decisão do laboratório): o resultado do ensaio não traz esse bloco
def test_resultado_do_ensaio_nao_calcula_incerteza():
    e = Env({"flow_k_pulses_per_l": 100.0})
    f = e.run(pulses=20)["result"]["flow"]
    assert "uncertainty" not in f and not hasattr(calc, "pulse_uncertainty")


def test_consistencia_dimensional_da_cadeia():
    """Q [L/min] = N [pulsos] ÷ K [pulsos/L] ÷ t [s] × 60 [s/min]; f [Hz] = N ÷ t; Q = f ÷ K × 60."""
    n, k, t = 1250, 100.0, 60.0
    q = n / k / t * 60
    f = n / t
    assert q == pytest.approx(12.5) and f / k * 60 == pytest.approx(q)
    # leitura instantânea (janela de 1 Scan): 21 pulsos em 1 s com K = 100 → 21 Hz → 12,6 L/min, a mesma relação f ÷ K × 60
    assert calc.flow_reading("pulse", {"pulse"}, "ok", None, 21, 0, 1000, dict(CFG_R, k_pulses_per_l=k))["lmin"] == pytest.approx(21 / k * 60)


# ---------------- API: nada arredondado em L/min antes da conversão de unidade na tela
@pytest.fixture
def v4(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v4")
    fake.flow_hz = 1   # 1 pulso/s
    app = boot(tmp_path, monkeypatch, fake, extra={"flow_k_pulses_per_l": 100_000.0, "flow_method": "pulse"})   # 1 Hz ÷ 100 000 pulsos/L = 0,0006 L/min = 0,6 mL/min
    yield app, fake, app.app.test_client()
    fake.stop()


def test_serie_e_resumo_preservam_vazoes_pequenas(v4):
    app, fake, c = v4
    for _ in range(3):
        cycle(app, fake)
    now = int(time.time() * 1000)
    s = c.get(f"/api/series?from={now - 600_000}&to={now + 60_000}").get_json()
    vals = [v for v in s["flow"] if v is not None]          # o pré-carregamento do emulador veio a 100 Hz; os registros novos a 1 Hz
    assert vals and min(vals) == pytest.approx(0.0006, rel=1e-6)                       # antes: round(…, 3) → 0,001 ou 0,0
    st = c.get(f"/api/summary?from={now - 600_000}&to={now + 60_000}").get_json()["stats"]["cor"]
    assert st["flow"]["min"] == pytest.approx(0.0006, rel=1e-6) and st["pulses"]["n"] >= 3


def test_config_ignora_chave_de_incerteza_de_versao_intermediaria(v4):
    app, fake, c = v4
    st, j = post(c, "/api/config", {"flow_k_uncertainty_pct": "0,5"})
    assert st == 200 and "flow_k_uncertainty_pct" not in j
