# Mapa CRBasic → API → interface

Fonte: `crbasic/Pluviometria.CR1X`. Scan de 1 s.

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
| Medidor de Vazão (programa atual) | — | **não existe no programa** | — | — | — | `cor_status = null`, `flow_state = "na"` | "Aguardando integração" |
| Medidor de Vazão (programa novo) | `Vazao1s` | `Flow_Mode` | Long | — | 1 pulsos P2 / 2 analógico 2H/2L | `flow_mode` (`pulse`/`analog`) | rótulo do modo |
| idem | `Vazao1s` | `Flow_Pulsos_1s` | Float | pulsos no Scan | contagem bruta | `flow_pulses` | totais do ensaio, histórico |
| idem | `Vazao1s` | `Flow_Freq_Hz` | Float | Hz | pulsos ÷ Scan | `flow_hz` | vazão = Hz ÷ K × 60 |
| idem | `Vazao1s` | `Flow_mV`, `Flow_mA` | Float | mV, mA | tensão no shunt; mA = mV ÷ shunt | `cor_ma` (mA) | vazão pela faixa 4–20 mA |
| idem | `Vazao1s` | `Flow_Status` | Long | — | 0 ok; 1–5 inválido (ver `CRBASIC_VAZAO.md`) | `cor_status` | indicador e histórico |

Calculadas no backend: total de basculadas, precipitação (mm) = basculadas × resolução da tela, intensidade (mm/h) e vazão pela inclinação da massa (regressão linear numa janela configurável, só exibição).

**Zero não é ausência de dado.** Massa 0 g, 0 °C e 0 basculadas são gravados como medição válida. `NAN`, status ≠ 0 ou erro de comunicação viram `null` + estado (`no_comm`/`invalid`), nunca 0.

## Pendências no CRBasic

1. **`crbasic/Pluviometria.CR1X`:** o arquivo `Pluviometria.CR1X` da raiz termina com uma linha de três crases depois de `EndProg`, que não é CRBasic. Removi só essa linha na cópia desta pasta. **Não sei se ela impedia a compilação**: os seus dados reais mostram que um programa com essa estrutura rodou no datalogger (pode ter sido outra versão do arquivo). Confira no CRBasic Editor.
2. A extração do peso (`SplitStr(NumLido(1),LastLine,"",3,0)`) está marcada como **experimental** no próprio programa. Valide com uma linha real da MK30K1 (campo `LastLine`) antes de confiar em `Peso_g`.
3. **Medidor de Vazão:** o programa atual não tem variável de vazão. O programa novo (`crbasic/Pluviometria_Vazao.CR1X`, perfil `programa_vazao`) acrescenta a tabela `Vazao1s`; veja `docs/CRBASIC_VAZAO.md`.
