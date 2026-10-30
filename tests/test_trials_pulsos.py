"""Ensaios por PULSOS: contagem bruta (N) pelo contador acumulado ou pela soma dos registros, tempo efetivo, resolução, lacunas,
perda de comunicação, contador reiniciado, duração em ms. Banco em memória, sem rede, sem relógio real."""
import os, sqlite3, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from trials import Trials, TrialError

T0 = 1_800_000_000_000
CFG = {"tip_resolution_mm": 0.2, "catch_area_cm2": 200.0, "density_g_cm3": 1.0, "flow_method": "pulse", "flow_k_pulses_per_l": 1000.0,
       "flow_k_value": 1000.0, "flow_k_unit": "pulsos/L", "flow_ma_tol": 0.02, "trial_duration_ms": 60000, "trial_duration_s": 60,
       "cor": {"q4": 0.0, "q20": 16.0, "unit": "L/min"}}
COLS = "ts,mass_g,temp_c,mass_status,temp_status,tips_total,cor_ma,cor_status,flow_mode,flow_pulses,flow_hz,flow_pulses_total,pulse_status"


class Env:
    def __init__(self, cfg=None, scan_ms=1000):
        self.cfg = dict(CFG, **(cfg or {}))
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript("""CREATE TABLE samples(ts INTEGER PRIMARY KEY, mass_g REAL, temp_c REAL, mass_status TEXT, temp_status TEXT,
          tips_total INTEGER, cor_ma REAL, cor_status TEXT, flow_mode TEXT, flow_pulses REAL, flow_hz REAL, flow_pulses_total INTEGER, pulse_status TEXT);
          CREATE TABLE tips(ts INTEGER, src TEXT);""")
        self.lock = threading.Lock()
        self.tr = Trials(self.db, self.lock, lambda: self.cfg, lambda: self.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0], scan_ms=scan_ms)
        self.total = 1000     # contador acumulado do datalogger antes do ensaio

    def add(self, sec, pulses=100, ma=12.0, mass=None, pstatus=None, cor_status=None, total=None):
        ts = T0 + sec * 1000
        if pstatus is None:
            pstatus = "ok" if pulses is not None else "no_comm"
        if pulses is not None and pstatus == "ok":
            self.total += pulses
        tot = self.total if total is None else total
        self.db.execute(f"INSERT OR REPLACE INTO samples({COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, mass, 22.0, "ok" if mass is not None else "no_comm", "ok", 0, ma, cor_status or ("ok" if ma is not None else "no_comm"),
                         "analog", pulses if pstatus == "ok" else None, (pulses / 1.0) if (pulses is not None and pstatus == "ok") else None,
                         tot if pstatus != "no_comm" else None, pstatus))
        self.db.commit()

    def feed(self, a, b, **kw):
        for s in range(a, b):
            self.add(s, **{k: (v(s) if callable(v) else v) for k, v in kw.items()})
        return self.tr.tick(int(time.time() * 1000))

    def run(self, before=5, after=80, **kw):
        self.feed(0, before, **kw)
        t = self.tr.start("flow", True)
        self.feed(before, after, **kw)
        return self.tr.get(t["id"])


@pytest.fixture
def env():
    return Env()


def test_nenhum_pulso_e_vazao_zero_valida_com_aviso(env):
    r = env.run(pulses=0)
    f = r["result"]["flow"]
    assert r["state"] == "completed" and f["pulses_total"] == 0 and f["volume_l"] == 0 and f["flow_l_min"]["mean"] == 0
    assert any("200" in w for w in f["warnings"])                   # poucos pulsos: aviso, não erro


def test_um_pulso_no_ensaio(env):
    r = env.run(pulses=lambda s: 1 if s == 30 else 0)
    f = r["result"]["flow"]
    assert f["pulses_total"] == 1 and f["pulses_sum"] == 1 and f["pulses_delta_total"] == 1 and f["volume_l"] == pytest.approx(0.001)


def test_multiplos_pulsos_exemplo_do_pedido_e_tempo_efetivo(env):
    r = env.run(pulses=100)
    f = r["result"]["flow"]
    assert r["state"] == "completed" and f["mode"] == "pulse"
    assert f["pulses_total"] == 6000 and f["count_method"] == "acumulado" and f["pulses_sum"] == 6000 and f["pulses_delta_total"] == 6000
    assert f["elapsed_s"] == pytest.approx(60.0) and f["time_cfg_ms"] == 60000 and f["time_eff_ms"] == 60000 and f["time_resolution_ms"] == 1000
    assert f["volume_l"] == pytest.approx(6.0) and f["flow_l_min"]["mean"] == pytest.approx(6.0) and f["freq_mean_hz"] == pytest.approx(100.0)
    assert f["raw_counts"] == 60                                     # registros com contagem válida


def test_lacuna_de_registros_nao_perde_pulsos_pelo_acumulado(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.total += 10 * 100                                            # o datalogger seguiu contando enquanto os registros não chegaram
    env.feed(40, 80)
    r = env.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["pulses_sum"] == 5000 and f["pulses_delta_total"] == 6000 and f["pulses_total"] == 6000 and f["count_method"] == "acumulado"
    assert f["time_eff_ms"] == 60000                                 # do primeiro ao último registro válido, inclusive a lacuna
    assert r["state"] == "incomplete" and "lacunas" in r["reason"]   # a cobertura ficou incompleta: o ensaio avisa


def test_perda_de_comunicacao_nao_vira_ausencia_de_pulsos(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.feed(30, 40, pulses=None)                                    # 10 s sem comunicação: registros sem o canal...
    env.total += 10 * 100                                            # ...mas o datalogger seguiu contando
    env.feed(40, 80)
    r = env.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["pulses_total"] == 6000 and f["count_method"] == "acumulado" and f["pulses_sum"] == 5000
    assert f["n_valid"] == 50 and f["valid_fraction"] < 0.95 and r["state"] == "incomplete"


def test_contador_reiniciado_sem_lacuna_usa_a_soma(env):
    def tot(s):
        return None
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.total = 0                                                    # programa do datalogger reiniciou: Flow_PulsosTot volta a zero
    env.feed(30, 80)
    f = env.tr.get(t["id"])["result"]["flow"]
    assert f["counter_reset"] and f["count_method"] == "soma" and f["pulses_total"] == 6000 and f["pulses_delta_total"] is None
    assert env.tr.get(t["id"])["state"] == "completed" and any("reinici" in w for w in f["warnings"])


def test_contador_reiniciado_e_lacuna_juntos_invalidam_a_contagem(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.total = 0
    env.feed(40, 80)
    r = env.tr.get(t["id"])
    assert r["state"] == "incomplete" and "contador" in r["reason"] and r["result"]["flow"]["pulses_total"] == 5000


def test_sem_fator_k_mostra_pulsos_brutos_sem_inventar_vazao():
    e = Env({"flow_k_pulses_per_l": None, "flow_k_value": None})
    r = e.run(pulses=100)
    f = r["result"]["flow"]
    assert f["pulses_total"] == 6000 and f["volume_l"] is None and f["flow_l_min"] is None and f["issues"]
    assert r["state"] == "incomplete"


def test_duracao_menor_que_a_resolucao_do_datalogger_e_recusada():
    e = Env({"trial_duration_ms": 500})
    e.feed(0, 5)
    with pytest.raises(TrialError) as x:
        e.tr.start("flow", True)
    assert x.value.status == 400 and "1000 ms" in x.value.msg


def test_duracao_em_ms_nao_multipla_do_scan_e_aceita_e_quantizada():
    e = Env({"trial_duration_ms": 1500})
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    assert t["end_ts"] - t["start_ts"] == 1500 and t["duration_cfg_ms"] == 1500
    e.feed(5, 10)
    r = e.tr.get(t["id"])
    f = r["result"]["flow"]
    assert r["state"] in ("completed", "incomplete") and f["time_cfg_ms"] == 1500 and f["time_eff_ms"] in (1000, 2000)
    assert f["time_resolution_ms"] == 1000 and r["result"]["quality"]["window_s"] == pytest.approx(1.5)


def test_reinicio_do_ensaio_conta_so_a_janela_nova(env):
    env.feed(0, 5)
    t1 = env.tr.start("flow", True)
    env.feed(5, 20)
    env.tr.stop()
    env.feed(20, 25)
    t2 = env.tr.start("flow", True)
    env.feed(25, 90)
    f1, f2 = env.tr.get(t1["id"])["result"]["flow"], env.tr.get(t2["id"])["result"]["flow"]
    assert f1["pulses_total"] == 1500 and f2["pulses_total"] == 6000


def test_metodo_pulsos_sem_canal_no_programa_fica_incompleto(env):
    r = env.run(pulses=None, pstatus=None)                           # programa v3: nenhuma linha tem o canal de pulsos
    f = r["result"]["flow"]
    assert r["state"] == "incomplete" and "pulsos" in r["reason"] and f["pulses_total"] is None


def test_metodo_analogico_congelado_e_outro_canal_informativo():
    e = Env({"flow_method": "analog"})
    r = e.run(pulses=100, ma=12.0)
    f = r["result"]["flow"]
    assert f["mode"] == "analog" and f["flow_l_min"]["mean"] == pytest.approx(8.0)       # 12 mA em 0–16 L/min
    assert f["other_channel"]["pulses_total"] == 6000 and f["other_channel"]["volume_l"] == pytest.approx(6.0)
    e.cfg["flow_method"] = "pulse"                                   # trocar o método depois não altera o ensaio congelado
    assert e.tr.get(r["id"])["result"]["flow"]["mode"] == "analog"


def test_tolerancia_do_4_20_congelada_no_ensaio():
    e = Env({"flow_method": "analog", "flow_ma_tol": 0.02})
    r = e.run(pulses=100, ma=3.99)
    f = r["result"]["flow"]
    assert f["flow_l_min"]["mean"] == pytest.approx(0.0) and f["n_valid"] == 60 and r["cfg"]["ma_tol"] == 0.02
    e2 = Env({"flow_method": "analog", "flow_ma_tol": 0.0})
    r2 = e2.run(pulses=100, ma=3.99)
    assert r2["result"]["flow"]["n_valid"] == 0 and r2["state"] == "incomplete"
