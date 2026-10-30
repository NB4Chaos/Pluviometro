"""Servidor (app.py) em processo: API do medidor de vazão, método analógico/pulsos, configuração parcial, gravação sem regressão e
instância única. Emulador com dados fictícios; pasta de dados temporária (nada do projeto é tocado)."""
import importlib, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from tests.fake_programa_atual import Fake


def boot(tmp_path, monkeypatch, fake, profile="programa_vazao", cfg=None):
    """Importa app.py apontando para o emulador, com pasta de dados temporária; roda UM ciclo de aquisição."""
    base = {"comm": {"protocol": "http", "address": f"127.0.0.1:{fake.port}", "user": "dash", "profile": profile},
            "density_g_cm3": 1.0, "cor": {"q4": 0.0, "q20": 100.0, "unit": "L/min"}}
    json.dump(base | (cfg or {}), open(tmp_path / "config.json", "w"))
    monkeypatch.setenv("ELUS_DATA_DIR", str(tmp_path)); monkeypatch.setenv("DATALOGGER_PASSWORD", "segredo")
    for k in ("DATALOGGER_HOST", "DATALOGGER_USER", "CR1000X_PROFILE", "DASHBOARD_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    app.poll_once()
    return app, app.app.test_client()


@pytest.fixture
def v4():
    f = Fake(prefill=20, tip_every=10, schema="v4")
    yield f
    f.stop()


@pytest.fixture
def v3():
    f = Fake(prefill=20, tip_every=10, schema="v3")
    yield f
    f.stop()


def test_metodo_padrao_analogico_calcula_pela_faixa_e_expoe_os_canais(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    f = c.get("/api/flow").get_json()
    assert f["method"] == "analog" and f["active"] == "analog" and f["channels"] == {"analog": True, "pulse": True}
    assert f["state"] == "ok" and f["value_l_min"] == pytest.approx(50.0)      # 12 mA na faixa 0–100 L/min
    assert f["raw"]["ma"] == pytest.approx(12.0) and f["raw"]["pulses"] == 100 and f["raw"]["pulses_total"] == v4.pulses_total
    s = c.get("/api/summary").get_json()["latest"]
    assert s["flow_state"] == "ok" and s["flow_lmin"] == pytest.approx(50.0) and s["flow_pulses"] == 100


def test_trocar_para_pulsos_exige_k_e_depois_calcula_pela_contagem_bruta(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    r = c.post("/api/flow/method", json={"method": "pulse"})
    assert r.status_code == 200 and r.get_json()["method"] == "pulse"
    f = c.get("/api/flow").get_json()
    assert f["state"] == "unconfigured" and f["value_l_min"] is None and f["active"] is None     # sem K nada é inventado
    r = c.post("/api/config", json={"flow_k_value": 100, "flow_k_unit": "pulsos/L"})
    assert r.status_code == 200 and r.get_json()["flow_k_pulses_per_l"] == 100.0
    f = c.get("/api/flow").get_json()
    assert f["state"] == "ok" and f["active"] == "pulse" and f["value_l_min"] == pytest.approx(60.0)   # 100 pulsos/s ÷ 100 pulsos/L × 60
    assert json.load(open(tmp_path / "config.json"))["flow_method"] == "pulse"                        # persistido


def test_k_em_outra_unidade_e_normalizado(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    r = c.post("/api/config", json={"flow_k_value": 10, "flow_k_unit": "mL/pulso"})
    assert r.status_code == 200 and r.get_json()["flow_k_pulses_per_l"] == pytest.approx(100.0) and r.get_json()["flow_k_unit"] == "mL/pulso"
    assert c.post("/api/config", json={"flow_k_value": -1, "flow_k_unit": "pulsos/L"}).status_code == 400
    assert c.post("/api/config", json={"flow_k_value": 1, "flow_k_unit": "pulsos/galão"}).status_code == 400


def test_programa_v3_nao_tem_canal_de_pulsos(tmp_path, monkeypatch, v3):
    app, c = boot(tmp_path, monkeypatch, v3, cfg={"flow_method": "pulse", "flow_k_value": 100, "flow_k_unit": "pulsos/L"})
    f = c.get("/api/flow").get_json()
    assert f["channels"] == {"analog": True, "pulse": False} and f["state"] == "unavailable" and f["value_l_min"] is None
    r = c.post("/api/flow/method", json={"method": "pulse"})
    assert r.status_code == 400 and "canal" in r.get_json()["error"].lower()
    assert c.post("/api/flow/method", json={"method": "analog"}).status_code == 200


def test_troca_de_metodo_recusada_durante_ensaio(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    r = c.post("/api/trials/start", json={"kind": "flow"})
    assert r.status_code == 200, r.get_json()
    r = c.post("/api/flow/method", json={"method": "pulse"})
    assert r.status_code == 409
    c.post("/api/trials/stop", json={})
    assert c.post("/api/flow/method", json={"method": "pulse"}).status_code == 200


def test_metodo_invalido_e_recusado(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    assert c.post("/api/flow/method", json={"method": "wifi"}).status_code == 400


def test_configuracao_parcial_preserva_o_que_nao_foi_enviado(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4, cfg={"mass_unit": "kg", "tip_resolution_mm": 0.25, "trial_duration_s": 90})
    r = c.post("/api/config", json={"flow_ma_tol": 0.05})
    d = r.get_json()
    assert r.status_code == 200 and d["flow_ma_tol"] == 0.05 and d["mass_unit"] == "kg" and d["tip_resolution_mm"] == 0.25
    assert d["trial_duration_ms"] == 90000 and d["trial_duration_s"] == 90          # duração antiga em s migrada para ms


def test_duracao_do_ensaio_em_ms_respeita_a_resolucao_do_scan(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    assert c.post("/api/config", json={"trial_duration_ms": 1500, "trial_duration_unit": "ms"}).status_code == 200
    r = c.post("/api/config", json={"trial_duration_ms": 500})
    assert r.status_code == 400 and "1000 ms" in r.get_json()["error"]
    f = c.get("/api/flow").get_json()
    assert f["scan_ms"] == 1000


def test_regravar_horario_existente_so_completa_campos_vazios(tmp_path, monkeypatch, v4):
    from datalogger import Reading
    app, c = boot(tmp_path, monkeypatch, v4)
    T = 1_800_000_000_000
    app.store_batch([Reading(mass_g=10.0, temp_c=None, temp_status="no_comm", ts=T)], T)
    app.store_batch([Reading(mass_g=99.0, temp_c=21.5, temp_status="ok", ts=T)], T)            # releitura: só completa a temperatura
    row = app.q("SELECT mass_g, temp_c, temp_status FROM samples WHERE ts=?", (T,))[0]
    assert row == (10.0, 21.5, "ok")
    app.store_batch([Reading(mass_g=None, mass_status="no_comm", temp_c=None, temp_status="no_comm", ts=T)], T)   # releitura pior não apaga
    assert app.q("SELECT mass_g, temp_c, temp_status FROM samples WHERE ts=?", (T,))[0] == (10.0, 21.5, "ok")


def test_instancia_unica(tmp_path, monkeypatch, v4):
    app, c = boot(tmp_path, monkeypatch, v4)
    h1 = app.single_instance(str(tmp_path / "servidor.lock"))
    assert h1 is not None
    assert app.single_instance(str(tmp_path / "servidor.lock")) is None       # segunda cópia não sobe
    app.release_instance(h1)
    h3 = app.single_instance(str(tmp_path / "servidor.lock"))
    assert h3 is not None
    app.release_instance(h3)


def test_csv_bruto_do_ensaio_traz_pulsos_e_vazao_pelo_metodo_congelado(tmp_path, monkeypatch, v4):
    """Regressão (30/10): /api/trials/<id>/raw.csv respondia 500 (SCOLS_LIST/flow_of_row acessados na instância, não no módulo)."""
    app, c = boot(tmp_path, monkeypatch, v4, cfg={"flow_method": "pulse", "flow_k_value": 100, "flow_k_unit": "pulsos/L", "trial_duration_ms": 2000})
    assert c.post("/api/trials/start", json={"kind": "flow"}).status_code == 200
    for _ in range(4):
        v4.tick(sleep=False); app.poll_once()
    t = c.get("/api/trials").get_json()
    tid = (t["last"] or t["running"])["id"]
    if t["running"]:
        c.post("/api/trials/stop", json={})
    r = c.get(f"/api/trials/{tid}/raw.csv")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "Pulsos (contagem no Scan)" in body and "método pulse" in body
    lines = [l for l in body.splitlines() if l.strip()]
    assert len(lines) >= 2 and lines[1].count(";") == lines[0].count(";")
    assert c.get(f"/api/trials/{tid}/tips.csv").status_code == 200
