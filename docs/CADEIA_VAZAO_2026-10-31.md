# Cadeia de medição da vazão por pulsos — investigação, correções e incerteza (31/10/2026)

Pedido: "Correção dos cálculos de vazão e aprimoramento da resolução temporal e metrológica". Método: rastrear a cadeia inteira
(CRBasic → tabela → `datalogger.py` → `calc.py` → `trials.py` → API → JavaScript → card), demonstrar cada passo com números do
banco e dos testes, e só então alterar. Legenda: **[CÓDIGO]** confirmado no código · **[DADOS]** banco do emulador · **[DOC]** especificação.

## 1. Qual era o erro original no cálculo da vazão

**Nenhuma fórmula da cadeia estava dimensionalmente errada.** O rastreio ponta a ponta (seções 5–7) mostra uma única aplicação de K, janela
real de contagem, N pela diferença do contador acumulado e Q = V ÷ Δt efetivo. O banco da rodada de 30/10 confirma: 100 pulsos/s com
K = 1000 pulsos/L → 6,000 L/min; ensaio de 500 pulsos em 5 s → 0,500 L e 6,000 L/min **[DADOS]**.

O que fazia o resultado *parecer* errado, e o que foi de fato corrigido:

| # | Achado | Onde | Efeito visível | Correção |
|---|---|---|---|---|
| A | Cobertura do ensaio deslocada em 1 Scan: o registro em *t* era tratado como cobrindo [t, t+Scan), mas o `PulseCount` conta (t−Scan, t] | `calc.covered_intervals` usado por `trials.compute` | "coberto **4 s de 5 s**" com 5 registros completos; ensaios curtos pareciam incompletos | `covered_intervals(..., backward=True)` só nos ensaios; períodos da tela inalterados |
| B | Arredondamento prematuro a 3 casas **em L/min**, antes da conversão de unidade na tela | `app.py` `/api/series` e `flow_stats` (resumo, gráfico, rodapé do histórico) | 0,0006 L/min (0,6 mL/min) virava 0,001 ou 0,000; em m³/h a 4ª casa sumia | vazão em L/min com 9 casas (1 nL/min); mA e Hz continuam com 3 |
| C | Carimbos de início/fim com ",001" artificial (início = último carimbo + 1 ms) exibidos com milissegundos | `trials.js`, `relatorio.html` | falsa precisão de 1 ms com Scan de 1 s | milissegundos só quando `resolution_ms < 1000` |
| D | Emulador de testes: 12 mA (= 50 L/min na faixa 0–100) e 100 Hz com K = 1000 pulsos/L (= 6 L/min) | `tests/fake_programa_atual.py` + configuração do cenário | "diferença pulsos − analógico: −88 %" nas capturas de 30/10 | K coerente no cenário (120 pulsos/L → 0,0 %); o emulador não é alterado (dado fictício, não operacional) |
| E | Nenhuma incerteza calculada; só "resolução (1 pulso)" | — | sem qualificação do resultado | `calc.pulse_uncertainty` (seção 11) |

## 2. Em quais arquivos estava
A: `calc.py` (`covered_intervals`) via `trials.py` (`compute`). B: `app.py` (`series`, `flow_stats`). C: `static/js/trials.js` (`timingHtml`), `templates/relatorio.html`.
D: configuração do cenário de navegador (fora do produto). E: inexistente (novo em `calc.py`/`trials.py`).

## 3. Qual era a fórmula anterior (inalterada, porque estava certa)
- Instantânea (`calc.flow_reading`): f = pulsos ÷ janela_s; Q(L/min) = f ÷ K(pulsos/L) × 60. janela_s = intervalo até o registro anterior da tabela `Vazao1s` (`__dt_ms`), ou o Scan nominal se não houver anterior contíguo (marcado "presumida").
- Ensaio (`trials.compute`): N = Tot(último) − [Tot(primeiro) − pulsos(primeiro)] = acumulado antes do 1º registro até o último; V = N ÷ K; Δt = (t_último − t_primeiro) + janela do 1º registro; Q = V ÷ Δt × 60.
- Cobertura (A): registro em t → [t, t+Scan). **Esta era a convenção errada para contagens** e foi trocada.
- Resumo/série (B): `round(Q_L/min, 3)`. **Trocado.**

## 4. Fórmula corrigida / confirmada
Q(L/min) = N × 60 ÷ (K × t_s), com K sempre em pulsos/L internamente e t_s o tempo efetivamente coberto pelos registros do datalogger.
Cobertura do ensaio: registro em t → [t−Δ, t), Δ = intervalo até o registro anterior (≤ 2,5 s) ou o Scan. Nada mais mudou nas fórmulas.

## 5. Como os pulsos brutos são utilizados
CRBasic v4 `PulseCount(Flow_Pulsos,1,P2,3,0,1,0)` (alta frequência, pull-up) lê e zera o contador de hardware a cada Scan **[CÓDIGO]**; `Flow_PulsosTot`
acumula. `datalogger.py` entrega `flow_pulses` (contagem bruta, nunca frequência), `flow_pulses_total` e `flow_dt_ms`. `app.py` grava os três sem
alterar e guarda também `flow_hz = pulsos ÷ janela` para o gráfico. A tela mostra a contagem como inteiro (`Fmt.int`) e o contador do datalogger.
No ensaio o estado inicial é o contador acumulado do último registro **anterior** à janela (não o clique) e o final é o do último registro
dentro dela: N = diferença, imune a registros perdidos no meio; se o acumulado reiniciar, cai para a soma dos registros e avisa.

## 6. Como o volume é calculado
V(L) = N ÷ K. K é digitado em pulsos/L, pulsos/m³, L/pulso ou mL/pulso e convertido **uma vez** para pulsos/L ao salvar (`calc.k_to_pulses_per_l`:
pulsos/m³ → ÷1000; L/pulso → 1/V; mL/pulso → 1000/V); o ensaio congela o K em pulsos/L. Testado com N = 0, 1, 100, 1250 e os quatro tipos de unidade.

## 7. Como a vazão é calculada
Instantânea: pulsos do registro ÷ janela real ÷ K × 60. Ensaio: N ÷ K ÷ Δt_efetivo × 60, nunca a média das instantâneas (elas só dão mín/máx).
Exemplo obrigatório: 1250 pulsos, K = 100 pulsos/L, 60 s → V = 12,5 L, Q = 12,5 L/min (`test_exemplo_de_validacao_1250_pulsos_60_s_k_100`).
Conversão para a unidade de exibição (L/h, mL/min, m³/h…) acontece **só na tela** (`Flow.convert`), com a mesma tabela do servidor (testada).

## 8. Como a frequência é determinada
- **Instantânea** (minicard "Frequência (último Scan de 1,00 s)"): pulsos do último registro ÷ janela real; 0 pulsos válidos = **0,0 Hz**; sem registro atual
  ou leitura inválida = "—". Não é estimada da vazão nem da faixa configurada.
- **Média do ensaio** (etiqueta do mesmo minicard e linha nos detalhes): N ÷ Δt_efetivo. As duas ficam lado a lado para não confundir instantânea com acumulada.
- Variável durante o ensaio: `test_frequencia_variavel_no_ensaio…` (0→100→0 Hz) confirma média = N/Δt e mín/máx = 0 e 100 Hz.

## 9. Qual resolução temporal foi efetivamente alcançada
**1000 ms, igual ao Scan do programa em uso.** Os carimbos da tabela `Vazao1s` vêm como `HH:MM:SS.00` (DataInterval de 1 s) **[DADOS]**; o CR1000X
marca registros com resolução de ms **[DOC]**, mas o programa só grava um por segundo. O software já trabalha em ms (duração, carimbos, `time_eff_ms`,
`resolution_ms`) e, com um programa de Scan 100 ms (proposta v5), passa a resolver 100 ms sem alteração (`test_tempo_efetivo_segue_a_resolucao_do_programa`
com `scan_ms=100`). "998,7 ms" **não é alcançável** com o hardware configurado como está; a tela não exibe ms quando a resolução é 1 s.
Alternativa tecnicamente viável para tempo abaixo do Scan: `TimerIO` nos terminais C do CR1000X (período/frequência com resolução de µs) para a
frequência; o volume continuaria vindo do contador. Exige novo programa e validação de bancada.

## 10. Quais limitações físicas existem
- Quantização do tempo = 1 Scan (1 s) nas duas bordas do ensaio; a contagem dentro da janela é exata (contador de hardware, 24 bits, 250 kHz) **[DOC]**.
- Fase dos pulsos nas bordas: ±1 pulso → 100/N % (1250 pulsos: 0,08 % de faixa, 0,046 % como incerteza-padrão).
- Relógio do CR1000X: ±3 min/ano ≈ 5,7 ppm **[DOC]**; só avaliável contra referência externa.
- Entrada P2: ±20 V, pull-up interno de 100 kΩ (fora da carga 200 Ω–10 kΩ exigida pelo medidor → pull-up externo); frequência máxima do medidor 10 kHz.
- O tempo de parede do servidor (polling, Socket.IO) **não entra** em nenhum cálculo: só é registrado como informação (`timing.wall_ms`).

## 11. Alterações na apresentação da incerteza — REMOVIDAS em 01/11
Por decisão do laboratório, o sistema **não calcula incerteza** (nem combinada, nem expandida, nem componentes). Tudo o que esta seção descreve
foi retirado em 01/11/2026 (`docs/ENTREGA_2026-11-01.md`, item 1); a avaliação de incerteza é feita na planilha a partir dos dados brutos,
do tempo efetivo e dos parâmetros congelados do ensaio. O texto abaixo fica só como registro do que existiu entre 31/10 e 01/11.

### (histórico) Alterações na apresentação da incerteza
Novo `calc.pulse_uncertainty(N, K, t, u_K%)`, gravado em `flow.uncertainty` do ensaio por pulsos:
- contagem: u = 1/(N·√3) (±1 pulso, retangular); relógio: 5,7 ppm; **K: só se informado** (campo opcional "Incerteza do fator K (%)" no painel do medidor,
  `flow_k_uncertainty_pct`); combinação em quadratura; u(V) sem a parcela do relógio.
- Exibição: detalhes do ensaio (componentes, combinada, "Q ± u", "V ± u"), card ao encerrar ("Incerteza-padrão da vazão (±1 pulso, relógio, K)" ou
  "K não informado") e relatório. 2 algarismos significativos; a resolução de exibição da vazão continua configurável (`flow_decimals`).
- Exemplo: 1250 pulsos, K = 100 ± 0,5 %, 60 s → u_N = 0,046 %, u_rel = 0,00057 %, u_K = 0,5 % → u_c = 0,50 % → 12,5 ± 0,063 L/min. Sem u_K: 0,046 % → ± 0,0058 L/min.
- O que **não** foi feito: incerteza do canal analógico (exige exatidão do ADC e do shunt), repetibilidade, incerteza expandida (k=2) e da balança: planilha.

Arredondamento: cálculos internos em ponto flutuante de 64 bits sem arredondar; servidor devolve L/min com 9 casas (antes 3); a tela arredonda só na
apresentação (`Fmt.num`, casas configuradas; `Fmt.sig` para incerteza e K).

## 12. Arquivos modificados
`calc.py` (`covered_intervals(backward)`, `pulse_uncertainty`, `CLOCK_REL`) · `trials.py` (cobertura do ensaio, `uncertainty`, `k_unc_pct` no snapshot) ·
`app.py` (sem arredondamento prematuro; `flow_k_uncertainty_pct` na configuração) · `static/js/flow.js` (minicard Frequência, incerteza no card,
campo u_K no painel) · `static/js/trials.js` (incerteza nos detalhes, carimbos por resolução, `cfgText`) · `templates/index.html` (campo u_K) ·
`templates/relatorio.html` (temporização por resolução, incerteza) · `tests/test_cadeia_vazao.py` (novo, 61 testes) · `docs/CADEIA_VAZAO_2026-10-31.md`.

## 13. Testes executados e resultados
| Teste | Resultado |
|---|---|
| `pytest tests` | **300 passed** (239 anteriores + 61 novos) |
| Volume: 0, 1, 100, 1250 pulsos; K em pulsos/L, pulsos/m³, L/pulso, mL/pulso; K inválido | ok |
| Vazão: 0…10 000 pulsos; janelas de 100 ms, 500 ms, 1 s, 2 s; unidades L/min…m³/min; mássica exige densidade; próximo de zero sem arredondar | ok |
| Frequência: 0, 1, 10, 50, 100 Hz; 100 pulsos em 2 s = 50 Hz; variável no ensaio (média = N/Δt) | ok |
| Temporização: 10/100/500 ms recusados e 1/10/60 s aceitos com Scan 1 s; 100/500/1000 ms aceitos com Scan 100 ms (software); tempo medido ≠ configurado quando o ensaio para antes | ok |
| Incerteza: componentes do exemplo 1250, K só quando informado, propagação para Q e V, consistência dimensional | ok |
| Cobertura: 5 registros = 5 s (antes 4,001 s); convenção antiga preservada nos períodos da tela | ok |
| API: `/api/series` e `/api/summary` preservam 0,0006 L/min; `flow_k_uncertainty_pct` aceita "0,5", vazio e recusa 150 | ok |
| e2e `e2e_ensaio`, `e2e_programa_atual`, `e2e_cr1000x_elus_calib` | TUDO OK ×3 |
| Navegador (Playwright, emulador v4, K = 120 pulsos/L coerente com 12 mA): minicard Frequência "100,0 Hz · média 100,0 Hz", 500 pulsos → 4,167 L, 50,000 L/min, u = 0,51 %, ± 0,26 L/min, "coberto 5 s de 5 s", diferença pulsos − analógico 0,0 %, sem erros JS | ok (`docs/capturas_2026-10-31/cadeia_*.png`) |

Antes × depois (mesmos dados): cobertura 4,001 s → 4,999 s de 5 s; série com 1 pulso/s e K = 100 000 pulsos/L: 0,001 (ou 0,0) → 0,0006 L/min;
início do ensaio "11:58:21,001" → "16:56:21"; vazão do ensaio 6,000 L/min → 6,000 L/min (inalterada, porque já estava certa).
