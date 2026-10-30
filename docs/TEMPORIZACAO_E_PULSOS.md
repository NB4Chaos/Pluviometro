# Temporização e pulsos no CR1000Xe — o que é possível, o que foi feito e o que fica pendente

Resposta às seções 4, 5 e 6.6 do pedido (`Prompt.md`). Legenda: **[CÓDIGO]** confirmado no código · **[DOC]** documentação oficial (Campbell Scientific:
*CR1000X Product Manual / Specifications* e *CRBasic Help: PulseCount, Scan, SlowSequence*; Siemens: *SITRANS F M MAG 5000/6000 Operating Manual*, datasheet FI 01)
· **[DADOS]** banco/log reais · **[FÍSICO]** depende da bancada.

## 1. Três tempos que não se confundem

| Tempo | O que é | Onde aparece |
|---|---|---|
| **Configurado** | o que o operador digitou (ms, s ou min), guardado em ms sem arredondar (`trial_duration_ms`) | card principal; `timing.cfg_ms` |
| **Efetivo** | o que os **carimbos do datalogger** cobrem: 1ª → última amostra do ensaio + 1 Scan (o registro em *t* cobre (t−Scan, t]) | `timing.eff_ms`; `flow.time_eff_ms` |
| **Resolução efetiva** | o intervalo do Scan do programa carregado (`scan_ms` do perfil; 1000 ms hoje) | `timing.resolution_ms`; mensagem de validação; casas decimais da tela |

`diff_ms = eff − cfg`. A tela mostra o tempo com as casas que a resolução permite (`Trials.dec4res`: 1000 ms → inteiro; 100 ms → 1 casa; 10 ms → 2; 1 ms → 3). O
relógio do PC (`timing.wall_ms`) é gravado **só como informação**; nenhum cálculo o usa.

## 2. Capacidade real do CR1000Xe (respostas às 8 perguntas da seção 5)

| # | Pergunta | Resposta | Fonte |
|---|---|---|---|
| 1 | Resolução temporal disponível | relógio em tempo real com resolução de **1 ms**; exatidão típica da ordem de minutos por ano sem GPS (ver nota) | [DOC] |
| 2 | Resolução dos carimbos | os carimbos (`TimeStamp`) têm fração de segundo; o servidor lê o campo `time` da DataQuery (`_ts_ms`) com ms | [DOC] + [CÓDIGO] |
| 3 | Intervalo de execução do programa em uso | **1 s** (`Scan(1,Sec,0,0)`); todas as tabelas gravadas a cada Scan | [CÓDIGO] |
| 4 | `PulseCount` detecta pulsos mais rápidos que o Scan? | **Sim**: contadores por hardware (24 bits) em P1/P2 acumulam entre execuções; `PulseCount` lê e zera o contador a cada Scan. Deve rodar em **todo** Scan principal (não em `If`, sub-rotina, `SubScan` ou `SlowSequence`) | [DOC] |
| 5 | Medir intervalos < 1 s com o programa atual? | **Não.** O menor intervalo observável é 1 registro = 1 s; durações como 500 ms são **recusadas** (`trials.start`, `set_config`), 1500 ms é aceita e quantizada (o resultado informa) | [CÓDIGO] |
| 6 | Limitações de aquisição/processamento/comunicação | no mesmo Scan de 1 s estão: laço serial da balança (até 100 `SerialIn` com timeout de 100 ms cada — pior caso ultrapassa o Scan e gera `SkippedScan`), `TCDiff` e `CurrentSE` com integração de 60 Hz e inversão (dezenas de ms cada). Consulta HTTP: ≈ 240 ms p50 por ciclo (4 tabelas) no log real; tabelas de 100 ms multiplicam por 10 o nº de registros a transferir | [CÓDIGO] + [DADOS] |
| 7 | Temporizador interno de maior resolução | `Scan` de até 1 ms; `Timer()`; `TimeIntoInterval`; `SubScan` (para medições, não para `PulseCount`). Nenhum está no programa em uso; a proposta v5 usa Scan de 100 ms | [DOC] |
| 8 | Incerteza/limitação do método de tempo | (a) quantização: início e fim do ensaio caem no instante de gravação de um registro → ±1 Scan em cada extremo; (b) o início do ensaio é "a próxima amostra" após o clique, logo a janela começa em um carimbo do datalogger e não no clique; (c) exatidão do relógio do datalogger (deriva) só é avaliável contra referência externa; (d) com N pulsos, ±1 pulso = ±100/N % do volume | [CÓDIGO] + [DOC] |

Nota sobre o relógio: a especificação do CR1000X dá a exatidão do relógio como ±3 min por ano (0 a 40 °C) [DOC]; com GPS a sincronização chega a ±10 µs [DOC].
Esses números são do fabricante; **não foram verificados na bancada**.

## 3. O que cada período configurável significa com o programa atual (Scan 1 s)

| Configurado | Aceito? | Resolução efetiva | Resultado |
|---|---|---|---|
| 1 000 ms | sim | 1000 ms | 1 registro |
| 500, 250, 100, 50, 10 ms | **não** (mínimo = `scan_ms`) | — | mensagem: "mínimo 1000 ms, que é a resolução efetiva do datalogger" |
| 1 500 ms | sim, com aviso | 1000 ms | 1 ou 2 registros; `eff_ms` 1000 ou 2000, `diff_ms` informado |
| 60 s | sim | 1000 ms | 60 registros |

Com a **proposta v5** (Scan 100 ms): 1000/500/250/100 ms aceitos com resolução 100 ms; 50 e 10 ms continuam recusados. Scan de 10 ms é tecnicamente possível no
CR1000Xe, mas **não** foi proposto: 100 registros/s por tabela e a necessidade de rever `ProcTime/MaxProcTime` e o transporte HTTP.

## 4. Como o sistema mede o tempo de um ensaio (implementado)

1. Clique em **Iniciar ensaio** → `trials.start`: `start_ts = último carimbo recebido + 1 ms` (a amostra que já estava na tela não entra); `end_ts = start_ts + cfg_ms`.
2. Cada ciclo grava as amostras com o carimbo do datalogger; `tick()` encerra quando chega um carimbo ≥ `end_ts` (ou após `GRACE_S` = 120 s pelo relógio do PC, estado *interrompido*).
3. `compute()` recebe só as linhas da janela e calcula `timing` (seção 1), `flow.time_eff_ms` (pulsos: do 1º ao último registro válido + Scan quando N vem do acumulado; soma das durações dos registros válidos quando N vem da soma).
4. O resultado é congelado (`trial_samples`/`trial_tips` + gatilhos do SQLite).

### Como verificar o temporizador (não implementado como "calibração": é um procedimento)
- Um gerador de pulsos de referência (frequência conhecida e rastreável) ligado a P2 (**respeitando ±20 V e o pull-up**, ver seção 6).
- Ensaios de 60 s, 600 s e 3600 s; comparar `N / f_ref` com `timing.eff_ms` e `timing.cfg_ms`. A diferença relativa é a estimativa da deriva do relógio do datalogger
  combinada com a quantização de ±1 Scan; use durações longas para que ±1 s seja desprezível (em 3600 s, ±0,03 %).
- Registrar `timing.first_sample_ts`/`last_sample_ts` e comparar com um cronômetro/relógio de referência lido no mesmo instante.
- **Nada disso declara o temporizador calibrado**: exige referência, repetições e avaliação de incerteza, feitas pelo laboratório.

## 5. Pulsos brutos: contagem, fórmulas e casos tratados (implementado)

- `Flow_Pulsos` (v4) = pulsos contados no Scan (bruto; 0 é válido). `Flow_PulsosTot` = acumulado desde o início do programa. `Flow_PStatus` 0 válido · 1 primeiro Scan · 2 saturado · 3 > 12 kHz · 4 sem leitura.
- No ensaio: `N = Tot_final − (Tot_inicial − pulsos_inicial)` quando o acumulado nunca diminuiu (= Contador_final − Contador_inicial do pedido; robusto a registros perdidos);
  senão `N = Σ Flow_Pulsos` dos registros válidos (robusto a reinício do contador; perde o que caiu em lacunas). `calc.pulse_count_window`.
- `V (L) = N / K(pulsos/L)`; `Q (L/min) = V / Δt(s) · 60`; `f (Hz) = N / Δt`. K convertido **uma vez** para pulsos/L (`calc.k_to_pulses_per_l`: pulsos/L, pulsos/m³, L/pulso, mL/pulso); a unidade de exibição só entra na tela (`Flow.convert`).
- Exemplo do pedido: K = 100 pulsos/L, N = 1250 em 60 s → V = 12,5 L; Q = 0,20833 L/s = 12,5 L/min (teste `test_vazao_por_pulsos_exemplo_do_pedido`).

| Caso | Tratamento | Teste |
|---|---|---|
| Nenhum pulso | N = 0, vazão 0 válida, aviso de < 200 pulsos | `test_nenhum_pulso_e_vazao_zero_valida_com_aviso` |
| Um pulso / múltiplos | N exato pela diferença do acumulado | `test_um_pulso_no_ensaio`, `test_multiplos_pulsos_…` |
| Pulsos antes do início / depois do fim | fora da janela [start, end): não entram (o início é a amostra seguinte ao clique) | `test_reinicio_do_ensaio_conta_so_a_janela_nova` |
| Perda de comunicação | registros sem o canal não viram zero; N pelo acumulado quando ele volta; fração válida < 95 % → *incompleto* | `test_perda_de_comunicacao_nao_vira_ausencia_de_pulsos` |
| Lacuna de registros | N pelo acumulado inclui os pulsos da lacuna; ensaio *incompleto* com motivo | `test_lacuna_de_registros_nao_perde_pulsos_pelo_acumulado` |
| Contador reiniciado (programa reiniciou) | N pela soma, aviso; **reinício + lacuna** → contagem incerta, ensaio *incompleto* | `test_contador_reiniciado_…` (2 testes) |
| Transbordamento | `Flow_PulsosTot` volta a 0 acima de 2×10⁹ no CRBasic → tratado como reinício; `Flow_Pulsos` ≥ 2²⁴ → `PStatus 2` → leitura inválida | `test_v4_pstatus_diferente_de_zero_…` |
| Período < 1 s | recusado com a resolução efetiva | `test_duracao_menor_que_a_resolucao_do_datalogger_e_recusada` |
| Sem K | pulsos brutos preservados; vazão/volume indisponíveis; ensaio *incompleto* | `test_sem_fator_k_mostra_pulsos_brutos_sem_inventar_vazao` |
| Programa v3 (sem canal) | "canal indisponível no programa", nunca zero; troca de método recusada (400) | `test_programa_v3_nao_tem_canal_de_pulsos` |

## 6. Ligação da saída de pulsos do MAG 5000 — o que falta confirmar [FÍSICO]

| Item | Confirmado | Pendente |
|---|---|---|
| Tipo de saída | digital, 0–10 kHz, ciclo 50 %; modos **ativo** (24 V DC / 30 mA, carga 1–10 kΩ) e **passivo** (3–30 V DC, ≤ 110 mA, carga 200 Ω–10 kΩ) [DOC] | qual modo está configurado/ligado na unidade instalada |
| Terminais | 56/57/58 na documentação Siemens [DOC] | atribuição exata, polaridade e se há jumper/configuração de modo |
| Entrada do CR1000Xe | P2: pull-up 100 kΩ a 5 V, baixo < 0,8 V, alto > 2,5 V, **máx. ±20 V**, 250 kHz [DOC] | — |
| Compatibilidade | saída **ativa de 24 V excede ±20 V: não ligar em P2** | valor do pull-up externo para o modo passivo (o interno de 100 kΩ está fora da carga ≤ 10 kΩ exigida pelo Siemens) ou condicionador/optoacoplador; alimentação externa |
| Frequência máxima | 10 kHz × 1 s = 10 000 pulsos/Scan, muito abaixo de 2²⁴; `Flow_PMaxHz = 12000` como limite de plausibilidade [CÓDIGO] | — |
| Fator K | [NÃO ENCONTRADO] em nenhum arquivo; `0,01 pulso/L` do `config.json` é sem origem | ler no menu de saídas do MAG 5000 (volume por pulso) e informar em Configurações com a unidade correta |

Informações necessárias para fechar: manual de operação do MAG 5000 (capítulo de ligações elétricas da saída digital), etiqueta/menu da unidade (modo da saída, K),
e uma medição na bancada (tensão da saída em repouso e em pulso, com o pull-up escolhido) antes de ligar em P2.

## 7. Troca de modo analógico ↔ pulsos: o que exige o quê

- **Só software** (implementado): a escolha no card do medidor grava `flow_method` no servidor e recalcula a vazão a partir do dado bruto já lido; o CR1000Xe mede os dois canais
  em todo Scan (programa v4). Nada é escrito no datalogger. O card distingue *solicitado* (gravado) de *ativo* (confirmado por uma amostra calculada com o método).
- **Exige o datalogger**: o programa em uso (v3) **não tem** `PulseCount` em P2. Para pulsos é preciso compilar e carregar o v4 (`docs/CRBASIC_V4_PULSOS.md`). O seletor avisa
  ("canal indisponível no programa") e recusa a troca; não simula.
- **Exige a bancada**: ligação da saída de pulsos (seção 6) e o K.
