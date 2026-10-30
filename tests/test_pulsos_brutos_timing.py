"""Sobre a base do TI (28/10): contagem BRUTA de pulsos no ensaio (N = diferença do contador acumulado, ou soma dos registros),
bloco de temporização (carimbos do datalogger, configurado × efetivo, resolução), duração em ms com mínimo = Scan.
Reescreve os cenários dos testes da fase anterior (test_trials_pulsos / test_trials_timing). Banco em memória, sem rede."""
import os, sqlite3, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from trials import Trials, TrialError

T0 = 1_800_000_000_000
CFG = {"tip_resolution_mm": 0.2, "catch_area_cm2": 200.0, "density_g_cm3": 1.0, "flow_k_pulses_per_l": 1000.0, "flow_k_unit": "pulsos/L",
       "flow_method": "pulse", "flow_ma_tol": 0.02, "trial_duration_ms": 60000, "trial_duration_s": 60, "cor": {"q4": 0.0, "q20": 16.0, "unit": "L/min"}}
COLS = "ts,mass_g,temp_c,mass_status,temp_status,tips_total,cor_ma,cor_status,flow_mode,flow_pulses,flow_hz,pulses_total,ma_code,pulse_code,flow_dt_ms"


class Env:
    def __init__(self, cfg=None, scan_ms=1000):
        self.cfg = dict(CFG, **(cfg or {}))
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript("""CREATE TABLE samples(ts INTEGER PRIMARY KEY, mass_g REAL, temp_c REAL, mass_status TEXT, temp_status TEXT,
          tips_total INTEGER, cor_ma REAL, cor_status TEXT, flow_mode TEXT, flow_pulses REAL, flow_hz REAL, pulses_total INTEGER, ma_code INTEGER,
          pulse_code INTEGER, flow_dt_ms INTEGER); CREATE TABLE tips(ts INTEGER, src TEXT);""")
        self.lock = threading.Lock()
        self.tr = Trials(self.db, self.lock, lambda: self.cfg, lambda: self.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0], scan_ms=scan_ms)
        self.total = 1000      # contador acumulado do datalogger antes do ensaio

    def add(self, sec, pulses=100, ma=12.0, mass=None, comm=True, total=None, mode="pulse"):
        ts = T0 + sec * 1000
        if comm and pulses is not None:
            self.total += pulses
        tot = self.total if total is None else total
        self.db.execute(f"INSERT OR REPLACE INTO samples({COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, mass, 22.0, "ok" if mass is not None else "no_comm", "ok", 0, ma if comm else None, "ok" if comm else "no_comm",
                         mode if comm else None, pulses if comm else None, (pulses / 1.0) if (comm and pulses is not None) else None,
                         tot if comm else None, 0 if comm else None, 0 if comm else None, 1000 if comm else None))
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


# ---------------- contagem bruta
def test_nenhum_pulso_e_vazao_zero_valida_com_aviso(env):
    f = env.run(pulses=0)["result"]["flow"]
    assert f["pulses_total"] == 0 and f["volume_l"] == 0 and f["flow_l_min"]["mean"] == 0 and any("pulsos" in i for i in f["issues"])


def test_um_pulso_no_ensaio(env):
    f = env.run(pulses=lambda s: 1 if s == 30 else 0)["result"]["flow"]
    assert f["pulses_total"] == 1 and f["pulses_sum"] == 1 and f["volume_l"] == pytest.approx(0.001)


def test_multiplos_pulsos_N_dividido_por_K_e_pelo_tempo(env):
    r = env.run(pulses=100)
    f = r["result"]["flow"]
    assert r["state"] == "completed" and f["mode"] == "pulse" and f["pulses_total"] == 6000 and f["count_method"] == "acumulado"
    assert f["volume_l"] == pytest.approx(6.0) and f["flow_l_min"]["mean"] == pytest.approx(6.0) and f["freq_mean_hz"] == pytest.approx(100.0)


def test_exemplo_do_pedido_1250_pulsos_em_60_s_com_K_100():
    e = Env({"flow_k_pulses_per_l": 100.0})
    pulses = {s: 21 if s - 5 < 50 else 20 for s in range(5, 65)}      # 50×21 + 10×20 = 1250 pulsos nos 60 registros do ensaio
    f = e.run(pulses=lambda s: pulses.get(s, 0))["result"]["flow"]
    assert f["pulses_total"] == 1250 and f["volume_l"] == pytest.approx(12.5) and f["flow_l_min"]["mean"] == pytest.approx(12.5)   # 12,5 L em 60 s = 12,5 L/min


def test_lacuna_de_registros_nao_perde_pulsos_pelo_acumulado(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.total += 10 * 100                      # o datalogger seguiu contando enquanto os registros não chegaram
    env.feed(40, 80)
    r = env.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["pulses_sum"] == 5000 and f["pulses_total"] == 6000 and f["count_method"] == "acumulado"
    assert r["state"] == "incomplete" and "lacunas" in r["reason"]


def test_perda_de_comunicacao_nao_vira_ausencia_de_pulsos(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.feed(30, 40, comm=False)               # 10 s sem registro do medidor
    env.total += 10 * 100
    env.feed(40, 80)
    r = env.tr.get(t["id"])
    f = r["result"]["flow"]
    assert f["pulses_total"] == 6000 and f["count_method"] == "acumulado" and f["n_valid"] == 50 and r["state"] == "incomplete"


def test_contador_reiniciado_usa_a_soma(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 30)
    env.total = 0                              # programa do datalogger reiniciou
    env.feed(30, 80)
    f = env.tr.get(t["id"])["result"]["flow"]
    assert f["count_method"] == "soma" and f["pulses_total"] == 6000


def test_sem_fator_k_preserva_a_contagem_sem_inventar_vazao():
    e = Env({"flow_k_pulses_per_l": None})
    r = e.run(pulses=100)
    f = r["result"]["flow"]
    assert f["pulses_total"] == 6000 and f["volume_l"] is None and f["flow_l_min"] is None and r["state"] == "incomplete"


def test_reinicio_do_ensaio_conta_so_a_janela_nova(env):
    env.feed(0, 5)
    t1 = env.tr.start("flow", True)
    env.feed(5, 20)
    env.tr.stop()
    env.feed(20, 25)
    t2 = env.tr.start("flow", True)
    env.feed(25, 90)
    assert env.tr.get(t1["id"])["result"]["flow"]["pulses_total"] == 1500 and env.tr.get(t2["id"])["result"]["flow"]["pulses_total"] == 6000


def test_metodo_analogico_nao_mistura_com_pulsos():
    e = Env({"flow_method": "analog"})
    f = e.run(pulses=100, ma=12.0, mode="analog")["result"]["flow"]
    assert f["mode"] == "analog" and f["flow_l_min"]["mean"] == pytest.approx(8.0) and f["pulses_total"] is None


# ---------------- temporização e duração
def test_ensaio_completo_registra_carimbos_cfg_efetivo_e_resolucao(env):
    r = env.run(pulses=100)
    t = r["result"]["timing"]
    assert t["start_ts"] == T0 + 4001 and t["end_ts"] == t["start_ts"] + 60000 and t["cfg_ms"] == 60000 and t["window_ms"] == 60000
    assert t["first_sample_ts"] == T0 + 5000 and t["last_sample_ts"] == T0 + 64000 and t["samples"] == 60
    assert t["eff_ms"] == 60000 and t["diff_ms"] == 0 and t["resolution_ms"] == 1000 and t["wall_ms"] >= 0
    assert r["duration_cfg_ms"] == 60000 and r["duration_cfg_s"] == 60


def test_duracao_menor_que_o_scan_e_recusada():
    e = Env({"trial_duration_ms": 500})
    e.feed(0, 5)
    with pytest.raises(TrialError) as x:
        e.tr.start("flow", True)
    assert x.value.status == 400 and "1000 ms" in x.value.msg


def test_duracao_1500_ms_aceita_e_quantizada_sem_arredondar_a_configuracao():
    e = Env({"trial_duration_ms": 1500})
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    assert t["end_ts"] - t["start_ts"] == 1500 and t["duration_cfg_ms"] == 1500 and t["duration_cfg_s"] == 1.5
    e.feed(5, 10)
    tm = e.tr.get(t["id"])["result"]["timing"]
    assert tm["cfg_ms"] == 1500 and tm["eff_ms"] in (1000, 2000) and tm["diff_ms"] == tm["eff_ms"] - 1500


def test_lacuna_no_fim_reduz_o_tempo_efetivo(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.feed(5, 50)
    env.feed(70, 72)
    tm = env.tr.get(t["id"])["result"]["timing"]
    assert tm["samples"] == 45 and tm["eff_ms"] == 45000 and tm["diff_ms"] == -15000


def test_sem_amostras_nao_inventa_tempo_efetivo(env):
    env.feed(0, 5)
    t = env.tr.start("flow", True)
    env.tr.stop()
    tm = env.tr.get(t["id"])["result"]["timing"]
    assert tm["samples"] == 0 and tm["eff_ms"] is None and tm["diff_ms"] is None


def test_configuracao_antiga_so_com_segundos_continua_valendo():
    e = Env({"trial_duration_s": 10})
    e.cfg.pop("trial_duration_ms")
    e.feed(0, 5)
    t = e.tr.start("flow", True)
    assert t["duration_cfg_ms"] == 10000 and t["end_ts"] - t["start_ts"] == 10000
