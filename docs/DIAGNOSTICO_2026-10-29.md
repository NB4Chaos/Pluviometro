# Diagnóstico técnico — 29/10/2026 (Etapa 1)

Revisão do sistema de calibração (pluviômetro + medidor de vazão) da Elus Instrumentação, datalogger Campbell Scientific CR1000Xe.
Pedido: `Prompt.md` na raiz do projeto. Este documento registra **o que foi encontrado** antes de qualquer alteração.

Legenda: **[CÓDIGO]** confirmado no código · **[DOC]** confirmado em documentação oficial · **[FÍSICO]** depende de validação na bancada · **[NÃO ENCONTRADO]**.

## 0. Resumo executivo

1. **A pasta de trabalho não continha o monitor do pluviômetro.** `Pluviometro\app.py`, `templates\index.html`, `README.md` e `requirements.txt` eram o projeto **"Linha de Ar — WEG CFW500 via Modbus RTU"** (controle de inversor, biblioteca `pymodbus`), sem nenhuma referência ao CR1000Xe, balança, termopar ou pluviômetro. Esses quatro arquivos foram preservados, intactos, em `backup\linha-de-ar_cfw500_2026-10-29\`.
2. **A versão revisada pelo TI (relatório Rev. 1, 28/10/2026) não está nesta máquina.** O PDF descreve `Pluviometria_v4_vazao_pulsos.CR1X`, `static/js/flow.js`, `docs/ENTREGA_2026-10-28.md`, `docs/CRBASIC_V4_PULSOS.md`, o registro-âncora no `datalogger.py` e o pacote `_entrega_2026-10-28/monitor-pluviometro_entrega_2026-10-28.zip`. Nenhum desses arquivos existe em `Pluviometro`, no backup, em `Downloads`, `Documentos`, `Desktop` ou `OneDrive`. O único arquivo relacionado fora da pasta é `Downloads\monitor-pluviometro_simplificado.zip` (15,6 MB, 29/10 22:52), que é a **origem do backup** (conteúdo idêntico, sem v4).
3. **O backup contém a última versão do monitor disponível aqui**: código de 22/10 com `app.py`/`datalogger.py`/`profiles/programa_vazao.json` alterados em 27/10, `config.json` de 28/10 06:56, banco e log até 28/10 07:53. É a versão **anterior** à revisão do TI, com a identidade visual original (Urbanist, cards de 28 px, azul `#0B1F4B`/amarelo `#FFC20E`) que o pedido quer recuperar.
4. **O código do backup tem um defeito grave em produção** (confirmado no log e no banco, e descrito pelo TI na seção 2.1 do PDF): 18 ocorrências de "Tabela reiniciada" no log, 52 097 amostras sem correspondência por tabela, 52 000 "amostras fora de ordem ou repetidas" e **25 186 das 27 160 amostras (92,7 %) sem temperatura** no banco real. Causa: pedir ao datalogger o registro *seguinte* ao último recebido; quando ele ainda não existe, a API responde a partir do registro mais antigo e o servidor interpreta como reinício da tabela.
5. **Decisão tomada (premissa declarada):** trabalhar sobre o código do backup restaurado para a raiz, **reimplementar** as correções do TI que estão descritas no PDF (registro-âncora, instância única, agenda absoluta, classificação do 4–20 mA, configuração parcial, API do medidor, CRBasic v4) e implementar as evoluções pedidas (card principal dinâmico, pulsos brutos, resolução de tempo, limpeza visual). Se o pacote do TI for localizado depois, ele pode ser comparado com esta entrega; nada aqui depende dele.

## 1. Diretórios e versões encontradas

| Local | Conteúdo real | Data | Uso nesta revisão |
|---|---|---|---|
| `Pluviometro\` (raiz, antes) | Projeto CFW500/Modbus (app.py 551 linhas, index.html com fontes Inter/Segoe UI) | 29/10 19:20 | movido para `backup\linha-de-ar_cfw500_2026-10-29\` |
| `Pluviometro\docs\` | `Elus_Monitor_Relatorio_Tecnico_Rev1_2026-10-28.pdf` (18 páginas, único PDF) | 28/10 | lido integralmente (seção 4) |
| `backup\monitor-pluviometro_simplificado\monitor-pluviometro\` | monitor completo: app.py, datalogger.py, calc.py, trials.py, static/, templates/, profiles/, crbasic/ (4 programas), tests/ (66 testes + 3 e2e), tools/, docs/ (13 md), config.json, banco SQLite, cursor, log | 22–28/10 | **referência**, não alterada; copiada para a raiz e para `backup\monitor-pluviometro_base_2026-10-29\` |
| `backup\Pluviometria_v3_com_vazao_4-20mA.CR1X` | programa **em uso no CR1000Xe** segundo o PDF do TI (CurrentSE em RG1) | 29/10 22:51 | copiado para `crbasic\` |
| `backup\...\.venv` | venv de Python 3.15 do computador do TI (`C:\Users\fcosta\...`) | — | inutilizável aqui; criado `.venv` novo (Python 3.14.3) |
| Git | **[NÃO ENCONTRADO]** — nenhum repositório em nenhuma das pastas | — | sem histórico para comparar |

## 2. Identidade visual: atual × anterior

Não existe uma "versão atual com tipografia alterada" do monitor nesta máquina. A única interface do monitor disponível é a do backup, que **é** a identidade original:

| Elemento | Backup (identidade Elus original) | Projeto CFW500 que estava na raiz (outro sistema) |
|---|---|---|
| Fonte | `Urbanist` 300/400/500/600 (Google Fonts) | `Inter, Segoe UI, Arial` |
| Cores | `--navy #0B1F4B`, `--logo #071E40`, `--yellow #FFC20E`, `--muted #5B6B8C`, `--bg #F5F5F8` | `#0b1f3a`, `#f5c400`, `#f3f6fa` |
| Cards | raio 28 px, sem borda, sem sombra, gap 24 px; hero `#06122E` com glow amarelo | raio 16 px, borda 1 px, sombra |
| Títulos | h1 46 px peso 400; h2 22 px peso 500 | h1 21–29 px; h2 16 px |
| Valor principal | `.big` 64 px peso 300, tabular | 22–32 px peso 800 |
| Botões/segmentos | pílulas 999 px, 44 px de altura, amarelo `.btn.y` | raio 9 px, peso 800 |
| Logo | `static/img/logo-elus.jpeg` real | "EL" desenhado em CSS |

Conclusão: a identidade a preservar é a de `static/app.css` + `templates/index.html` do backup. A alteração visual nesta revisão se limita a **reduzir a poluição** e a **tornar o card principal dinâmico**, mantendo tokens, fontes, raios, espaçamentos e componentes.

## 3. Hardware e caminho dos dados (programa em uso: `Pluviometria_v3_com_vazao_4-20mA.CR1X`)

| Equipamento | Sinal | Conexão no CR1000Xe | Instrução CRBasic | Variável | Tabela | Situação |
|---|---|---|---|---|---|---|
| Balança MK30K1 | RS-232, 9600 bps, formato 3 (8N1) | TX→C6, RX→C5, GND→G (`ComC5`) | `SerialOpen(ComC5,9600,3,0,1000,0)`, `SerialIn`, `SplitStr` | `Peso_g`, `StatusBal`, `LastLine` | `Balanca1s` (1 s) | [CÓDIGO]; linha real `"+   19.7g  \r\n"` confirmada em 22/10 (REVISAO_PLUGINS) |
| Termopar tipo T | mV diferencial | 1H (+), 1L (−) | `TCDiff(TempAgua_C,1,mV200C,1,TypeT,PTemp_C,True,0,60,1,0)`; junta fria = `PanelTemp(PTemp_C,4000)` | `TempAgua_C`, `PTemp_C` | `Termopar1s` (1 s) | [CÓDIGO] |
| Pluviômetro | contato seco | P1 – G | `PulseCount(Pluvio_Basculadas_1s,1,P1,1,0,1,0)` (PConfig 1 = switch closure com pull-up 100 kΩ/5 V) | `Pluvio_Basculadas_1s`, `Pluvio_Total`, `Pluvio_Chuva_mm` | `Pluviometro1s` (1 s) | [CÓDIGO]; `Const Pluvio_mmPorBasculada = 0.2` ("confirmar a resolução real") — o servidor ignora `Pluvio_Chuva_mm` e usa a resolução da tela |
| MAG 5000, 4–20 mA | corrente | **RG1** (entrada de corrente nativa, shunt interno 10 Ω) | `CurrentSE(Flow_mA,1,mV200,RG1,True,0,60,1,0)` | `Flow_mA`, `Flow_mV` (= mA×10, derivado), `Flow_Status` (0/1/2), `Flow_mode` (=2) | `Vazao1s` (1 s) | [CÓDIGO]; **funcionando**: 144 amostras `analog/ok` no banco, 4,0106–4,0109 mA (medidor parado). O pedido cita "2H/2L e shunt": isso era o programa `Pluviometria_Vazao.CR1X`, **não** o programa em uso |
| MAG 5000, pulsos | digital | **não ligado** | — | — | — | [FÍSICO] ver seção 6 |

Fluxo: Scan 1 s → `CallTable` (5 tabelas de 20 000 registros, ≈ 5,5 h circulares) → `DataQuery since-record` por tabela (HTTP, conta somente leitura, senha no Gerenciador de Credenciais do Windows, serviço `Elus-CR1000Xe`) → `datalogger.py` casa as tabelas por horário (±0,5 s) → `app.py` grava `samples`/`tips` (SQLite WAL) → Socket.IO `sample` + `/api/summary` (2 s) → `app.js` renderiza.

Nomes de campos: o perfil `programa_vazao.json` usa `Flow_mode` (m minúsculo), igual ao programa em uso. O emulador de teste (`tests/fake_programa_atual.py`) e o programa `Pluviometria_Vazao.CR1X` usam `Flow_Mode`/`Flow_Pulsos_1s`/`Flow_Freq_Hz`: por isso 3 testes do backup falham (linha de base: **73 passaram, 3 falharam**, idêntico ao relatado pelo TI).

## 4. Relatório do TI (Rev. 1, 28/10/2026) — o que diz e o que se confirma

| Item do TI | Confirmado aqui? | Decisão |
|---|---|---|
| 2.1 Releitura indevida das tabelas (pedir registro inexistente → API devolve o mais antigo → "tabela reiniciada" → regrava histórico sem temperatura/vazão); 16 vezes entre 22 e 28/10; 92,7 % das 27 160 amostras sem temperatura | **Sim** [CÓDIGO+DADOS]: `datalogger._pull` pede `nxt = último+1`; log tem 18 "reiniciada"; banco: 25 186/27 160 sem temperatura; `samples.cor_status` NULL em 16 861 linhas (regravadas sem vazão) | **reimplementar** o registro-âncora |
| 2.2 Duas cópias do servidor (27/10 15:45–16:33) | **Sim**: log tem "iniciando" às 15:45:59 e 16:33:46 com resumos intercalados | trava de instância única |
| 2.2 Agenda por horário absoluto, fase após o Scan, nova tentativa em 120 ms | plausível: `sio.sleep(max(0.05, SAMPLE_PERIOD - (time()-t0)))` acumula deriva | reimplementar |
| 2.3 Método analógico/pulsos escolhido no servidor; o datalogger mede os dois canais em todo Scan; método "ativo" só após amostra calculada; troca recusada em ensaio | não existe no backup | implementar (`/api/flow`, `/api/flow/method`) |
| 2.3 mA bruto sempre gravado; tolerância 0,02 mA nos limites sem extrapolar; falha abaixo de 3,6 mA (NAMUR NE 43) | não existe no backup (`cor_class`: fora de 4–20 → `out_of_range`, valor preservado) | implementar `calc.classify_ma` |
| 2.3 Pulsos: f = N/Δt; Q = 60·f/K; V = ΔN_acum/K; K em pulsos/L, pulsos/m³, L/pulso, mL/pulso; **K = 0,01 pulso/L do config.json sem origem** | `config.json` tem `flow_k_pulses_per_l: 0.01` — valor sem origem documentada | implementar; manter o valor marcado como "a conferir no MAG 5000" |
| 2.4 CRBasic v4: `Flow_Pulsos`, `Flow_PulsosTot`, `Flow_PStatus`; `Flow_Status = 3` para NAN; um único `PulseCount` em P2 em alta frequência; limite 12 kHz; não compilado | arquivo **não existe aqui** | escrever o v4 a partir do v3 em uso, com os mesmos campos (compatível com o perfil) |
| 2.5 Interface refeita (painel lateral com abas, `flow.js`) | não existe aqui; e o pedido atual **não quer** essa interface | não reproduzir; manter identidade original |
| 2.6 221 testes + 105 e2e | não verificável (código ausente) | suíte própria desta revisão |
| 2.7 Otimizações: cobertura do período calculada uma vez; configuração do medidor montada uma vez por requisição | aplicáveis ao código do backup | aplicar |
| 3.2 Pendências de bancada: compilar v4; K, Qmax, corte de vazão baixa do MAG 5000; saída de pulsos em modo **passivo** com pull-up; nunca ligar a saída ativa de 24 V em P2 (máx. ±20 V) | — | mantidas como pendências (seção 6) |

Nenhuma alteração do TI é revertida: elas não estão presentes; as válidas são reimplementadas.

## 5. Problemas encontrados no código do backup (ordem de gravidade)

| # | Gravidade | Onde | Problema | Correção prevista |
|---|---|---|---|---|
| P1 | crítica | `datalogger.py:_pull` | pede registro inexistente → releitura/regravação do histórico (seção 4) | registro-âncora; `INSERT … ON CONFLICT` só preenche campos vazios |
| P2 | alta | `app.py` | segunda instância sobe na mesma porta (`SO_REUSEADDR`) | trava de instância única em `DATA/servidor.lock` |
| P3 | alta | `app.py:_acquire_once` | agenda relativa acumula deriva; cruza o instante de gravação do Scan | agenda absoluta com fase |
| P4 | média | `datalogger.py:127-128`, `app.py:294` | `print()` de depuração a cada ciclo (`PERFIL CARREGADO`, `DEBUG FLOW`) | remover |
| P5 | média | `profiles/programa_vazao.json` × `tests/fake_programa_atual.py` | emulador e programa `Pluviometria_Vazao` usam `Flow_Mode`/`Flow_Pulsos_1s`; o programa em uso usa `Flow_mode` sem pulsos | emulador passa a ter esquemas v3 e v4; perfil com campos de pulso opcionais |
| P6 | média | `app.py:cor_class` | 4,000 mA exato como limite: vazão zero só é aceita porque o medidor parado lê 4,011 mA | `classify_ma` com tolerância configurável |
| P7 | média | `trials.py` | duração só em segundos inteiros (10 s a 6 h); sem registro da resolução temporal | duração em ms com unidade; resolução efetiva registrada |
| P8 | baixa | `trials.py:compute` | pulsos somados por registro: lacuna perde pulsos; não usa o contador acumulado | N por Δacumulado quando monotônico, soma como alternativa; invalidar se lacuna+reinício |
| P9 | baixa | `app.py:set_config` | `mass_unit` obrigatório (KeyError → 400 se ausente) | configuração parcial |
| P10 | baixa | `index.html` | card do Medidor de Vazão é secundário mesmo no Comparativo; parágrafo longo de ajuda no card do pluviômetro; duas linhas "Média do período" | card principal dinâmico; textos em `details` |

## 6. Aquisição por pulsos do MAG 5000 — o que está confirmado e o que falta

Fonte: datasheet Siemens SITRANS F M MAG 5000/6000 (FI 01) e ajuda/especificações oficiais da Campbell Scientific (links em `docs/TEMPORIZACAO_E_PULSOS.md`).

| Item | Valor | Fonte |
|---|---|---|
| Saída digital do MAG 5000: frequência | 0 … 10 kHz, 50 % de ciclo (uni/bidirecional) | [DOC] Siemens |
| Pulso **ativo** | 24 V DC, 30 mA, 1 kΩ ≤ Ri ≤ 10 kΩ, alimentado pelo medidor (terminais 57/58) | [DOC] Siemens |
| Pulso **passivo** | 3 … 30 V DC, máx. 110 mA, 200 Ω ≤ Ri ≤ 10 kΩ, alimentado pelo equipamento conectado | [DOC] Siemens |
| Terminais 56/57/58 | 57/58 = saída ativa; capacitor 1000 µF entre 56 (+) e 58 para contador mecânico; atribuição exata do modo passivo | [DOC] parcial — **confirmar no manual de operação e na etiqueta da unidade** |
| Entrada P2 do CR1000Xe | pull-up 100 kΩ a 5 V; nível baixo < 0,8 V, alto > 2,5 V; **máx. ±20 V DC sustentado**; 250 kHz em alta frequência; contador 24 bits (16 777 216/Scan); resistência de entrada 5 kΩ | [DOC] Campbell |

Consequências: a saída **ativa de 24 V não pode ir direto em P2** (excede ±20 V). O caminho tecnicamente coerente é a saída **passiva** com o P2 em alta frequência, mas o pull-up interno (100 kΩ) está **fora** da faixa de carga especificada pelo Siemens (≤ 10 kΩ): provavelmente será necessário um resistor de pull-up externo (ex.: 4,7–10 kΩ entre P2 e o terminal 5V do datalogger) ou um condicionador. **Isso é uma proposta, não uma ligação validada** [FÍSICO]. 10 kHz × Scan de 1 s = 10 000 pulsos/Scan: muito abaixo do limite do contador.

Fator K: o MAG 5000 define o volume por pulso no menu de saídas; o valor **não está em nenhum arquivo do projeto** [NÃO ENCONTRADO]. O `0.01` do `config.json` fica marcado como "sem origem".

## 7. Resolução temporal — o que o CR1000Xe permite (investigação pedida na seção 5 do prompt)

| Pergunta | Resposta | Fonte |
|---|---|---|
| Resolução do relógio / carimbo | 1 ms (relógio em tempo real; GPS opcional ±10 µs) | [DOC] Campbell, especificações do sistema |
| Intervalo mínimo do Scan | 1 ms (período de execução 1 ms a 1 dia) | [DOC] |
| Intervalo do programa em uso | **1 s** (`Scan(1,Sec,0,0)`); tabelas gravadas a cada Scan | [CÓDIGO] |
| `PulseCount` detecta pulsos mais rápidos que o Scan? | Sim: contador por hardware, 24 bits, acumula entre execuções; `PulseCount` precisa rodar em **todo** Scan principal (não pode ficar em `If`, sub-rotina, `SubScan` nem `SlowSequence`) | [DOC] ajuda CRBasic |
| Medir intervalos < 1 s com o programa atual? | **Não.** Cada registro agrega 1 s; o servidor só enxerga múltiplos de 1 s. Qualquer duração configurada em ms fica quantizada em 1 s | [CÓDIGO] |
| Limitações práticas | o laço serial da balança (`SerialIn` com timeout de 100 ms, até 100 linhas) e o `TCDiff` com integração de 60 Hz vivem no mesmo Scan: reduzir o Scan para 100 ms exige mover a balança para `SlowSequence` e verificar `SkippedScan`; a consulta HTTP leva ~240 ms (p50 medido no log) | [CÓDIGO+LOG] |
| Temporizador de maior resolução | `Timer()`/`TimeIntoInterval` e tabelas com `Scan` de 100 ms ou 10 ms existem no CR1000X; não estão no programa em uso | [DOC] |

Decisão: a interface passa a aceitar a duração em **ms, s ou min**, mas mostra sempre a **resolução efetiva** (1000 ms com o programa atual) e o tempo **efetivamente medido** pelos carimbos do datalogger. Um programa de alta taxa é apresentado como proposta documentada (`docs/TEMPORIZACAO_E_PULSOS.md`), não como implementação carregada.

## 8. Riscos e dependências

- A migração do cursor (`cursor_cr1000x.json`, formato antigo "próximo registro") para o formato âncora precisa ser automática e não reler o histórico.
- O banco real (27 160 amostras) tem linhas regravadas sem temperatura/vazão; a correção impede novas regravações, mas **não reconstrói** o que foi perdido (os registros já saíram do anel de 5,5 h do datalogger).
- O programa v4 não pode ser compilado aqui (sem CRBasic Editor); o servidor precisa funcionar com v3 (sem pulsos) e com v4.
- A escolha analógico/pulsos é do **servidor**: o CR1000Xe mede os dois canais sempre; nada é escrito no datalogger.
- Credenciais: `app.py` exige `DATALOGGER_PASSWORD` no ambiente ou no keyring; os testes usam o emulador.
