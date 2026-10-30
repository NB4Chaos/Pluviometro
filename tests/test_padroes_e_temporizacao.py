"""Fase 3 (01/11): fator K em pulsos/kg (massa, sem converter para volume sem densidade), temporização fina da v5 (carimbos do Timer
do datalogger dentro do segundo), resolução de tempo configurável × efetiva, cadastro/seleção de padrões e cópia congelada no ensaio.
Banco em memória e emulador com dados fictícios; nada aqui valida o hardware."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import calc
from trials import Trials, TrialError, SCOLS
from tests.test_pulsos_brutos_timing import Env, T0
from tests.test_flow_api import boot, cycle, post
from tests.fake_programa_atual import Fake

K = calc.k_to_pulses_per_l


# ---------------- fator K: pulsos/L × pulsos/kg
def test_pulsos_por_kg_e_grandeza_massica():
    assert calc.k_is_mass("pulsos/kg") and not calc.k_is_mass("pulsos/L")
    assert K(500, "pulsos/kg") is None                                  # sem densidade: NÃO vira pulsos/L
    assert K(500, "pulsos/kg", 0.9982) == pytest.approx(499.1)          # com ρ = 0,9982 kg/L: 500 pulsos/kg = 499,1 pulsos/L
    assert calc.k_from_pulses_per_l(499.1, "pulsos/kg", 0.9982) == pytest.approx(500)
    assert calc.k_from_pulses_per_l(499.1, "pulsos/kg") is None


def test_ensaio_com_k_em_pulsos_por_kg_da_massa_e_volume_so_com_densidade():
    e = Env({"flow_k_pulses_per_l": K(100, "pulsos/kg", 1.0), "flow_k_unit": "pulsos/kg", "flow_k_input": 100, "density_g_cm3": 1.0})
    pulses = {s: 21 if s - 5 < 50 else 20 for s in range(5, 65)}        # 1250 pulsos em 60 s
    f = e.run(pulses=lambda s: pulses.get(s, 0))["result"]["flow"]
    assert f["k_basis"] == "mass" and f["mass_kg"] == pytest.approx(12.5) and f["mass_flow_kg_min"] == pytest.approx(12.5)
    assert f["volume_l"] == pytest.approx(12.5) and f["flow_l_min"]["mean"] == pytest.approx(12.5)   # ρ = 1,0 → 12,5 L


def test_ensaio_com_k_em_pulsos_por_kg_sem_densidade_preserva_massa_e_nao_inventa_volume():
    e = Env({"flow_k_pulses_per_l": None, "flow_k_unit": "pulsos/kg", "flow_k_input": 100})
    r = e.run(pulses=20)
    f = r["result"]["flow"]
    assert f["pulses_total"] == 1200 and f["mass_kg"] == pytest.approx(12.0) and f["volume_l"] is None and f["flow_l_min"] is None
    assert any("pulsos/kg" in i for i in f["issues"]) and r["state"] == "incomplete"


# ---------------- temporização fina (v5): carimbos do Timer dentro do segundo
COLS18 = SCOLS


class EnvV5(Env):
    def __init__(self, cfg=None, scan_ms=1000, fast_ms=10):
        super().__init__(cfg, scan_ms)
        self.fast_ms = fast_ms
        self.db.executescript("ALTER TABLE samples ADD COLUMN flow_t1_ms INTEGER; ALTER TABLE samples ADD COLUMN flow_t2_ms INTEGER; ALTER TABLE samples ADD COLUMN flow_tres_ms INTEGER;")
        self.tr = Trials(self.db, self.lock, lambda: self.cfg, lambda: self.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0], scan_ms=scan_ms)

    def add5(self, sec, pulses, t1, t2):
        ts = T0 + sec * 1000
        self.total += pulses
        self.db.execute(f"INSERT OR REPLACE INTO samples({COLS18}) VALUES({','.join('?' * 17)})",
                        (ts, 500.0, 22.0, "ok", "ok", 12.0, "ok", "pulse", pulses, float(pulses), self.total, 0, 0, 1000, t1, t2, self.fast_ms))
        self.db.commit()


def test_tempo_efetivo_pelos_carimbos_do_timer_com_resolucao_do_scan_rapido():
    e = EnvV5({"flow_k_pulses_per_l": 100.0, "trial_duration_ms": 5000}, fast_ms=10)
    for s in range(5):
        e.add5(s, 100, 10, 1000)
    t = e.tr.start("flow", True)
    # pulsos só começam 400 ms depois do início do 1º segundo e param 300 ms antes do fim do último: Δt = 5000 − 400 − 300 = 4300 ms (res 10 ms)
    e.add5(5, 60, 410, 1000); e.add5(6, 100, 10, 1000); e.add5(7, 100, 10, 1000); e.add5(8, 100, 10, 1000); e.add5(9, 70, 10, 700)
    e.add5(10, 100, 10, 1000)                                         # fecha o ensaio
    e.tr.tick(int(time.time() * 1000))
    r = e.tr.get(t["id"])
    f, tm = r["result"]["flow"], r["result"]["timing"]
    assert tm["resolution_ms"] == 10 and tm["res_source"] == "timer" and tm["record_ms"] == 1000
    assert f["time_source"] == "timer" and f["time_eff_ms"] == 4300 and tm["pulse_eff_ms"] == 4300
    assert f["pulses_total"] == 430 and f["volume_l"] == pytest.approx(4.3) and f["flow_l_min"]["mean"] == pytest.approx(4.3 / 4.3 * 60)
    assert tm["eff_ms"] == 5000                                      # o tempo coberto pelos registros continua 5 s; o dos pulsos é 4,3 s


def test_resolucao_exibida_nunca_e_mais_fina_que_a_efetiva():
    e = EnvV5({"trial_duration_ms": 3000, "time_resolution_ms": 1}, fast_ms=10)   # operador pediu 0,001 s; o programa resolve 0,01 s
    for s in range(5):
        e.add5(s, 10, 10, 1000)
    t = e.tr.start("flow", True)
    for s in range(5, 9):
        e.add5(s, 10, 10, 1000)
    e.tr.tick(int(time.time() * 1000))
    tm = e.tr.get(t["id"])["result"]["timing"]
    assert tm["requested_res_ms"] == 1 and tm["resolution_ms"] == 10 and tm["display_res_ms"] == 10
    e2 = Env({"trial_duration_ms": 3000, "time_resolution_ms": 1})                  # programa v4: só o Scan de 1 s
    e2.feed(0, 5); t2 = e2.tr.start("flow", True); e2.feed(5, 10)
    tm2 = e2.tr.get(t2["id"])["result"]["timing"]
    assert tm2["resolution_ms"] == 1000 and tm2["display_res_ms"] == 1000 and tm2["res_source"] == "scan"


def test_sem_carimbos_finos_o_calculo_antigo_continua():
    e = Env({"flow_k_pulses_per_l": 100.0})
    f = e.run(pulses=10)["result"]["flow"]
    assert f["time_source"] == "scan" and f["time_eff_ms"] == 60_000


# ---------------- padrões: API, seleção e cópia congelada
@pytest.fixture
def v5(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v5", fast_ms=10)
    app = boot(tmp_path, monkeypatch, fake, extra={"flow_method": "analog", "trial_duration_ms": 3000})
    yield app, fake, app.app.test_client()
    fake.stop()


PULSE = {"tag": "PAD-VAZ-001", "brand": "Marca A", "model": "Modelo X", "sn": "12345678", "acq": "pulse", "k_value": "1000", "k_unit": "pulsos/L"}
MASS = {"tag": "PAD-VAZ-002", "brand": "Marca B", "model": "Modelo Y", "sn": "22", "acq": "pulse", "k_value": "500", "k_unit": "pulsos/kg"}
ANALOG = {"tag": "PAD-VAZ-003", "brand": "Marca C", "model": "Modelo Z", "sn": "33", "acq": "analog", "q4": "0", "q20": "30", "range_unit": "m³/h", "signal_type": "4–20 mA passivo"}


def test_cadastro_edicao_busca_e_exclusao(v5):
    app, fake, c = v5
    st, p = post(c, "/api/standards", PULSE); assert st == 201 and p["id"] and p["k_value"] == 1000 and p["q4"] is None
    st, m = post(c, "/api/standards", MASS); assert st == 201 and m["k_unit"] == "pulsos/kg"
    st, a = post(c, "/api/standards", ANALOG); assert st == 201 and a["q20"] == 30 and a["range_unit"] == "m³/h" and a["k_value"] is None
    st, j = post(c, "/api/standards", PULSE); assert st == 409                               # TAG repetida
    st, j = post(c, "/api/standards", dict(PULSE, tag="X", k_value="")); assert st == 400     # K obrigatório
    st, j = post(c, "/api/standards", dict(ANALOG, tag="Y", q20="0")); assert st == 400       # 4 mA = 20 mA
    st, j = post(c, "/api/standards", dict(PULSE, tag="Z", k_unit="pulsos/galão")); assert st == 400
    assert [s["tag"] for s in c.get("/api/standards?q=marca b").get_json()["standards"]] == ["PAD-VAZ-002"]
    assert [s["tag"] for s in c.get("/api/standards?q=PAD-VAZ").get_json()["standards"]] == ["PAD-VAZ-001", "PAD-VAZ-002", "PAD-VAZ-003"]
    r = c.put(f"/api/standards/{p['id']}", data=json.dumps(dict(PULSE, k_value="2000")), content_type="application/json")
    assert r.status_code == 200 and r.get_json()["k_value"] == 2000
    assert c.delete(f"/api/standards/{m['id']}", data="{}", content_type="application/json").status_code == 200
    assert c.delete(f"/api/standards/{m['id']}").status_code == 415                            # escrita exige JSON (guarda contra formulário de outro site)
    assert len(c.get("/api/standards").get_json()["standards"]) == 2


def test_selecao_carrega_parametros_e_pede_o_metodo(v5):
    app, fake, c = v5
    cycle(app, fake)                                                                          # o datalogger já informou os canais
    _, p = post(c, "/api/standards", PULSE)
    _, a = post(c, "/api/standards", ANALOG)
    st, j = post(c, f"/api/standards/{p['id']}/select", {})
    assert st == 200 and j["method_error"] is None and j["config"]["standard"]["tag"] == "PAD-VAZ-001"
    assert j["config"]["flow_k_pulses_per_l"] == 1000 and j["config"]["flow_k_unit"] == "pulsos/L" and j["config"]["flow_method"] == "pulse"
    assert j["flow"]["requested"] == "pulse" and j["flow"]["active"] is None                 # só ativo quando o datalogger confirmar
    cycle(app, fake)
    assert c.get("/api/flow").get_json()["active"] == "pulse"
    st, j = post(c, f"/api/standards/{a['id']}/select", {})
    assert st == 200 and j["config"]["cor"] == {"q4": 0.0, "q20": 30.0, "unit": "m³/h"} and j["config"]["flow_method"] == "analog"
    assert j["config"]["flow_k_pulses_per_l"] == 1000                                        # o K anterior fica guardado, mas o método é analógico


def test_selecao_de_pulsos_em_programa_sem_canal_nao_mostra_aquisicao_ativa(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v3")
    app = boot(tmp_path, monkeypatch, fake, extra={"flow_method": "analog"})
    c = app.app.test_client()
    try:
        cycle(app, fake)
        _, p = post(c, "/api/standards", PULSE)
        st, j = post(c, f"/api/standards/{p['id']}/select", {})
        assert st == 200 and j["method_error"] and "pulsos" in j["method_error"].lower()
        assert j["config"]["standard"]["tag"] == "PAD-VAZ-001" and j["config"]["flow_method"] == "analog" and j["flow"]["requested"] == "analog"
    finally:
        fake.stop()


def test_ensaio_congela_copia_do_padrao_e_edicao_posterior_nao_altera(v5):
    app, fake, c = v5
    cycle(app, fake)
    _, p = post(c, "/api/standards", PULSE)
    post(c, f"/api/standards/{p['id']}/select", {})
    cycle(app, fake)
    st, t = post(c, "/api/trials/start", {"kind": "flow"})
    assert st == 200 and t["cfg"]["standard"]["tag"] == "PAD-VAZ-001" and t["cfg"]["k_pulses_per_l"] == 1000 and t["cfg"]["time_res_ms"] == 100
    assert c.put(f"/api/standards/{p['id']}", data=json.dumps(dict(PULSE, tag="PAD-VAZ-009", k_value="5")), content_type="application/json").status_code == 200
    for _ in range(5):
        cycle(app, fake)
    tr = c.get(f"/api/trials/{t['id']}").get_json()
    assert tr["state"] != "running" and tr["cfg"]["standard"]["tag"] == "PAD-VAZ-001" and tr["cfg"]["k_pulses_per_l"] == 1000
    assert tr["result"]["flow"]["standard"]["tag"] == "PAD-VAZ-001" and tr["result"]["flow"]["k_pulses_per_l"] == 1000
    hist = c.get("/api/trials").get_json()["history"]
    assert hist[0]["standard_tag"] == "PAD-VAZ-001"
    assert c.delete(f"/api/standards/{p['id']}", data="{}", content_type="application/json").status_code == 200   # excluir não apaga o histórico
    assert c.get(f"/api/trials/{t['id']}").get_json()["cfg"]["standard"]["tag"] == "PAD-VAZ-001"
    assert c.get("/api/config").get_json()["standard"] is None


def test_v5_entrega_carimbos_e_resolucao_efetiva_na_configuracao(v5):
    app, fake, c = v5
    fake.flow_hz, fake.first_pulse_ms = 50, 240
    cycle(app, fake)
    s = app.state["latest"]
    assert s["flow_t1_ms"] == 240 and s["flow_t2_ms"] == 1000 and s["flow_tres_ms"] == 10
    cfg = c.get("/api/config").get_json()
    assert cfg["timing_res_ms"] == 10 and cfg["time_resolution_ms"] == 100 and cfg["time_resolution_options_ms"] == [100, 10, 1]
    st, j = post(c, "/api/config", {"time_resolution_ms": 1}); assert st == 200 and j["time_resolution_ms"] == 1
    st, j = post(c, "/api/config", {"time_resolution_ms": 50}); assert st == 400


def test_k_em_pulsos_por_kg_na_configuracao_segue_a_densidade(v5):
    app, fake, c = v5
    st, j = post(c, "/api/config", {"flow_k": {"value": "500", "unit": "pulsos/kg"}, "density_g_cm3": ""})
    assert st == 200 and j["flow_k_unit"] == "pulsos/kg" and j["flow_k_value"] == 500 and j["flow_k_pulses_per_l"] is None and j["flow_k_mass"]
    st, j = post(c, "/api/config", {"density_g_cm3": "0,9982"})
    assert st == 200 and j["flow_k_pulses_per_l"] == pytest.approx(499.1) and j["flow_k_value"] == 500
