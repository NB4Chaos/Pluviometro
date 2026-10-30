"""Servidor (app.py) + emulador: método do medidor (solicitado × confirmado), bloqueio durante ensaio, persistência,
configuração parcial, gravação que nunca piora o histórico e instância única. Dados FICTÍCIOS; pasta de dados temporária."""
import importlib, json, os, sys, time
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from datalogger import Reading
from tests.fake_programa_atual import Fake

CFG = {"tip_resolution_mm": 0.2, "density_g_cm3": 1.0, "catch_area_cm2": 100.0, "flow_k_pulses_per_l": 1000.0,
       "cor": {"q4": 0.0, "q20": 100.0, "unit": "L/min"}, "trial_duration_s": 10}


def boot(tmp_path, monkeypatch, fake, extra=None, write=True):
    if write:
        cfg = dict(CFG, comm={"protocol": "http", "address": f"127.0.0.1:{fake.port}", "user": "dash", "profile": "programa_vazao"}, **(extra or {}))
        json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"))
    monkeypatch.setenv("ELUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATALOGGER_PASSWORD", "segredo")
    for k in ("DATALOGGER_HOST", "DATALOGGER_USER", "CR1000X_PROFILE", "DASHBOARD_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def cycle(app, fake=None, ticks=1):
    """Um ciclo real de aquisição (_acquire_once), sem esperar o relógio."""
    for _ in range(ticks if fake else 0):
        fake.tick(sleep=False)
    p = app.Pacer(1.0)
    app._acquire_once(time.time(), time.time(), p)
    return app.state["latest"]


def post(c, url, body):
    r = c.post(url, data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()


@pytest.fixture
def v4(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v4")
    app = boot(tmp_path, monkeypatch, fake)
    yield app, fake, app.app.test_client()
    fake.stop()


def test_metodo_padrao_analogico_confirmado_pelo_dado_e_os_dois_canais_gravados(v4):
    app, fake, c = v4
    s = cycle(app)
    f = s["flow"]
    assert f["method"] == "analog" and f["active"] == "analog" and f["confirmed"] and f["state"] == "ok"
    assert f["lmin"] == pytest.approx(50.0) and f["has"] == ["analog", "pulse"]            # 12 mA na faixa 0–100 L/min
    assert s["cor_ma"] == pytest.approx(12.0) and s["flow_pulses"] == 100 and s["flow_hz"] == pytest.approx(100.0)
    assert f["channels"]["pulse"]["lmin"] == pytest.approx(6.0)                           # o outro canal também é avaliado
    assert f["crosscheck"]["diff_pct"] == pytest.approx(-88.0)


def test_troca_para_pulso_fica_pendente_ate_o_proximo_dado_do_datalogger(v4):
    app, fake, c = v4
    cycle(app)
    st, j = post(c, "/api/flow/method", {"method": "pulse"})
    assert st == 200 and j["requested"] == "pulse" and j["active"] is None and not j["confirmed"]
    assert json.load(open(os.path.join(app.DATA, "config.json"), encoding="utf-8"))["flow_method"] == "pulse"
    s = cycle(app, fake)
    assert s["flow"]["method"] == "pulse" and s["flow"]["active"] == "pulse" and s["flow"]["confirmed"]
    assert s["flow"]["lmin"] == pytest.approx(6.0) and s["flow_mode"] == "pulse"           # 100 Hz ÷ 1000 pulsos/L × 60
    assert c.get("/api/flow").get_json()["confirmed_at"] is not None


def test_pulso_indisponivel_no_programa_em_uso_v3_e_recusado(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v3")
    try:
        app = boot(tmp_path, monkeypatch, fake)
        c = app.app.test_client()
        cycle(app)
        st, j = post(c, "/api/flow/method", {"method": "pulse"})
        assert st == 409 and "P2" in j["error"] and j["flow"]["requested"] == "analog" and j["flow"]["has"] == ["analog"]
        assert app.load_cfg()["flow_method"] == "analog"
    finally:
        fake.stop()


def test_metodo_invalido_e_recusado(v4):
    app, fake, c = v4
    cycle(app)
    assert post(c, "/api/flow/method", {"method": "turbina"})[0] == 400


def test_troca_bloqueada_durante_ensaio_e_liberada_depois(v4):
    app, fake, c = v4
    cycle(app)
    assert post(c, "/api/trials/start", {"kind": "pluv"})[0] == 200
    st, j = post(c, "/api/flow/method", {"method": "pulse"})
    assert st == 409 and "ensaio" in j["error"] and j["flow"]["locked"]
    assert post(c, "/api/config", {"flow_method": "pulse"})[0] == 400                      # o caminho da configuração também respeita
    assert post(c, "/api/trials/stop", {})[0] == 200
    assert post(c, "/api/flow/method", {"method": "pulse"})[0] == 200


def test_ensaio_de_vazao_nao_inicia_com_metodo_ainda_nao_confirmado(v4):
    app, fake, c = v4
    cycle(app)
    post(c, "/api/flow/method", {"method": "pulse"})
    st, j = post(c, "/api/trials/start", {"kind": "flow"})
    assert st == 409 and "confirmado" in j["error"]
    cycle(app, fake)
    st, t = post(c, "/api/trials/start", {"kind": "flow"})
    assert st == 200 and t["cfg"]["flow_method"] == "pulse" and t["cfg"]["ma_tol"] == pytest.approx(0.02)


def test_metodo_persiste_depois_de_reiniciar_o_servidor(tmp_path, monkeypatch):
    fake = Fake(prefill=20, schema="v4")
    try:
        app = boot(tmp_path, monkeypatch, fake)
        cycle(app)
        post(app.app.test_client(), "/api/flow/method", {"method": "pulse"})
        app2 = boot(tmp_path, monkeypatch, fake, write=False)                              # mesmo config.json
        assert app2.FLOW["requested"] == "pulse" and app2.FLOW["active"] is None
        assert cycle(app2, fake)["flow"]["active"] == "pulse"
    finally:
        fake.stop()


def test_configuracao_parcial_preserva_o_resto_e_valida(v4):
    app, fake, c = v4
    before = dict(app.load_cfg())
    st, j = post(c, "/api/config", {"flow_k": {"value": "2,5", "unit": "L/pulso"}})
    assert st == 200 and j["flow_k_pulses_per_l"] == pytest.approx(0.4) and j["flow_k_unit"] == "L/pulso"
    assert j["flow_k_value"] == pytest.approx(2.5)
    for k in ("default_range_s", "temp_unit", "flow_unit", "mass_unit", "cor", "tip_resolution_mm", "trial_duration_s"):
        assert j[k] == before[k], k
    assert post(c, "/api/config", {"flow_k": {"value": "0", "unit": "pulsos/L"}})[0] == 400
    assert post(c, "/api/config", {"flow_k": {"value": "1", "unit": "pulsos/galão"}})[0] == 400
    assert post(c, "/api/config", {"flow_ma_tol": 0.5})[0] == 400
    assert post(c, "/api/config", {"cor": {"q20": 50}})[1]["cor"] == {"q4": 0.0, "q20": 50.0, "unit": "L/min"}
    st, j = post(c, "/api/config", {"flow_k": {"value": "", "unit": "pulsos/m³"}})
    assert st == 200 and j["flow_k_pulses_per_l"] is None                                  # "" apaga: K nunca presumido
    saved = json.load(open(os.path.join(app.DATA, "config.json"), encoding="utf-8"))
    assert saved["flow_k_pulses_per_l"] is None and saved["flow_k_unit"] == "pulsos/m³"


def test_releitura_nunca_piora_linha_ja_gravada(v4):
    app, fake, c = v4
    T = 1_800_000_000_000
    good = Reading(mass_g=10.0, temp_c=21.5, mass_status="ok", temp_status="ok", cor_ma=12.0, cor_status="ok", ts=T,
                   flow_pulses=100.0, flow_dt_ms=1000, flow_has=("analog", "pulse"))
    worse = Reading(mass_g=10.0, temp_c=None, mass_status="ok", temp_status="no_comm", cor_ma=None, cor_status="no_comm", ts=T,
                    flow_has=("analog", "pulse"))
    app.store_batch([good], T)
    app.store_batch([worse], T)                                                            # releitura com junção vazia
    row = dict(zip(app.COLS, app.q(f"SELECT {','.join(app.COLS)} FROM samples WHERE ts=?", (T,))[0]))
    assert row["temp_c"] == 21.5 and row["temp_status"] == "ok" and row["cor_ma"] == 12.0 and row["cor_status"] == "ok"
    T2 = T + 1000
    app.store_batch([replace(worse, ts=T2)], T2)
    app.store_batch([replace(good, ts=T2)], T2)                                            # e completa o que faltava
    row = dict(zip(app.COLS, app.q(f"SELECT {','.join(app.COLS)} FROM samples WHERE ts=?", (T2,))[0]))
    assert row["temp_status"] == "ok" and row["cor_status"] == "ok" and app.diag["merged"] >= 1


def test_corrente_fora_da_faixa_fica_gravada_bruta_com_estado_proprio(v4):
    app, fake, c = v4
    cycle(app)
    fake.flow_ma = 2.0                                                                     # alarme do transmissor / laço
    s = cycle(app, fake)
    assert s["cor_ma"] == pytest.approx(2.0) and s["cor_status"] == "out_of_range" and s["flow"]["state"] == "fault"
    h = c.get("/api/history", query_string={"from": s["ts"], "to": s["ts"] + 1}).get_json()["rows"][0]
    assert h["flow_state"] == "fault" and h["flow_lmin"] is None and h["cor_ma"] == pytest.approx(2.0)


def test_comparacao_entre_canais_aponta_pulsos_ausentes(v4):
    app, fake, c = v4
    cycle(app)
    fake.flow_hz = 0.0                                                                     # corrente diz 50 L/min, P2 sem pulsos
    s = None
    for _ in range(app.XCHECK_STREAK):
        s = cycle(app, fake)
    assert s["flow"]["crosscheck"]["suspect"] == "no_pulses" and s["flow"]["state"] == "ok"   # diagnóstico; a leitura não muda


def test_grafico_converte_cada_linha_exatamente_como_flow_value(v4):
    """Otimização de 28/10/2026: /api/series reaproveita conversões repetidas, mas cada linha continua valendo exatamente
    o que flow_value dá (valor repetido, canal que o método não usa, zero com e sem sinal, ausente, fora da faixa)."""
    app, fake, c = v4
    base = 1_600_000_000_000
    casos = [("analog", 12.0, None, "ok"), ("analog", 12.0, None, "ok"), ("analog", 12.0, 950.0, "ok"), ("analog", 3.0, None, "out_of_range"),
             ("analog", 20.01, None, "ok"), ("analog", None, None, "no_comm"), (None, 8.0, None, "ok"), ("pulse", None, 950.0, "ok"),
             ("pulse", 12.0, 950.0, "ok"), ("pulse", None, 0.0, "ok"), ("pulse", None, -0.0, "ok"), ("pulse", None, None, "ok"),
             ("pulse", 3.0, 10.0, "out_of_range"), ("analog", 0.0, None, "ok"), ("analog", -0.0, None, "ok"), (None, None, None, None)]
    with app.lock:
        for i, (mode, ma, hz, st) in enumerate(casos):
            row = dict.fromkeys(app.COLS)
            row.update(ts=base + i * 1000, cor_ma=ma, cor_status=st, flow_mode=mode, flow_hz=hz)
            app.db.execute(app.INSERT_SQL, tuple(row[k] for k in app.COLS))
        app.db.commit()
    s = c.get(f"/api/series?from={base}&to={base + len(casos) * 1000}").get_json()
    cfg = app.load_cfg()
    esperado = [None if v is None else round(sum([v]) / 1, 3) for v in (app.flow_value(m, ma, hz, st, cfg)[0] for m, ma, hz, st in casos)]
    assert json.dumps(s["flow"]) == json.dumps(esperado)


def test_uma_segunda_copia_do_servidor_nao_sobe(v4):
    app, fake, c = v4
    lock = app.single_instance()
    try:
        with pytest.raises(SystemExit):
            app.single_instance()
    finally:
        lock.close()
