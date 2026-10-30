# Diagnóstico técnico — 30/10/2026 (Etapa 1)

Revisão do sistema de calibração (pluviômetro + medidor de vazão) da Elus Instrumentação, datalogger Campbell Scientific **CR1000Xe**.
Pedido: `Prompt.md` (raiz). Material recebido: `Pluviometro.rar` (projeto + `backup/` + `docs/` com o PDF do TI). Este documento registra o que foi
**encontrado antes de qualquer alteração**; o plano está em `docs/PLANO_2026-10-30.md` e a entrega em `docs/ENTREGA_2026-10-30.md`.

Legenda: **[CÓDIGO]** confirmado no código · **[DOC]** confirmado em documentação oficial · **[DADOS]** confirmado no banco/log reais ·
**[FÍSICO]** depende de validação na bancada · **[NÃO ENCONTRADO]**.

## 0. Resumo executivo

1. **Git**: o repositório `NB4Chaos/Pluviometro` estava **vazio** (branch sem commits); não existia histórico para comparar. O projeto como recebido foi
   gravado como primeiro commit (`Baseline`) para servir de forma de recuperação. Banco, cursor e logs ficam fora do repositório (`.gitignore`).
2. **Identidade visual**: `static/app.css`, `templates/index.html` e `static/js/*` da raiz são **byte a byte iguais** aos do backup de referência
   (`backup/monitor-pluviometro_simplificado/monitor-pluviometro`). A tipografia na raiz **já é a original** (Urbanist 300/400/500/600, azul
   `#0B1F4B`, amarelo `#FFC20E`, cards de 28 px). A interface "com fontes alteradas" que o pedido descreve corresponde a uma destas duas coisas, nenhuma
   delas presente na raiz: (a) o projeto **Linha de Ar / CFW500** que ocupava a pasta até 29/10 (`Inter, Segoe UI, Arial`, raio 9 px, peso 800 —
   preservado em `backup/linha-de-ar_cfw500_2026-10-29/`); (b) a interface refeita pelo TI (Rev. 1, painel lateral com abas, `flow.js`), cujo pacote
   **não está nesta máquina**. Conclusão: **não há nada a reverter nos tokens**; a tarefa visual é manter esses tokens e aplicar a limpeza + o card dinâmico.
3. **PDF do TI** (`docs/Elus_Monitor_Relatorio_Tecnico_Rev1_2026-10-28.pdf`, 18 páginas, único PDF): lido integralmente (seção 4). As correções descritas
   (registro-âncora, instância única, agenda absoluta, classificação do 4–20 mA, configuração parcial, API do medidor, CRBasic v4) **já estão
   reimplementadas** no código da raiz pela sessão de 29/10 e cobertas por 141 testes que passam. A interface do TI (seção 2.5 do PDF) **não** foi
   reproduzida, e o pedido atual não a quer.
4. **O que ainda faltava** (e é o objeto desta sessão): card principal dinâmico por método, seletor Analógico/Pulso dentro do card, pulsos **brutos** na
   tela (hoje o card mostra "Sinal: X Hz", um valor derivado), duração do ensaio em ms/s/min com resolução efetiva declarada, redução da poluição visual,
   registro de temporização no resultado do ensaio, e a documentação de temporização/pulsos referida pelo plano de 29/10 (arquivos que não existiam).

## 1. Diretórios e versões (como recebidos)

| Local | Conteúdo | Uso |
|---|---|---|
| raiz | monitor completo (app.py 1053 linhas, datalogger.py, calc.py, trials.py, static/, templates/, profiles/, crbasic/ (6 programas), tests/ (141 testes + 3 e2e), tools/, docs/ (17 arquivos), config.json, banco 28/10) | **local de trabalho** |
| `backup/monitor-pluviometro_simplificado/monitor-pluviometro/` | versão anterior (22–28/10): referência visual | só leitura; **igual** à raiz em static/ e templates/ |
| `backup/monitor-pluviometro_base_2026-10-29/` | cópia idêntica ao simplificado (diff vazio) | só leitura |
| `backup/linha-de-ar_cfw500_2026-10-29/` | projeto CFW500/Modbus que estava na raiz (outro sistema) | não faz parte do monitor |
| `backup/Pluviometria_v3_com_vazao_4-20mA.CR1X` | programa **em uso** no CR1000Xe segundo o PDF do TI | copiado em `crbasic/` |
| `docs/*.pdf` | relatório do TI Rev. 1 (28/10/2026) | lido |

## 2. Identidade visual: comparação

| Elemento | raiz (hoje) | backup (referência) | CFW500 (o que estava na pasta) |
|---|---|---|---|
| Fonte | `Urbanist` 300/400/500/600 (Google Fonts, `index.html:11`) | idêntico | `Inter, Segoe UI, Arial` |
| Tokens | `--navy #0B1F4B --logo #071E40 --yellow #FFC20E --muted #5B6B8C --bg #F5F5F8` (`app.css:1`) | idêntico | `#0b1f3a`, `#f5c400` |
| Cards | raio 28 px, sem borda/sombra, gap 24 px; hero `#06122E` com glow amarelo | idêntico | raio 16 px, borda, sombra |
| Títulos | h1 46 px/400; h2 22 px/500; valor `.big` 64–72 px/300 | idêntico | h1 21–29 px; valores 22–32 px/800 |
| Botões/campos | pílulas 999 px, 44 px; inputs raio 14 px | idêntico | raio 9 px, peso 800 |

Verificação executada: servidor + emulador v4, captura Chromium 1440 px e 400 px; `getComputedStyle(body).fontFamily = "Urbanist, system-ui, sans-serif"`;
valor principal do hero 72 px / peso 300; sem rolagem horizontal em 400 px; nenhum erro de JavaScript.

Poluição visual encontrada no dashboard (a reduzir sem perder função): três indicadores de estado quase iguais no topo (`Recebendo dados`, `Dados reais do
datalogger`, `Comunicação OK` em cada card); no método Comparativo o Medidor de Vazão fica num card secundário **abaixo**, com "Média do período" repetida em
três cards; parágrafo de 5 linhas sobre massa ejetada dentro do pluviômetro; `Exibir` (Precipitação | Vazão) e `Método` lado a lado confundem; duração em
segundos inteiros, sem unidade selecionável; nenhum lugar para escolher Analógico/Pulso nem para ver os pulsos brutos.

## 3. Hardware e caminho dos dados (programa em uso: `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X`)

| Equipamento | Sinal | Conexão no CR1000Xe | Instrução CRBasic | Variável | Tabela | Situação |
|---|---|---|---|---|---|---|
| Balança MK30K1 | RS-232 9600 bps, formato 3 (8N1, TTL/RS-232 de C5–C6) | TX balança → **C6**, RX balança → **C5**, GND → **G** (`ComC5`) | `SerialOpen(ComC5,9600,3,0,1000,0)`; laço `SerialIn` até 100 linhas/Scan; `SplitStr`; sinal pelo 1º caractere | `Peso_g` (IEEE4), `StatusBal` (0 ok · 1 sem bytes · 2 sem linha · 3 inválida · 4 fora de −100…31000 g), `LastLine` | `Balanca1s` (1 s) | [CÓDIGO]; pinagem confirmada no cabeçalho do programa e no pedido; formato da linha real confirmado em 22/10 |
| Termopar tipo T | mV diferencial | **1H (+)**, **1L (−)** | `TCDiff(TempAgua_C,1,mV200C,1,TypeT,PTemp_C,True,0,60,1,0)`; junta fria `PanelTemp(PTemp_C,4000)`; integração 60 Hz; inversão ligada | `TempAgua_C`, `PTemp_C` | `Termopar1s` (1 s) | [CÓDIGO] |
| Pluviômetro | contato seco | **P1** – **G** | `PulseCount(Pluvio_Basculadas_1s,1,P1,1,0,1,0)`: PConfig 1 = fechamento de contato **com pull-up interno** (100 kΩ a 5 V — explica os ≈5 V medidos com contato aberto), POption 0 = contagem | `Pluvio_Basculadas_1s`, `Pluvio_Total`, `Pluvio_Chuva_mm` (`Const Pluvio_mmPorBasculada = 0.2`, "confirmar") | `Pluviometro1s` (1 s) | [CÓDIGO]; o servidor ignora `Pluvio_Chuva_mm` e aplica a resolução configurada (0,2 mm no `config.json`) |
| MAG 5000, 4–20 mA | corrente | **RG1** (entrada de corrente nativa do CR1000Xe, shunt interno de 10 Ω) | `CurrentSE(Flow_mA,1,mV200,RG1,True,0,60,1,0)`; `Flow_mV = Flow_mA×10` (derivado); `Flow_Status` 0/1/2 por 4–20 mA | `Flow_mA`, `Flow_mV`, `Flow_Status`, `Flow_mode` (=2, **m minúsculo**) | `Vazao1s` (1 s) | [CÓDIGO] + [DADOS]: 144 amostras `analog/ok` no banco real entre 4,0106 e 4,0109 mA (medidor parado). **O pedido cita "2H/2L e shunt"**: isso é o programa `Pluviometria_Vazao.CR1X` (VoltDiff em 2H/2L, `Flow_Shunt_ohm`), que **não é o programa em uso** segundo o PDF do TI |
| MAG 5000, pulsos | digital | **P2** no programa v4 (ligação **não validada**) | `PulseCount(Flow_Pulsos,1,P2,3,0,1,0)` (PConfig 3 = alta frequência com pull-up; POption 0 = contagem) | `Flow_Pulsos`, `Flow_PulsosTot`, `Flow_PStatus` | `Vazao1s` (v4) | [CÓDIGO] no v4, **não compilado**; [FÍSICO] seção 6 |

Datalogger: `CR1000Xe` confirmado nos cabeçalhos dos 6 programas CRBasic, no PDF do TI e no emulador (`"model": "CR1000X"`). **Versão do OS e do programa
carregado: [NÃO ENCONTRADO]** — não há exportação da tabela `Status` nos arquivos; `datalogger.health()` lê `ProgName` em produção (`/api/diag`).

Fluxo: Scan 1 s → `CallTable` (5 tabelas circulares de 20 000 registros ≈ 5,5 h) → `DataQuery since-record` por tabela a partir do registro-âncora
(HTTP, conta somente leitura, senha no Gerenciador de Credenciais do Windows) → `datalogger.py` casa as tabelas por horário (±500 ms) e entrega
`Reading` com o dado **bruto** → `app.store_batch` grava `samples`/`tips` (SQLite WAL; releitura só completa campos vazios) → `flow_eval` calcula a
vazão pelo método configurado → Socket.IO `sample` + `/api/summary` (2 s) → `app.js` renderiza.

## 4. Relatório do TI (Rev. 1, 28/10/2026): o que diz × o que o código tem

| Seção do PDF | Alteração descrita | Presente na raiz? | Decisão |
|---|---|---|---|
| 2.1 | registro-âncora; só reinício real quando a âncora some/muda de horário; gravação só completa campos vazios; leitura paralela (desligada) | **Sim** (`datalogger._pull`, `_anchor`, `UPSERT_SQL`); leitura paralela **não** (não era exigida) | manter |
| 2.2 | instância única; agenda por horário absoluto com fase e nova tentativa em 120 ms; `/api/flow`, `/api/flow/method`; configuração parcial; origem dos parâmetros no log; sem `print` | **Sim** (`single_instance`, `acquire`, rotas, `set_config`) | manter |
| 2.3 | método escolhido no servidor; mA bruto sempre gravado; tolerância 0,02 mA sem extrapolar; falha < 3,6 mA; pulsos f = N/Δt, Q = 60·f/K, V = ΔN/K; K em 4 unidades; K = 0,01 "sem origem" | **Sim** (`calc.classify_ma`, `k_to_pulses_per_l`, `pulse_count_window`, `trials.compute`) | manter; K continua **sem origem** |
| 2.4 | CRBasic v4 (`Flow_Pulsos`, `Flow_PulsosTot`, `Flow_PStatus`; `Flow_Status=3` para NAN; um só `PulseCount` em P2; 12 kHz) | **Sim** (`crbasic/Pluviometria_v4_vazao_pulsos.CR1X`), não compilado | manter |
| 2.5 | interface refeita com painel lateral e abas | **Não**, e o pedido atual não a quer | não reproduzir; identidade original |
| 2.6 | 221 testes + 105 e2e | não verificável (pacote ausente); aqui: 141 testes + 3 e2e | suíte própria |
| 2.7 | cobertura do período calculada uma vez; configuração do medidor montada uma vez por requisição | parcialmente (`stats`/`flow_stats` recebem `cfg`) | manter |
| 3.2 | pendências de bancada: compilar v4; K/Qmax/corte do MAG 5000; saída de pulsos em modo passivo com pull-up; nunca 24 V em P2 | — | pendências mantidas (seção 6) |

Problemas que existiam antes (PDF 2.1–2.2, confirmados no banco e no log reais [DADOS]): 18 "Tabela reiniciada" no log; 52 097 amostras sem
correspondência por tabela; 25 186 de 27 160 amostras (92,7 %) sem temperatura; `cor_status` NULL em 16 861 linhas; duas cópias do servidor em 27/10.
Nenhuma alteração do TI é revertida.

## 5. Arquitetura de software: achados (ordem de gravidade)

| # | Gravidade | Onde | Achado | Ação |
|---|---|---|---|---|
| A1 | alta (pedido) | `templates/index.html`, `static/js/app.js` | card principal fixo na balança; medidor em card secundário; sem seletor Analógico/Pulso; "Sinal: X Hz" em vez de pulsos brutos | card dinâmico por método (T2) |
| A2 | alta (pedido) | `app.js:saveDuration`, `index.html:44` | duração só em segundos inteiros (10–21600), sem unidade; não usa `trial_duration_ms` que o servidor já aceita | duração em ms/s/min com mínimo = Scan (T2) |
| A3 | média | `trials.py` | resultado não registra explicitamente carimbo inicial/final, tempo configurado × efetivo × relógio do PC num bloco único | bloco `timing` (T3) |
| A4 | média | `static/js/trials.js`, `templates/relatorio.html` | detalhe/relatório mostram duração em s inteiros (`mmss`), K só em pulsos/L | ms + unidade de K (T2) |
| A5 | baixa | `app.js:cfgBody` | o POST de configuração envia o corpo inteiro, apesar de o servidor aceitar parcial | envio parcial (T2) |
| A6 | baixa | `index.html` | pills `#conn` e `#real` dizem a mesma coisa; "Média do período" em três cards; texto explicativo longo | limpeza (T2) |
| A7 | baixa | `docs/` | `TEMPORIZACAO_E_PULSOS.md`, `CRBASIC_V4_PULSOS.md`, `ENTREGA_2026-10-29.md` referidos mas inexistentes; `MAPA_VARIAVEIS.md` descreve o programa `Pluviometria_Vazao` (2H/2L) e não o v3/v4 em uso | escrever/atualizar (T4, T6) |
| A8 | informativo | `calc.flow_from_sample` | usa Hz (derivado) para pulsos: só é chamado pelo caminho analógico em `trials._analog_lm`; o caminho de pulsos usa a contagem bruta (`pulse_flow_l_min`) | sem alteração; documentado |
| A9 | informativo | `profiles/elus_calib.json`, `crbasic/Pluviometria_Vazao.CR1X`, `_v2`, `_v3` | perfis/programas anteriores, não usados em produção, mas usados por testes de regressão e2e | mantidos |

Conversões duplicadas: não há. Toda vazão é calculada **uma vez** no servidor em L/min (`flow_eval`/`trials.compute`) e a tela só converte a unidade de exibição
(`Flow.convert`). Nomes de campo: perfil e emulador usam `Flow_mode` (m minúsculo), igual ao programa em uso; o probe aponta grafia divergente.

## 6. Aquisição por pulsos do MAG 5000: confirmado × pendente

| Item | Valor | Fonte |
|---|---|---|
| Frequência da saída digital | 0–10 kHz, ciclo 50 % | [DOC] Siemens SITRANS F M MAG 5000/6000 (FI 01 / manual 05/2006) |
| Saída **ativa** | 24 V DC, 30 mA, carga 1–10 kΩ, alimentada pelo medidor | [DOC] Siemens |
| Saída **passiva** | 3–30 V DC, ≤ 110 mA, carga 200 Ω–10 kΩ, alimentação externa | [DOC] Siemens |
| Terminais (56/57/58), polaridade, modo configurado na unidade instalada | **[FÍSICO]** — conferir no manual de operação e na etiqueta/menu da unidade | — |
| Entrada P2 do CR1000Xe | pull-up interno 100 kΩ a 5 V; baixo < 0,8 V, alto > 2,5 V; **máx. ±20 V DC**; até 250 kHz em alta frequência; contador 24 bits | [DOC] Campbell |
| Fator K do MAG 5000 | **[NÃO ENCONTRADO]** em nenhum arquivo; o `0,01 pulso/L` do `config.json` é sem origem | — |

Consequência técnica: a saída ativa de 24 V **não pode** ir direto em P2. A opção coerente é a saída passiva com pull-up externo (o interno de 100 kΩ está fora
da carga especificada pelo Siemens) ou um condicionador. **Proposta, não ligação validada.**

## 7. Resolução temporal do CR1000Xe (seção 5 do pedido)

| Pergunta | Resposta | Fonte |
|---|---|---|
| Resolução do relógio e dos carimbos | 1 ms (carimbo `TimeStamp` com fração; GPS opcional ±10 µs) | [DOC] |
| Intervalo mínimo do Scan | 1 ms (`Scan(1,mSec,…)` a 1 dia) | [DOC] |
| Intervalo do programa em uso | **1 s** (`Scan(1,Sec,0,0)`), tabelas gravadas a cada Scan | [CÓDIGO] |
| `PulseCount` detecta pulsos mais rápidos que o Scan? | Sim: contador por hardware (24 bits), acumula entre execuções; precisa rodar em todo Scan principal | [DOC] |
| Medir intervalos < 1 s com o programa atual? | **Não**: cada registro agrega 1 s; o servidor só enxerga múltiplos de 1 s | [CÓDIGO] |
| Limitações práticas | laço serial da balança (até 100 `SerialIn` de 100 ms de timeout cada) e `TCDiff`/`CurrentSE` com integração de 60 Hz no mesmo Scan; consulta HTTP ≈ 240 ms (p50 no log) por tabela | [CÓDIGO+DADOS] |
| Temporizador de maior resolução | `Timer()`, `TimeIntoInterval`, `Scan` de 100 ms/10 ms existem; não estão no programa em uso | [DOC] |
| Incerteza do método | com Scan de 1 s a quantização é de ±1 Scan (±1 s) no instante de início e de fim; a frequência média sofre ±1 pulso/N | [CÓDIGO] |

Decisão: a interface aceita ms/s/min e mostra a **resolução efetiva** (`scan_ms` do perfil = 1000 ms) e o tempo **efetivamente medido** pelos carimbos. Um programa de
Scan 100 ms é entregue como **proposta não compilada** (`crbasic/propostas/`), com o que muda e o que precisa ser verificado (`docs/TEMPORIZACAO_E_PULSOS.md`).

## 8. Riscos e dependências

- Nada aqui foi executado contra um CR1000Xe real: emulador + banco real (cópia) apenas.
- O v4 e a proposta v5 **não foram compilados** (sem CRBasic Editor).
- O K do MAG 5000, a Qmax e a ligação da saída de pulsos dependem da bancada.
- `DATALOGGER_PASSWORD` continua no keyring do Windows; os testes usam o emulador.
