# Mapa CRBasic → servidor → interface (30/10/2026)

Programa **em uso**: `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X` (Scan de 1 s). Programa com pulsos: `Pluviometria_v4_vazao_pulsos.CR1X` (mesmos campos +
3 de pulso; **não compilado**). Perfil do servidor: `profiles/programa_vazao.json` (campos de pulso opcionais: lê v3 e v4).

| Instrumento | Conexão | Tabela | Variável CRBasic | Tipo | Natureza | `datalogger.Reading` | coluna `samples` | JSON (`latest`) | Onde aparece |
|---|---|---|---|---|---|---|---|---|---|
| Balança MK30K1 | C5/C6/G (RS-232) | `Balanca1s` | `Peso_g` | IEEE4, g | instantânea; `NAN` se falhou | `mass_g` | `mass_g` | `mass_g` | card da balança, gráfico, histórico |
| Balança | | `Balanca1s` | `StatusBal` | Long | 0 ok · 1 sem bytes · 2 sem linha · 3 inválida · 4 fora de −100…31000 g | `mass_status` (`ok`/`no_comm`/`invalid`) | `mass_status` | `mass_status` | pill do card, coluna Estado |
| Balança | | `Balanca1s` / `Resumo` | `LinhaNova`, `BaudInUse`, `LastLine`, `TotalOK`, `TotalFalha`, `FalhasSeguidas` | — | diagnóstico | não lidos | — | — | — |
| Termopar tipo T | 1H/1L | `Termopar1s` | `TempAgua_C` | IEEE4, °C | instantânea; junta fria `PTemp_C` | `temp_c`, `temp_status` | `temp_c`, `temp_status` | `temp_c` | card da temperatura, gráfico, histórico |
| Pluviômetro | P1/G | `Pluviometro1s` | `Pluvio_Basculadas_1s` | IEEE4 | basculadas no Scan | cada basculada → evento `tips` (chave `Pluviometro1s:<no>:<time>:<k>`) | tabela `tips` | `new_tips`, `tips_total` | card do pluviômetro, eventos, ensaio |
| Pluviômetro | | `Pluviometro1s` | `Pluvio_Total`, `Pluvio_Chuva_mm` | IEEE4 | acumulado do CRBasic (0,2 mm fixo; reinicia com o programa) | **ignorados de propósito** | — | — | — (o servidor aplica a resolução configurada) |
| MAG 5000 4–20 mA | RG1 | `Vazao1s` | `Flow_mA` | IEEE4, mA | bruta, mesmo fora de 4–20 | `cor_ma` (bruto), `cor_status` (`ok`/`invalid`/`no_comm`) | `cor_ma`, `cor_status` (`ok`/`out_of_range`/`fail`/`invalid`/`no_comm`) | `cor_ma`, `cor_status` | card do medidor (Corrente), histórico, exportação |
| MAG 5000 4–20 mA | | `Vazao1s` | `Flow_mV` | IEEE4 | derivado (mA×10) | não lido | — | — | — |
| MAG 5000 4–20 mA | | `Vazao1s` | `Flow_Status` | Long | 0 faixa · 1 abaixo · 2 acima · 3 NAN (v4) | 3 ⇒ `invalid`; o resto é reclassificado no servidor (`calc.classify_ma`) | — | — | — |
| MAG 5000 | | `Vazao1s` | `Flow_mode` (**m minúsculo**) | Long | 2 fixo (informativo) | `flow_mode` (`analog`) | `flow_mode` | `flow_mode` | — (o método é do servidor) |
| MAG 5000 pulsos (v4) | P2 | `Vazao1s` | `Flow_Pulsos` | IEEE4 | **contagem bruta no Scan**; 0 válido | `flow_pulses`, `pulse_status`; `flow_hz` derivado | `flow_pulses`, `flow_hz`, `pulse_status` | `flow_pulses` | card do medidor ("Pulsos no último Scan"), histórico, ensaio |
| MAG 5000 pulsos (v4) | | `Vazao1s` | `Flow_PulsosTot` | Long | acumulado desde o início do programa | `flow_pulses_total` | `flow_pulses_total` | `flow_pulses_total` | card ("Contador do datalogger"); N = Δ no ensaio |
| MAG 5000 pulsos (v4) | | `Vazao1s` | `Flow_PStatus` | Long | 0 válido · 1 primeiro Scan · 2 saturado · 3 > 12 kHz · 4 NAN | ≠ 0 ⇒ `pulse_status = invalid` | `pulse_status` | `pulse_status` | pill/estado |

Derivados no servidor (uma única vez, em L/min; a tela só converte a unidade): `flow_eval` (método configurado → `flow_lmin`, `flow_state`, `flow.active`), `trials.compute`
(N, Δt, V, Q, `timing`), `period_grav` (Δm → V → Q de referência), `precip_period`.

Estados do medidor (`flow_state`): `ok` · `na` (programa sem medidor) · `unavailable` (programa sem o canal do método) · `no_comm` · `invalid` · `fail` (< 3,6 mA) · `out_of_range` · `unconfigured` (K, faixa ou densidade ausentes).

**Zero não é ausência de dado.** Massa 0 g, 0 °C, 0 basculadas e 0 pulsos são medições válidas. `NAN`, status ≠ 0 ou falha de comunicação viram `null` + estado, nunca 0.

## Pendências no CRBasic
1. `SplitStr(NumLido(1),LastLine,"",3,0)` continua marcado "experimental" no programa; a linha real `"+   19.7g  \r\n"` foi confirmada em 22/10.
2. `Pluvio_mmPorBasculada = 0.2` "confirmar a resolução real" — o servidor usa `tip_resolution_mm` do `config.json` (0,2).
3. v4 e a proposta v5 não compilados.
