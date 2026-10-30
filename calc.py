"""Cálculos de medição: funções puras (sem banco, sem relógio), todas por HORÁRIO REAL da amostra.

Convenções:
  * tempos em ms (época); intervalos semiabertos [início, fim): um evento exatamente em `fim` pertence ao período seguinte.
  * None = indisponível. Ausência de dado NUNCA vira zero.
  * massa em g, volume em cm³/mL/L, precipitação em mm, intensidade em mm/h, vazão em L/min.
  * medidor de vazão: fator K interno em pulsos/L; frequência = pulsos ÷ janela real de contagem (nunca a contagem crua).
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
    if not ts:
        return out
    a = b = None   # trecho aberto [a, b): só vira tupla quando fecha (antes, cada amostra recriava a tupla; mesmo resultado)
    last = len(ts) - 1
    for i, t in enumerate(ts):
        w = nominal_ms
        if i < last:
            d = ts[i + 1] - t
            if d <= max_gap_ms:
                w = d
        e = t + w
        if e > end:
            e = end
        if a is not None and t <= b:
            if e > b:
                b = e
        else:
            if a is not None:
                out.append((a, b))
            a, b = t, e
    out.append((a, b))
    return out


def window_coverage(sample_ts, start, end, **kw):
    """(ms cobertos, nº de lacunas, completo?). Completo = descoberto ≤ max(3 períodos nominais (inclui a latência de ~1–2 s do dado mais recente), 2 % da janela)."""
    return _coverage(covered_intervals(sample_ts, start, end, **kw), start, end)


def _coverage(iv, start, end):
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
    iv = covered_intervals(sample_ts, start, end)   # uma vez só: a cobertura e as basculadas cobertas usam os mesmos trechos
    cov, gaps, complete = _coverage(iv, start, end)
    out = {"tips": n, "covered_s": cov / 1000, "window_s": (end - start) / 1000, "gaps": gaps, "complete": complete,
           "precip_mm": None, "intensity_mm_h": None}
    if res_mm is None:
        return out
    if cov > 0:
        n_cov = sum(count_in(tip_ts, a, b) for a, b in iv)
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
        r["issues"].append("a massa diminuiu durante o ensaio (balança esvaziada ou tarada?): referência indisponível")
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


# ---------------------------------------------------------------- medidor de vazão: fator K
# Unidade interna do fator K: pulsos por litro. "Volume por pulso" é como o MAG 5000 configura a saída de pulsos.
#   pulsos/L  -> K                 pulsos/m³ -> K / 1000
#   L/pulso   -> 1 / V             mL/pulso  -> 1000 / V
K_UNITS = {"pulsos/L": ("k", 1.0), "pulsos/m³": ("k", 1e-3), "L/pulso": ("v", 1.0), "mL/pulso": ("v", 1e-3)}


def k_to_pulses_per_l(value, unit="pulsos/L"):
    """Fator K como o operador digitou -> pulsos/L. None se ausente, não finito, ≤ 0 ou unidade desconhecida (nunca um K presumido)."""
    if value is None or unit not in K_UNITS:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    kind, f = K_UNITS[unit]
    return v * f if kind == "k" else 1.0 / (v * f)


def k_from_pulses_per_l(k_l, unit="pulsos/L"):
    """Inverso de k_to_pulses_per_l: pulsos/L -> valor na unidade de exibição."""
    if not k_l or k_l <= 0 or unit not in K_UNITS:
        return None
    kind, f = K_UNITS[unit]
    return k_l / f if kind == "k" else 1.0 / (k_l * f)


# ---------------------------------------------------------------- medidor de vazão: sinal 4–20 mA
MA_FAULT = 3.6     # NAMUR NE 43: abaixo disso é sinal de falha (no modo "4–20 mA + alarme" o MAG 5000 vai a 1,3 / 2 / 3 mA)
MA_TOL = 0.02      # mA: tolerância padrão nos limites 4 e 20 mA (0,125 % do span); configurável


def classify_ma(ma, tol=MA_TOL):
    """Sinal 4–20 mA -> (estado, mA usado na escala).

      ok     4 ≤ I ≤ 20                   escala linear
      low    4 − tol ≤ I < 4              escala presa em 4 mA (ruído em vazão zero; não extrapola)
      high   20 < I ≤ 20 + tol            escala presa em 20 mA
      under  3,6 ≤ I < 4 − tol            abaixo da faixa: sem vazão
      over   I > 20 + tol                 acima da faixa (vazão acima do Qmax ou saída saturada): sem vazão
      fault  I < 3,6                      falha: laço aberto (~0 mA) ou alarme do transmissor
      invalid  sem leitura (NAN)
    """
    if ma is None:
        return "invalid", None
    tol = max(0.0, float(tol or 0.0))
    if ma < MA_FAULT:
        return "fault", None
    if ma < 4.0 - tol:
        return "under", None
    if ma < 4.0:
        return "low", 4.0
    if ma <= 20.0:
        return "ok", ma
    if ma <= 20.0 + tol:
        return "high", 20.0
    return "over", None


def analog_flow_l_min(ma_eff, q4, q20, range_unit, density_g_cm3=None):
    """mA já classificado (4..20) -> L/min pela relação linear da faixa configurada. Faixa ausente => None."""
    if ma_eff is None or q4 is None or q20 is None:
        return None
    return flow_to_l_min(q4 + (ma_eff - 4.0) / 16.0 * (q20 - q4), range_unit, density_g_cm3)


# ---------------------------------------------------------------- medidor de vazão: pulsos
# Flow_PStatus do CRBasic v4. 0 = contagem válida.
PULSE_CODES = {1: "primeiro Scan depois de iniciar o programa (janela de contagem incompleta)",
               2: "contador de pulsos saturado",
               3: "frequência acima do máximo possível do medidor (ruído ou ligação)",
               4: "contagem sem leitura (NAN)"}


def pulse_window_s(dt_ms):
    """Janela de contagem de um registro (s) e se ela foi presumida.

    A contagem de um registro cobre o intervalo REAL desde o registro anterior da mesma tabela (1 s nominal; 2 s se um Scan
    foi pulado, porque o contador de hardware acumula). Sem registro anterior, ou com lacuna maior que MAX_GAP_MS (registros
    perdidos, não Scan pulado), usa o Scan nominal e marca como presumida.
    """
    if dt_ms is not None and 0 < dt_ms <= MAX_GAP_MS:
        return dt_ms / 1000.0, False
    return NOMINAL_MS / 1000.0, True


def pulse_resolution_l_min(k_pulses_per_l, window_s=1.0):
    """Degrau de vazão de 1 pulso numa janela (L/min): a resolução da leitura instantânea por pulsos."""
    if not k_pulses_per_l or k_pulses_per_l <= 0 or not window_s:
        return None
    return 60.0 / (k_pulses_per_l * window_s)


def pulses_between(ts, pulses, totals, valid, a, b):
    """Pulsos em (a, b] para auditoria de volume.

    Preferência: diferença do contador acumulado (Flow_PulsosTot) entre os registros em a e em b. Ela não perde pulsos de
    registros ausentes no meio. Só vale se os dois extremos têm o acumulado e ele nunca diminui no trecho (diminuir =
    programa reiniciado ou volta a zero). Senão: soma das contagens válidas por registro em (a, b].
    Devolve (pulsos, 'acumulado' | 'soma', aviso ou None). Listas paralelas e ordenadas por ts.
    """
    idx = [i for i, t in enumerate(ts) if a < t <= b]
    by_ts = {t: i for i, t in enumerate(ts)}
    ia, ib = by_ts.get(a), by_ts.get(b)
    if ia is not None and ib is not None and totals[ia] is not None and totals[ib] is not None:
        seq = [totals[i] for i in [ia] + idx if totals[i] is not None]
        if all(y >= x for x, y in zip(seq, seq[1:])):
            return totals[ib] - totals[ia], "acumulado", None
        aviso = "contador acumulado reiniciado no intervalo (programa do datalogger reiniciado?): volume pela soma das contagens"
    else:
        aviso = None if all(t is None for t in totals) else "contador acumulado ausente num extremo do intervalo: volume pela soma das contagens"
    return sum(pulses[i] for i in idx if valid[i] and pulses[i] is not None), "soma", aviso


# ---------------------------------------------------------------- medidor de vazão: uma amostra, qualquer método -> L/min
def flow_from_sample(mode, status, pulses_hz, ma, k_pulses_per_l, q4, q20, range_unit, density_g_cm3=None, ma_tol=0.0):
    """Vazão instantânea em L/min a partir do dado BRUTO de uma amostra, ou None se não for possível.

    pulso   : Q = f(Hz) / K(pulsos/L) · 60        (K vem da configuração; sem K => None, nunca um K presumido)
    analógico: mA -> faixa linear 4–20 mA (q4..q20 na unidade `range_unit`) -> L/min; fora de 4–20 mA (além da
               tolerância `ma_tol`) => None. Dentro da tolerância a escala fica presa no limite (sem extrapolar).
    `ma_tol` = 0 reproduz exatamente o critério antigo (ensaios congelados antes da tolerância existir).
    """
    if status != "ok":
        return None
    if mode == "pulse":
        if pulses_hz is None or not k_pulses_per_l or k_pulses_per_l <= 0:
            return None
        return pulses_hz / k_pulses_per_l * 60.0
    _, eff = classify_ma(ma, ma_tol)
    return analog_flow_l_min(eff, q4, q20, range_unit, density_g_cm3)


def flow_reading(method, has, comm, ma, pulses, pulse_code, dt_ms, cfg):
    """Avalia UMA amostra do medidor pelo método escolhido. Nada é presumido: sem parâmetro => 'unconfigured'.

    method: 'analog' | 'pulse'      has: canais que o programa do datalogger fornece ({'analog', 'pulse'})
    comm  : 'ok' (havia registro de Vazao1s para a amostra) | 'no_comm'
    cfg   : q4, q20, range_unit, density, k_pulses_per_l, ma_tol
    Estados: ok | no_comm | unavailable | invalid | fault | out_of_range | unconfigured.
    O sinal bruto (mA ou pulsos/Hz) volta sempre que existir, mesmo quando a vazão não pode ser calculada.
    """
    out = {"method": method, "state": None, "reason": None, "lmin": None, "clamp": None, "ma": ma, "ma_class": None,
           "pulses": pulses, "hz": None, "window_s": None, "window_assumed": None, "resolution_lmin": None}
    if method not in ("analog", "pulse"):
        out.update(state="unconfigured", reason="método de aquisição não definido")
        return out
    if method not in has:
        out.update(state="unavailable", reason="o programa do datalogger não fornece o canal de pulsos (P2)" if method == "pulse"
                   else "o programa do datalogger não fornece o canal 4–20 mA")
        return out
    if comm != "ok":
        out.update(state="no_comm", reason="sem registro do medidor para esta amostra")
        return out
    k = cfg.get("k_pulses_per_l")
    if method == "pulse":
        w, assumed = pulse_window_s(dt_ms)
        out.update(window_s=w, window_assumed=assumed, resolution_lmin=pulse_resolution_l_min(k, w))
        if pulse_code:
            out.update(state="invalid", reason=PULSE_CODES.get(pulse_code, f"código de estado {pulse_code} do canal de pulsos"))
            return out
        if pulses is None:
            out.update(state="invalid", reason="contagem de pulsos ausente")
            return out
        out["hz"] = pulses / w
        if not k or k <= 0:
            out.update(state="unconfigured", reason="fator K não configurado")
            return out
        out.update(state="ok", lmin=out["hz"] / k * 60.0)
        return out
    cls, eff = classify_ma(ma, cfg.get("ma_tol", MA_TOL))
    out["ma_class"] = cls
    if cls == "invalid":
        out.update(state="invalid", reason="corrente sem leitura (NAN)")
    elif cls == "fault":
        out.update(state="fault", reason="corrente abaixo de 3,6 mA: laço aberto ou alarme do transmissor")
    elif cls == "under":
        out.update(state="out_of_range", reason="corrente abaixo de 4 mA além da tolerância")
    elif cls == "over":
        out.update(state="out_of_range", reason="corrente acima de 20 mA além da tolerância (vazão acima do Qmax ou saída saturada)")
    elif cfg.get("q4") is None or cfg.get("q20") is None:
        out.update(state="unconfigured", reason="faixa 4–20 mA não configurada")
    else:
        v = analog_flow_l_min(eff, cfg["q4"], cfg["q20"], cfg.get("range_unit", "L/min"), cfg.get("density"))
        if v is None:
            out.update(state="unconfigured", reason="unidade mássica da faixa exige a densidade da água")
        else:
            out.update(state="ok", lmin=v, clamp={"low": "low", "high": "high"}.get(cls))
    return out


def stored_status(reading):
    """Estado gravado no banco (coluna cor_status) a partir de flow_reading: diz se o DADO é válido, não se a configuração
    está completa. 'unconfigured' com sinal válido grava 'ok' (a vazão é recalculada quando a configuração existir)."""
    st = reading["state"]
    if st in ("ok", "unconfigured"):
        return "ok"
    return "out_of_range" if st == "fault" else st


def sample_weights_ms(ts, max_gap_ms=MAX_GAP_MS, nominal_ms=NOMINAL_MS):
    """Duração que cada amostra representa: até a próxima (se não houver lacuna), senão o período nominal."""
    w = []
    for i, t in enumerate(ts):
        nxt = ts[i + 1] if i + 1 < len(ts) else None
        w.append((nxt - t) if nxt is not None and nxt - t <= max_gap_ms else nominal_ms)
    return w
