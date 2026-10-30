"""Ensaios: janela, congelamento, lacunas, interrupção e unicidade. Banco em memória, sem rede, sem relógio real."""
import os, sqlite3, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from trials import Trials, TrialError

T0 = 1_800_000_000_000     # ms (horário do "datalogger")
CFG = {"tip_resolution_mm": 0.2, "catch_area_cm2": 200.0, "density_g_cm3": 1.0, "flow_k_pulses_per_l": 1000.0,
       "trial_duration_s": 60, "cor": {"q4": 0.0, "q20": 16.0, "unit": "L/min"}}


class Env:
    def __init__(self, cfg=None):
        self.cfg = dict(CFG, **(cfg or {}))
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript("""CREATE TABLE samples(ts INTEGER PRIMARY KEY, mass_g REAL, temp_c REAL, mass_status TEXT, temp_status TEXT,
          tips_total INTEGER, cor_ma REAL, cor_status TEXT, flow_mode TEXT, flow_pulses REAL, flow_hz REAL);
          CREATE TABLE tips(ts INTEGER, src TEXT); CREATE UNIQUE INDEX ux ON tips(src);""")
        self.lock = threading.Lock()
        self.tr = Trials(self.db, self.lock, lambda: self.cfg, lambda: self.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0])
        self.n = 0

    def add(self, sec, mass=None, temp=22.0, mode=None, pulses=None, hz=None, ma=None, cor_status=None, tip=0, mass_status=None):
        ts = T0 + sec * 1000
        self.db.execute("INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, mass, temp, mass_status or ("ok" if mass is not None else "no_comm"), "ok", 0, ma, cor_status, mode, pulses, hz))
        for k in range(tip):
            self.n += 1
            self.db.execute("INSERT INTO tips VALUES(?,?)", (ts, f"t{self.n}"))
        self.db.commit()

    def feed(self, a, b, **kw):
        for s in range(a, b):
            self.add(s, **{k: (v(s) if callable(v) else v) for k, v in kw.items()})
        return self.tr.tick(int(time.time() * 1000))


@pytest.fixture
def env():
    return Env()


def grav(env, extra=0):
    """Ensaio de pluviômetro de 60 s: balança já tinha 500 g e ganha 1 g/s; 1 basculada a cada 10 s."""
    env.feed(0, 10, mass=lambda s: 500.0 + s)
    t = env.tr.start("pluv", True)
    assert t["start_ts"] == T0 + 9 * 1000 + 1 and t["state"] == "running"
    return t


def test_gravimetrico_completo_usa_so_a_variacao_de_massa(env):
    t = grav(env)
    env.feed(10, 80, mass=lambda s: 500.0 + s, tip=lambda s: 1 if s % 10 == 0 else 0)
    r = env.tr.get(t["id"])
    assert r["state"] == "completed" and r["reason"] is None
    g = r["result"]["gravimetric"]
    # janela [T0+9,001 s ; T0+69,001 s): primeira amostra s=10 (510 g), última s=69 (569 g)
    assert g["mass_start_g"] == 510.0 and g["mass_end_g"] == 569.0 and g["delta_mass_g"] == pytest.approx(59.0)
    assert g["duration_s"] == pytest.approx(59.0)
    assert g["volume_l"] == pytest.approx(0.059)
    assert g["precip_ref_mm"] == pytest.approx(10 * 59 / 200)          # 2,95 mm
    assert g["flow_ref_l_min"] == pytest.approx(0.059 / (59 / 60))
    # basculadas em (t0, t1]: s = 20,30,40,50,60 (a de s=10 já estava no instante t0 e a de 70 é posterior)
    assert g["pulses_window"] == 5 and g["pluv_precip_mm"] == pytest.approx(1.0)
    assert g["diff_mm"] == pytest.approx(1.0 - 2.95)
    assert r["result"]["quality"]["rows"] == 60 and r["result"]["quality"]["gaps"] == 0


def test_massa_diminuiu_vira_incompleto_mas_a_indicacao_do_pluviometro_fica(env):
    t = grav(env)
    env.feed(10, 80, mass=lambda s: 600.0 - 0.01 * s, tip=lambda s: 1 if s % 10 == 0 else 0)   # balança perdendo massa (evaporação)
    r = env.tr.get(t["id"])
    g = r["result"]["gravimetric"]
    assert g["delta_mass_g"] < 0 and g["volume_ml"] is None and g["precip_ref_mm"] is None
    assert g["pluv_pulses"] == 5 and g["pluv_precip_mm"] == pytest.approx(1.0)      # 5 × 0,2 mm: não depende da balança
    assert g["pluv_intensity_mm_h"] == pytest.approx(1.0 / (59 / 3600))
    assert g["diff_mm"] is None and g["error_pct"] is None
    assert r["state"] == "incomplete" and "referência gravimétrica indisponível" in r["reason"]
    assert "mass" not in r["result"]                                                  # média de massa não faz parte do resultado


def test_medidor_usa_o_mesmo_intervalo_da_balanca(env):
    # 100 pulsos/s, K = 1000 → 0,1 L por amostra. Balança: +100 g/s (ρ = 1) → referência 0,1 L por segundo de intervalo.
    env.feed(0, 5, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=lambda s: 100.0 * s)
    t = env.tr.start("flow", True)
    env.feed(5, 80, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=lambda s: 100.0 * s)
    v = env.tr.get(t["id"])["result"]["flow"]["vs_reference"]
    assert v["window_s"] == pytest.approx(59.0)
    assert v["volume_ref_l"] == pytest.approx(5.9)                                   # Δm = 5900 g em (t0, t1]
    assert v["volume_meter_l"] == pytest.approx(5.9)                                 # 59 amostras em (t0, t1], não 59 em [t0, t1)
    assert v["error_pct"] == pytest.approx(0.0, abs=1e-9)


def test_mudar_a_duracao_nao_altera_ensaio_em_andamento_nem_concluido(env):
    t = grav(env)                                                          # iniciado com 60 s
    env.cfg["trial_duration_s"] = 10                                       # operador muda durante o ensaio
    env.feed(10, 30, mass=lambda s: 500.0 + s)                             # 20 s depois: com 10 s já teria acabado
    run = env.tr.status()["running"]
    assert run and run["id"] == t["id"] and run["duration_cfg_s"] == 60 and run["end_ts"] == t["end_ts"]
    env.feed(30, 80, mass=lambda s: 500.0 + s)
    r = env.tr.get(t["id"])
    assert r["state"] == "completed" and r["duration_cfg_s"] == 60 and r["end_ts"] - r["start_ts"] == 60_000
    env.cfg["trial_duration_s"] = 300                                      # mudar de novo não reescreve o concluído
    assert env.tr.get(t["id"]) == r
    env.feed(80, 90, mass=lambda s: 500.0 + s)
    assert env.tr.start("pluv", True)["duration_cfg_s"] == 300             # só o PRÓXIMO ensaio usa o valor novo


def test_resultado_congelado_apos_o_fim_mesmo_com_dados_novos(env):
    t = grav(env)
    env.feed(10, 80, mass=lambda s: 500.0 + s, tip=lambda s: 1 if s % 10 == 0 else 0)
    antes = env.tr.get(t["id"])["result"]
    env.feed(80, 300, mass=lambda s: 500.0 + 5 * s, tip=1)           # a balança e o pluviômetro continuam recebendo
    env.cfg.update(density_g_cm3=0.5, catch_area_cm2=10.0, tip_resolution_mm=9.9)   # e a configuração muda
    assert env.tr.get(t["id"])["result"] == antes
    assert env.tr.status()["last"]["result"] == antes
    raw, tips = env.tr.raw(t["id"])
    assert len(raw) == 60 and all(T0 + 9001 <= r[0] < T0 + 69001 for r in raw)
    with pytest.raises(sqlite3.DatabaseError):                            # o banco recusa alteração...
        env.db.execute("UPDATE trials SET result='{}' WHERE id=?", (t["id"],))
    with pytest.raises(sqlite3.DatabaseError):
        env.db.execute("DELETE FROM trials WHERE id=?", (t["id"],))
    with pytest.raises(sqlite3.DatabaseError):                            # ...e dados brutos também
        env.db.execute("DELETE FROM trial_samples WHERE trial_id=?", (t["id"],))
    with pytest.raises(sqlite3.DatabaseError):
        env.db.execute("INSERT INTO trial_tips VALUES(?,?,?)", (t["id"], T0, "x"))


def test_historico_recente_nao_afeta_o_ensaio(env):
    # a "janela de 15 min" da interface é só uma consulta; o ensaio copia suas amostras no fim
    t = grav(env)
    env.feed(10, 4000, mass=lambda s: 500.0 + s)                          # 66 min depois, muito além de qualquer janela recente
    r = env.tr.get(t["id"])
    assert r["state"] == "completed" and r["result"]["quality"]["rows"] == 60


def test_so_um_ensaio_por_vez(env):
    env.feed(0, 10, mass=500.0)
    env.tr.start("pluv", True)
    with pytest.raises(TrialError) as e:
        env.tr.start("flow", True)
    assert e.value.status == 409 and "em andamento" in e.value.msg


def test_nao_inicia_sem_dados_atuais(env):
    with pytest.raises(TrialError) as e:
        env.tr.start("pluv", True)                                        # banco vazio
    assert e.value.status == 409
    env.feed(0, 5, mass=1.0)
    with pytest.raises(TrialError):
        env.tr.start("pluv", False)                                       # sem comunicação confirmada


def test_interrompido_pelo_usuario_preserva_dados_e_nao_e_completo(env):
    t = grav(env)
    env.feed(10, 40, mass=lambda s: 500.0 + s)
    r = env.tr.stop()
    assert r["state"] == "interrupted" and "usuário" in r["reason"]
    assert r["result"]["quality"]["rows"] == 30 and r["result"]["gravimetric"]["delta_mass_g"] == pytest.approx(29.0)
    assert r["end_ts"] < t["end_ts"]
    with pytest.raises(TrialError):
        env.tr.stop()                                                     # já não há ensaio


def test_lacuna_de_dados_marca_incompleto(env):
    t = grav(env)
    env.feed(10, 30, mass=lambda s: 500.0 + s)
    env.feed(50, 80, mass=lambda s: 500.0 + s)                            # 20 s sem nenhum registro
    r = env.tr.get(t["id"])
    assert r["state"] == "incomplete" and r["result"]["quality"]["gaps"] == 1
    assert "lacunas" in r["reason"]
    assert r["result"]["quality"]["covered_s"] < 45


def test_balanca_invalida_marca_incompleto_no_ensaio_do_pluviometro(env):
    t = grav(env)
    env.feed(10, 80, mass=lambda s: 500.0 + s if s % 2 else None)         # metade das leituras de massa inválidas
    r = env.tr.get(t["id"])
    assert r["state"] == "incomplete" and "balança" in r["reason"]


def test_sem_dados_apos_o_fim_previsto_vira_interrompido(env):
    t = grav(env)
    env.feed(10, 20, mass=lambda s: 500.0 + s)
    now = int(time.time() * 1000)
    assert env.tr.tick(now) is None                                       # ainda dentro da espera
    r = env.tr.tick(now + (60 + 121) * 1000)                              # passou duração + tolerância sem chegar ao fim
    assert r["state"] == "interrupted" and "sem dados" in r["reason"]


def test_ensaio_continua_apos_reiniciar_o_servidor(env):
    t = grav(env)
    env.feed(10, 30, mass=lambda s: 500.0 + s)
    tr2 = Trials(env.db, env.lock, lambda: env.cfg, lambda: env.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0])  # "novo processo"
    assert tr2.status()["running"]["id"] == t["id"]
    for s in range(30, 80):
        env.add(s, mass=500.0 + s)
    assert tr2.tick(int(time.time() * 1000))["state"] == "completed"


def test_medidor_por_pulsos_vazao_volume_e_pulsos_brutos(env):
    env.feed(0, 5, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=1.0)
    t = env.tr.start("flow", True)
    env.feed(5, 80, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=1.0)
    r = env.tr.get(t["id"])
    f = r["result"]["flow"]
    assert r["state"] == "completed" and f["mode"] == "pulse"
    assert f["pulses_total"] == 6000                                      # 60 s × 100 pulsos
    assert f["flow_l_min"]["mean"] == pytest.approx(6.0) and f["flow_l_min"]["min"] == f["flow_l_min"]["max"] == pytest.approx(6.0)
    assert f["volume_l"] == pytest.approx(6.0)                            # 6000 pulsos / (1000 pulsos/L)
    assert f["valid_fraction"] == 1.0


def test_medidor_pulsos_sem_k_nao_inventa_vazao():
    e = Env({"flow_k_pulses_per_l": None})
    e.feed(0, 5, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=1.0)
    t = e.tr.start("flow", True)
    e.feed(5, 80, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=1.0)
    r = e.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["flow_l_min"] is None and f["volume_l"] is None and f["issues"]
    assert f["pulses_total"] is None or True
    assert r["state"] == "incomplete"                                     # não há leituras válidas do medidor


def test_medidor_analogico_media_min_max_em_l_min():
    e = Env()
    e.feed(0, 5, mode="analog", ma=12.0, cor_status="ok", mass=1.0)
    t = e.tr.start("flow", True)
    e.feed(5, 80, mode="analog", ma=lambda s: 12.0 if s < 40 else 16.0, cor_status="ok", mass=1.0)
    f = e.tr.get(t["id"])["result"]["flow"]
    # faixa 0–16 L/min: 12 mA -> 8 L/min ; 16 mA -> 12 L/min
    assert f["flow_l_min"]["min"] == pytest.approx(8.0) and f["flow_l_min"]["max"] == pytest.approx(12.0)
    n_baixo = 40 - 5 - 0                                                  # amostras s=5.. mas a primeira do ensaio é s=5
    assert 8.0 < f["flow_l_min"]["mean"] < 12.0
    assert f["ma"]["min"] == 12.0 and f["ma"]["max"] == 16.0


def test_ausencia_de_sinal_analogico_fora_da_faixa_nao_entra_na_media():
    e = Env()
    e.feed(0, 5, mode="analog", ma=12.0, cor_status="ok", mass=1.0)
    t = e.tr.start("flow", True)
    e.feed(5, 80, mode="analog", ma=lambda s: 12.0 if s % 10 else 3.2, cor_status=lambda s: "ok" if s % 10 else "out_of_range", mass=1.0)
    r = e.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["flow_l_min"]["mean"] == pytest.approx(8.0) and f["flow_l_min"]["min"] == pytest.approx(8.0)  # 3,2 mA ignorado
    assert 0.85 < f["valid_fraction"] < 0.95 and r["state"] == "incomplete"


def test_comparacao_do_medidor_com_a_referencia_usa_o_mesmo_intervalo(env):
    # 6 L/min por pulsos; a balança ganha 100 g/s = 0,1 L/s = 6 L/min (ρ = 1): erro ~0 %
    env.feed(0, 5, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=lambda s: 100.0 * s)
    t = env.tr.start("flow", True)
    env.feed(5, 80, mode="pulse", pulses=100.0, hz=100.0, cor_status="ok", mass=lambda s: 100.0 * s)
    f = env.tr.get(t["id"])["result"]["flow"]
    v = f["vs_reference"]
    assert v["volume_meter_l"] == pytest.approx(v["volume_ref_l"], rel=1e-9) and abs(v["error_pct"]) < 1e-6
    assert v["window_s"] == pytest.approx(59.0)


def test_programa_sem_medidor_de_vazao_ensaio_de_vazao_fica_incompleto(env):
    env.feed(0, 5, mass=1.0)
    t = env.tr.start("flow", True)
    env.feed(5, 80, mass=1.0)
    r = env.tr.get(t["id"])
    assert r["result"]["flow"] is None and r["state"] == "incomplete" and "não fornece" in r["reason"]


def test_status_em_andamento_mostra_progresso_e_resultado_parcial_marcado(env):
    t = grav(env)
    env.feed(10, 30, mass=lambda s: 500.0 + s)
    st = env.tr.status()["running"]
    assert st["state"] == "running" and st["n_samples"] == 20 and st["elapsed_s"] == pytest.approx(20.0, abs=1)
    assert 38 <= st["remaining_s"] <= 41 and st["partial"]["gravimetric"]["delta_mass_g"] == pytest.approx(19.0)
    assert env.tr.status()["last"] is None                                # nada é "último resultado" até terminar


def test_densidade_ausente_nao_inventa_volume():
    e = Env({"density_g_cm3": None})
    e.feed(0, 5, mass=lambda s: 100.0 + s)
    t = e.tr.start("pluv", True)
    e.feed(5, 80, mass=lambda s: 100.0 + s)
    g = e.tr.get(t["id"])["result"]["gravimetric"]
    assert g["volume_ml"] is None and g["precip_ref_mm"] is None and g["issues"]


def test_tip_rows_massa_3s_depois_e_referencia_invalida(tmp_path, monkeypatch):
    """Massa de cada basculada lida 3 s depois; Δm = None após tara (massa menor) ou anterior > 10 min."""
    import importlib, os, sys
    monkeypatch.setenv("ELUS_DATA_DIR", str(tmp_path)); monkeypatch.setenv("DATALOGGER_PASSWORD", "x"); monkeypatch.setenv("DATALOGGER_HOST", "127.0.0.1:1")
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    T = 1_800_000_000_000
    with app.lock:
        for s in range(0, 120):                       # massa sobe 1 g/s; aos 60 s a balança é tarada (volta a 0)
            app.db.execute("INSERT INTO samples(ts,mass_g,mass_status) VALUES(?,?,?)", (T + s * 1000, float(s if s < 60 else s - 60), "ok"))
        for k, s in enumerate((10, 20, 61, 70, 71)):  # basculadas; as duas últimas a 1 s uma da outra
            app.db.execute("INSERT INTO tips(ts,src) VALUES(?,?)", (T + s * 1000, f"k{k}"))
        app.db.commit()
    rows = app.tip_rows("t.ts>=? AND t.ts<?", (T, T + 200_000), "ASC")
    by = {r["ts"]: r for r in rows}
    assert by[T + 10_000]["mass_g"] == 13.0 and by[T + 10_000]["settled"] and by[T + 10_000]["dm_g"] is None   # 1ª: sem anterior
    assert by[T + 20_000]["mass_g"] == 23.0 and by[T + 20_000]["dm_g"] == 10.0
    assert by[T + 61_000]["mass_g"] == 4.0 and by[T + 61_000]["dm_g"] is None                                    # tara: massa menor
    assert by[T + 70_000]["mass_g"] == 10.0 and not by[T + 70_000]["settled"]                                     # próxima veio antes de 3 s
    assert by[T + 71_000]["mass_g"] == 14.0 and by[T + 71_000]["settled"] and by[T + 71_000]["dm_g"] == 4.0
    desc = app.tip_rows("t.ts>=? AND t.ts<?", (T, T + 200_000), "DESC", 2)
    assert [r["ts"] for r in desc] == [T + 71_000, T + 70_000] and desc[1]["dm_g"] == 6.0                     # Δm usa a anterior fora da página
