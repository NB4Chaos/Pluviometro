"""Cálculos de medição: funções puras (sem banco, sem relógio), todas por HORÁRIO REAL da amostra.

Convenções:
  * tempos em ms (época); intervalos semiabertos [início, fim): um evento exatamente em `fim` pertence ao período seguinte.
  * None = indisponível. Ausência de dado NUNCA vira zero.
  * massa em g, volume em cm³/mL/L, precipitação em mm, intensidade em mm/h, vazão em L/min.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque

NOMINAL_MS = 1000     # período nominal da aquisição (Scan de 1 s no CRBasic)
MAX_GAP_MS = 2500     # acima disso entre duas amostras seguidas existe lacuna (o Scan é de 1 s)

# Unidades de vazão -> L/min (volumétricas) ou kg/min (mássicas). Mesma tabela do frontend (util.js).
_VOL_L_MIN = {"L/min": 1.0, "L/h": 1 / 60, "mL/min": 1e-3, "mL/s": 0.06, "m³/h": 1000 / 60, "m³/s": 60000.0, "m³/min": 1000.0}
_MASS_KG_MIN = {"kg/h": 1 / 60, "kg/s": 60.0}


def flow_to_l_min(value, unit, density_g_cm3=None):
    """Converte uma vazão para L/min. Unidade mássica exige densidade (g/cm³ = kg/L); sem ela devolve None."""
    if value is None:
        return None
    if unit in _VOL_L_MIN:
        return value * _VOL_L_MIN[unit]
    if unit in _MASS_KG_MIN:
        return value * _MASS_KG_MIN[unit] / density_g_cm3 if density_g_cm3 else None
    return None


# ---------------------------------------------------------------- períodos, cobertura e precipitação
def count_in(ts_list, start, end):
    """Quantos eventos de `ts_list` (ordenada) caem em [start, end)."""
    return bisect_left(ts_list, end) - bisect_left(ts_list, start)


def covered_intervals(sample_ts, start, end, max_gap_ms=MAX_GAP_MS, nominal_ms=NOMINAL_MS):
    """Trechos de [start, end) realmente cobertos por amostras.

    Cada amostra cobre [ts, próxima amostra) se a distância até a próxima for ≤ max_gap_ms; se for maior (lacuna),
    cobre só o próprio período nominal. A última amostra cobre um período nominal. Resultado: lista de (a, b) fundidos.
    """
    ts = [t for t in sample_ts if start <= t < end]
    out = []
    for i, t in enumerate(ts):
        nxt = ts[i + 1] if i + 1 < len(ts) else None
        w = (nxt - t) if nxt is not None and nxt - t <= max_gap_ms else nominal_ms
        a, b = t, min(t + w, end)
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def window_coverage(sample_ts, start, end, **kw):
    """(ms cobertos, nº de lacunas, completo?). Completo = descoberto ≤ max(3 períodos nominais (inclui a latência de ~1–2 s do dado mais recente), 2 % da janela)."""
    iv = covered_intervals(sample_ts, start, end, **kw)
    cov = sum(b - a for a, b in iv)
    gaps = max(0, len(iv) - 1)
    tol = max(3 * NOMINAL_MS, 0.02 * (end - start))
    return cov, gaps, (end - start) - cov <= tol


def precip_period(tip_ts, sample_ts, start, end, res_mm):
    """Precipitação acumulada e intensidade média de [start, end).

    acumulado  = basculadas do período × resolução (mm)
    intensidade = basculadas dentro dos trechos COBERTOS × resolução ÷ tempo coberto (mm/h)
    `complete` False => resultado parcial (mostre a duração coberta). Sem amostras => intensidade None.
    """
    n = count_in(tip_ts, start, end)
    cov, gaps, complete = window_coverage(sample_ts, start, end)
    out = {"tips": n, "covered_s": cov / 1000, "window_s": (end - start) / 1000, "gaps": gaps, "complete": complete,
           "precip_mm": None, "intensity_mm_h": None}
    if res_mm is None:
        return out
    if cov > 0:
        n_cov = sum(count_in(tip_ts, a, b) for a, b in covered_intervals(sample_ts, start, end))
        out["precip_mm"] = n * res_mm
        out["intensity_mm_h"] = n_cov * res_mm / (cov / 3.6e6)
    elif n > 0:
        out["precip_mm"] = n * res_mm   # há eventos registrados, mas nenhuma amostra para medir a duração
    return out   # sem amostras e sem eventos: desconhecido, não "zero chuva"


# ---------------------------------------------------------------- médias e taxas por janela de tempo
def rolling_mean(ts, vals, window_ms, min_n=3):
    """Média móvel à direita: em cada ts[i], média dos valores VÁLIDOS em (ts[i]-window, ts[i]].

    Menos de `min_n` válidos na janela => None (nunca um número enganoso). Valores None (NAN) são ignorados,
    inclusive nas lacunas: a média usa só o que foi medido.
    """
    out, q, s, n = [], deque(), 0.0, 0
    for t, v in zip(ts, vals):
        if v is not None:
            q.append((t, v)); s += v; n += 1
        while q and q[0][0] <= t - window_ms:
            _, old = q.popleft(); s -= old; n -= 1
        out.append(s / n if n >= min_n else None)
    return out


def rolling_slope(ts, vals, window_ms, min_n=5, min_span_frac=0.5):
    """Inclinação (unidade/s) por regressão linear na janela (t-window, t], só com valores válidos.

    Exige ≥ min_n pontos e que eles cubram ≥ min_span_frac da janela; senão None. Somas deslizantes: O(n).
    """
    out, q = [], deque()
    t0 = ts[0] if ts else 0
    sx = sy = sxx = sxy = 0.0
    for t, v in zip(ts, vals):
        if v is not None:
            x = (t - t0) / 1000.0
            q.append((t, x, v)); sx += x; sy += v; sxx += x * x; sxy += x * v
        while q and q[0][0] <= t - window_ms:
            _, x, y = q.popleft(); sx -= x; sy -= y; sxx -= x * x; sxy -= x * y
        n = len(q)
        if n < min_n or q[-1][0] - q[0][0] < window_ms * min_span_frac:
            out.append(None); continue
        den = sxx - sx * sx / n
        out.append(None if den <= 1e-9 else (sxy - sx * sy / n) / den)
    return out


def stats(vals):
    """(média, mín, máx, n) dos valores válidos; tudo None se não houver nenhum."""
    v = [x for x in vals if x is not None]
    return (sum(v) / len(v), min(v), max(v), len(v)) if v else (None, None, None, 0)


def mass_slope_to_l_min(g_per_s, density_g_cm3):
    """Inclinação da massa (g/s) -> vazão (L/min). Sem densidade => None."""
    if g_per_s is None or not density_g_cm3:
        return None
    return g_per_s / density_g_cm3 / 1000.0 * 60.0


# ---------------------------------------------------------------- gravimetria
def gravimetric(m0_g, m1_g, t0_ms, t1_ms, density_g_cm3, area_cm2, pulses=None, res_mm=None):
    """Referência gravimétrica de um intervalo, pela VARIAÇÃO de massa na balança.

      Δm (g) = m1 − m0                  V (cm³ = mL) = Δm / ρ            V (L) = V(cm³) / 1000
      P (mm) = 10 · V(cm³) / A(cm²)     I (mm/h) = P / Δt(h)             Q (L/min) = V(L) / Δt(min)
    Δt = t1 − t0 (tempo entre as duas leituras de massa realmente usadas). Dados faltando => campo None + `issues`.
    """
    r = {"mass_start_g": m0_g, "mass_end_g": m1_g, "delta_mass_g": None, "volume_ml": None, "volume_l": None,
         "precip_ref_mm": None, "intensity_ref_mm_h": None, "flow_ref_l_min": None, "duration_s": None,
         "pluv_pulses": pulses, "pluv_precip_mm": None, "pluv_intensity_mm_h": None,
         "diff_mm": None, "error_pct": None, "issues": []}
    if m0_g is None or m1_g is None or t0_ms is None or t1_ms is None or t1_ms <= t0_ms:
        r["issues"].append("sem duas leituras válidas de massa em instantes distintos")
        return r
    dt_s = (t1_ms - t0_ms) / 1000.0
    r["duration_s"] = dt_s
    if pulses is not None and res_mm:   # indicação do pluviômetro: independe da balança, por isso vem antes das verificações
        r["pluv_precip_mm"] = pulses * res_mm
        r["pluv_intensity_mm_h"] = r["pluv_precip_mm"] / (dt_s / 3600.0)
    dm = m1_g - m0_g
    r["delta_mass_g"] = dm
    if dm < 0:
        r["issues"].append("a massa diminuiu no intervalo (balança esvaziada ou tarada?): referência indisponível")
        return r
    if not density_g_cm3 or density_g_cm3 <= 0:
        r["issues"].append("densidade da água não configurada: volume indisponível")
        return r
    v_cm3 = dm / density_g_cm3
    r["volume_ml"], r["volume_l"] = v_cm3, v_cm3 / 1000.0
    r["flow_ref_l_min"] = r["volume_l"] / (dt_s / 60.0)
    if area_cm2 and area_cm2 > 0:
        r["precip_ref_mm"] = 10.0 * v_cm3 / area_cm2
        r["intensity_ref_mm_h"] = r["precip_ref_mm"] / (dt_s / 3600.0)
    else:
        r["issues"].append("área de captação não configurada: precipitação de referência indisponível")
    if r["pluv_precip_mm"] is not None and r["precip_ref_mm"] is not None:
        r["diff_mm"] = r["pluv_precip_mm"] - r["precip_ref_mm"]
        if r["precip_ref_mm"] > 0:
            r["error_pct"] = 100.0 * r["diff_mm"] / r["precip_ref_mm"]
    return r


# ---------------------------------------------------------------- medidor de vazão: fator K, sinal 4–20 mA e pulsos brutos
MA_TOL = 0.02         # tolerância (mA) nos limites de 4 e 20 mA: dentro dela o valor fica PRESO ao limite, nunca extrapolado
MA_FAIL_BELOW = 3.6   # abaixo disso o sinal é falha do transmissor/laço (NAMUR NE 43), não vazão
K_UNITS = ("pulsos/L", "pulsos/m³", "L/pulso", "mL/pulso")


def k_to_pulses_per_l(value, unit):
    """Fator K em qualquer unidade aceita -> pulsos por litro. None se ausente, não finito, <= 0 ou unidade desconhecida."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    if unit == "pulsos/L":
        return v
    if unit == "pulsos/m³":
        return v / 1000.0
    if unit == "L/pulso":
        return 1.0 / v
    if unit == "mL/pulso":
        return 1000.0 / v
    return None


def classify_ma(ma, tol=MA_TOL, fail_below=MA_FAIL_BELOW):
    """(estado, valor usável) do sinal 4–20 mA.

    ok    : 4−tol <= mA <= 20+tol; o valor devolvido fica preso a [4, 20] (sem extrapolar a escala)
    under : fail_below <= mA < 4−tol      over: mA > 20+tol      fail: mA < fail_below      none: sem sinal
    """
    if ma is None or not math.isfinite(ma):
        return "none", None
    if ma < fail_below:
        return "fail", ma
    if ma < 4.0 - tol:
        return "under", ma
    if ma > 20.0 + tol:
        return "over", ma
    return "ok", min(20.0, max(4.0, ma))


def pulse_volume_l(n, k_pulses_per_l):
    """Volume (L) de N pulsos brutos: V = N / K. None sem N ou sem K válido."""
    if n is None or not k_pulses_per_l or k_pulses_per_l <= 0:
        return None
    return n / k_pulses_per_l


def pulse_flow_l_min(n, dt_s, k_pulses_per_l):
    """Vazão média (L/min) de N pulsos em dt_s segundos: Q = (N / K) / dt · 60. None se dt <= 0, sem N ou sem K."""
    v = pulse_volume_l(n, k_pulses_per_l)
    if v is None or dt_s is None or dt_s <= 0:
        return None
    return v / dt_s * 60.0


def pulse_count_window(counts, totals):
    """Pulsos recebidos numa janela de registros do datalogger.

    counts: pulsos contados em cada registro (Flow_Pulsos); totals: contador acumulado no fim de cada registro (Flow_PulsosTot).
    n_delta = Tot_final − (Tot_inicial − pulsos_inicial)  (= Contador_final − Contador_inicial do pedido): robusto a registros perdidos.
    n_sum   = Σ counts: robusto a reinício do contador, perde o que caiu em lacunas.
    n = n_delta quando o acumulado existe e nunca diminuiu ("acumulado"); senão n_sum ("soma"). reset = o acumulado diminuiu.
    """
    out = {"n_sum": None, "n_delta": None, "n": None, "method": None, "reset": False}
    cs = [c for c in counts if c is not None]
    if not cs:
        return out
    out["n_sum"] = int(round(sum(cs)))
    ts = [t for t in totals if t is not None]
    if len(ts) == len(counts) and ts:
        if any(b < a for a, b in zip(ts, ts[1:])):
            out["reset"] = True
        else:
            out["n_delta"] = int(round(ts[-1] - (ts[0] - counts[0])))
    if out["n_delta"] is not None and not out["reset"]:
        out["n"], out["method"] = out["n_delta"], "acumulado"
    else:
        out["n"], out["method"] = out["n_sum"], "soma"
    return out


# ---------------------------------------------------------------- medidor de vazão (qualquer modo -> L/min)
def flow_from_sample(mode, status, pulses_hz, ma, k_pulses_per_l, q4, q20, range_unit, density_g_cm3=None, tol=MA_TOL):
    """Vazão instantânea em L/min a partir do dado BRUTO de uma amostra, ou None se não for possível.

    pulso   : Q = f(Hz) / K(pulsos/L) · 60        (K vem da configuração; sem K => None, nunca um K presumido)
    analógico: mA classificado por `classify_ma` (tolerância nos limites, sem extrapolar) -> faixa linear 4–20 mA
               (q4..q20 na unidade `range_unit`) -> L/min; fora da faixa ou falha => None
    """
    if status != "ok":
        return None
    if mode == "pulse":
        if pulses_hz is None or not k_pulses_per_l or k_pulses_per_l <= 0:
            return None
        return pulses_hz / k_pulses_per_l * 60.0
    state, ma_c = classify_ma(ma, tol)
    if state != "ok" or q4 is None or q20 is None:
        return None
    return flow_to_l_min(q4 + (ma_c - 4.0) / 16.0 * (q20 - q4), range_unit, density_g_cm3)


def sample_weights_ms(ts, max_gap_ms=MAX_GAP_MS, nominal_ms=NOMINAL_MS):
    """Duração que cada amostra representa: até a próxima (se não houver lacuna), senão o período nominal."""
    w = []
    for i, t in enumerate(ts):
        nxt = ts[i + 1] if i + 1 < len(ts) else None
        w.append((nxt - t) if nxt is not None and nxt - t <= max_gap_ms else nominal_ms)
    return w
