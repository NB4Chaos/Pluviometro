# Mapa CRBasic → API → interface

Fonte: `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X` (em uso, perfil `programa_vazao`) e `crbasic/Pluviometria_v4_vazao_pulsos.CR1X`
(novo, mesmo perfil). Scan de 1 s. Os nomes de campo são os declarados no CRBasic, com a grafia exata (`Flow_mode`, com “m” minúsculo).

| Instrumento | Tabela | Variável | Tipo | Unidade | Natureza | Campo no JSON (`/api/summary` → `latest`) | Onde aparece |
|---|---|---|---|---|---|---|---|
| Balança MK30K1 | `Balanca1s` | `Peso_g` | Float (IEEE4) | g | Instantânea; `NAN` se a leitura falhou | `mass_g` | Card Massa, gráfico, histórico |
| Balança | `Balanca1s` | `StatusBal` | Long | — | 0 ok · 1 sem bytes · 2 sem linha completa · 3 linha inválida · 4 fora de −100…31000 g | `mass_status` (`ok`/`no_comm`/`invalid`) | Indicador do card, coluna Estado |
| Balança | `Balanca1s` | `LinhaNova`, `BaudInUse`, `LastLine` | Boolean / Long / String | — | Diagnóstico | não usados | — |
| Balança | `Resumo` (10 min) | `TotalOK`, `TotalFalha`, `FalhasSeguidas` | Long | contagem | Diagnóstico | não usados | — |
| Termopar tipo T | `Termopar1s` | `TempAgua_C` | Float | °C | Instantânea; `NAN` se falhar | `temp_c` | Card Temperatura, gráfico, histórico |
| Termopar | `Termopar1s` | `PTemp_C` | Float | °C | Temperatura do painel (referência) | não usado | — |
| Pluviômetro | `Pluviometro1s` | `Pluvio_Basculadas_1s` | Float | basculadas/s | Contagem do último segundo | cada basculada vira um evento (`new_tips`) | Total, intervalos, intensidade |
| Pluviômetro | `Pluviometro1s` | `Pluvio_Total`, `Pluvio_Chuva_mm` | Float | basculadas, mm | **Acumulado do CRBasic, reinicia com o programa** | **ignorados de propósito**: o servidor conta os eventos e aplica a resolução da tela | — |
| Medidor de vazão (v3 e v4) | `Vazao1s` | `Flow_mA` | Float | mA | corrente medida em RG1 (`CurrentSE`), gravada **mesmo fora de 4–20 mA** | `cor_ma` | sinal do card, histórico, exportação |
| idem | `Vazao1s` | `Flow_Status` | Long | — | 0 = 4 a 20 mA · 1 abaixo · 2 acima · 3 NAN (este só na v4) | `ma_code` | diagnóstico |
| idem | `Vazao1s` | `Flow_mV` | Float | mV | `Flow_mA × 10`, derivado (compatibilidade) | não usado | — |
| idem | `Vazao1s` | `Flow_mode` | Long | — | sempre 2 (legado: o método é escolhido no servidor) | não usado | — |
| Medidor (só v4) | `Vazao1s` | `Flow_Pulsos` | Float | pulsos | contagem desde o Scan anterior (**não** é Hz) | `flow_pulses` | sinal do card, histórico |
| idem | `Vazao1s` | `Flow_PulsosTot` | Long | pulsos | acumulado das contagens válidas desde o início do programa | `pulses_total` | volume dos ensaios, diagnóstico |
| idem | `Vazao1s` | `Flow_PStatus` | Long | — | 0 ok · 1 primeiro Scan · 2 saturado · 3 acima de 12 kHz · 4 NAN | `pulse_code` | estado do canal de pulsos |

## Calculado no servidor (nunca no CRBasic)

| Grandeza | Fórmula | Campo | Observação |
|---|---|---|---|
| Janela de contagem | intervalo até o registro anterior de `Vazao1s` | `flow_dt_ms` | > 2,5 s ou ausente: 1 s nominal, marcado "janela presumida" |
| Frequência | `Flow_Pulsos ÷ janela` | `flow_hz` | gravada para os dois métodos (os dois canais ficam no banco) |
| Vazão por pulsos | `f ÷ K × 60` (L/min) | `flow.lmin` | K em pulsos/L; sem K: "não configurado", nunca um K presumido |
| Vazão analógica | `q4 + (I − 4)/16 × (q20 − q4)`, convertida para L/min | `flow.lmin` | tolerância (padrão 0,02 mA) nos limites: escala presa em 4/20 mA, marcada "no limite" |
| Estado da corrente | < 3,6 mA falha · 3,6–(4−tol) abaixo · dentro ok/no limite · > 20+tol acima | `flow.ma_class` | 3,6 mA: NAMUR NE 43; o MAG 5000 sinaliza alarme com 1,3/2/3 mA |
| Método usado na amostra | `config.json → flow_method` | `flow_mode` | "analog" ou "pulse"; só vira **ativo** quando uma amostra é calculada com ele |
| Estado gravado | dado válido ou não (independe de configuração) | `cor_status` | ok · no_comm · invalid · out_of_range (inclui falha) · unavailable |

Bloco `flow` do evento `sample` (Socket.IO) e de `latest`: `requested`, `active`, `confirmed`, `locked`, `has` (canais do programa),
`method`, `state`, `reason`, `lmin`, `clamp`, `ma`, `ma_class`, `pulses`, `hz`, `window_s`, `window_assumed`, `resolution_lmin`,
`channels` (o mesmo para cada canal) e `crosscheck` (`diff_pct`, `suspect`).

**Zero não é ausência de dado.** Massa 0 g, 0 °C, 0 basculadas e 0 pulsos são medições válidas. `NAN`, estado ≠ 0 ou falta de
comunicação viram `null` + estado, nunca 0.

## Pendências no CRBasic

1. A extração do peso (`SplitStr(NumLido(1),LastLine,"",3,0)`) segue marcada como **experimental** no programa. Valide com uma linha real
   da MK30K1 (campo `LastLine`).
2. `Pluviometria_v4_vazao_pulsos.CR1X` **não foi compilado** nesta máquina. Compile e confira `Status.SkippedScan` depois de carregar.
3. Ligação dos pulsos: ver `CRBASIC_V4_PULSOS.md` (não validada).
4. `crbasic/Pluviometria_Vazao.CR1X` é histórico (nunca foi carregado; esquema incompatível com o perfil atual). Não use.
