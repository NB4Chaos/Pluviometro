# Diagnóstico e plano — fase 2 (pacote do TI como base) · 31/10/2026

Pedido: "Refinamento do sistema de calibração — preservação das otimizações do TI e evolução da interface UI/UX".
Material: `monitor-pluviometro_entrega_2026-10-28.zip` (pacote do TI, 71 arquivos) e o PDF Rev. 1 (idêntico, byte a byte, ao já lido em 30/10).
Fase anterior (base diferente): `docs/DIAGNOSTICO_2026-10-30.md`, `docs/ENTREGA_2026-10-30.md`.

## 1. O que o pacote do TI contém e o que foi decidido

| Item | Situação |
|---|---|
| Testes do TI nesta máquina | **221 passaram** (pytest), antes de qualquer alteração |
| Diferença para o código que estava no repositório (reimplementação de 29/10) | app.py 2174 linhas de diff, trials.py 816, calc.py 703, datalogger.py 246: implementações distintas das mesmas ideias |
| Decisão | **o pacote do TI passa a ser a base** (commit "Nova base"); os arquivos anteriores ficam no histórico do Git (commits 79a20ce…874894c) |
| Testes escritos para a base anterior (`test_trials_pulsos`, `test_trials_timing`, `test_app_api`, `test_calc_flow`) | dependiam de funções que não existem na base do TI; seus cenários são **reescritos** sobre a base nova (nenhum cenário é abandonado) |

## 2. Otimizações do TI identificadas (todas preservadas)

| Onde | O que faz | Efeito | Decisão |
|---|---|---|---|
| `app.py` `Pacer` | agenda por horário absoluto com fase travada logo após a gravação do Scan; nova tentativa de 120 ms (máx. 2) quando o registro ainda não existe; `CREEP` de 4 ms | latência PC−datalogger sem dente de serra (meta ≈ 0,3 s); 1 consulta por Scan | **manter** |
| `datalogger.py` registro-âncora | pede desde o último registro recebido, nunca um inexistente | fim das falsas "tabelas reiniciadas" e das regravações sem temperatura | manter |
| `datalogger.py` `DATALOGGER_PARALLEL` | leitura das 4 tabelas em paralelo (desligada) | só ganha se o CR1000Xe atender pedidos simultâneos | manter desligada |
| `app.py` `merge_sample` | releitura só completa grupos sem leitura válida | nunca piora uma linha gravada | manter |
| `app.py` `store_batch` | basculadas contadas uma vez por lote (`bisect`) | menos `COUNT(*)` por amostra | manter |
| `calc.covered_intervals`/`precip_period` | cobertura calculada numa passada | resumo 28–55 % mais rápido (medido pelo TI) | manter |
| `app.py` `/api/series` | `flow_cfg` montado uma vez + memo de conversões repetidas; média por fatia | gráfico 1–15 % mais rápido | manter |
| `app.js` `SUMMARY_EVERY` | resumo a cada 2 s (1 min–1 h), 5 s (6 h), 10 s (24 h/personalizado) | menos consultas em janelas longas | **manter os intervalos** |
| `app.js` `CHART_RELOAD` + `Charts.push` | gráfico recebe o ponto novo pelo Socket.IO e só recarrega a série a cada 15–60 s | gráficos sem refazer o período a cada 2 s | manter |
| `app.js` `onSample` | basculada nova força o resumo na hora; só a aba visível atualiza; `setHtml` evita reescrever o DOM | fluidez sem requisições extras | manter |
| Socket.IO eventos `flow` e `config` | troca de método e configuração chegam às abas sem polling | menos consultas | manter |
| `index.html` `?v=2026.10.28` | cache-busting de CSS/JS | — | manter (versão nova no sufixo) |

Regra desta fase: **nenhum intervalo diminui e nenhuma requisição nova é adicionada ao ciclo**. As animações usam só `opacity`/`transform` e classes de curta duração; nenhuma depende de nova consulta.

## 3. Tipografia: TI × identidade original (backup de referência)

| Elemento | Original (backup, referência) | TI (28/10) | Decisão |
|---|---|---|---|
| Fontes | Urbanist 300/400/500/600 | Urbanist 400/500/600/700 + **IBM Plex Mono** (sinais brutos) | voltar à original: Urbanist 300–600, sem mono (números tabulares em Urbanist) |
| h1 | 46 px / 400 | 30 px / 600, `letter-spacing −.01em` | 46 px / 400 (34 px abaixo de 900 px) |
| h2 / h3 | 22 px / 500 · 16 px / 600 | 18 px / 600 · 16 px / 600 | 22 / 500 · 16 / 600 |
| Valor principal `.big` | 64 px / 300 (72 px na linha de 2 cards) | clamp(44, 4,6vw, 64) / 300 | 64 px / 300 com clamp só para telas estreitas |
| Rótulos dos cards | `.lbl` 14 px, caixa normal, cor `--muted` | `.eyebrow` 12 px, **maiúsculas**, 700, + linha `.model` com marca/modelo | `.lbl` original; sem marca/modelo |
| Cards | raio 28 px, sem borda, sem sombra, gap 24 | raio 20 px, borda 1 px, sombra, gap 20 | original |
| Hero | `#06122E` + glow | `--navy-900 #071E40` + glow | original `#06122E` |
| Botões / segmentos | pílula 44 px, `.btn` 600; `.seg` branco, ativo navy | pílula 42 px; `.seg` com borda em `--surface-2` | original |
| Barra de controles | sem caixa, rótulos 14 px | caixa branca com borda, rótulos em maiúsculas | sem caixa, rótulos originais |
| Campos | raio 14 px, 44 px | raio 12 px, foco com anel amarelo | raio 14 px; manter o anel de foco do TI (acessibilidade) |
| Transições | `transform 120 ms` em botões | tokens `--dur-1/2/3`, `--ease`; `prefers-reduced-motion` global | manter os tokens de movimento do TI |

O que fica da camada do TI porque é estrutura, não tipografia: seletor Analógico/Pulso com "thumb" animado, linha de estado do método (`.mstate`), painel lateral de parâmetros (abas, validação, foco preso), `aria-*`, sprite de ícones.

## 4. Pulsos: o que o TI mostra × o que foi pedido

| Situação | TI (card de Vazão) | Pedido |
|---|---|---|
| Ao vivo, método pulsos | valor principal = **vazão** (`f.lmin`); linha de sinal "919 pulsos em 1,00 s = 919,0 Hz" em mono | valor principal = **contagem bruta** (pulsos no Scan); a vazão aparece como valor **calculado**, secundário |
| Ensaio em andamento | o card de vazão não mostra o ensaio (fica na balança: Δm, volume, vazão de referência) | contagem inicial registrada, cronômetro, **pulsos acumulados** como valor principal, tempo efetivo; vazão só depois |
| Ensaio encerrado | resultado só em "Detalhes do ensaio" do card da balança | N total, tempo efetivo, volume e vazão média identificados como calculados |

O backend do TI já fornece o necessário: `flow_pulses` (contagem bruta no Scan), `pulses_total` (contador acumulado), `flow.window_s`, e no ensaio `pulses_total`/`count_method`/`pulses_sum`/`freq_mean_hz` (diferença do contador acumulado quando coerente). **Nenhuma fórmula muda**; muda a apresentação. Acréscimo no backend: bloco `timing` (carimbos, configurado × efetivo, resolução) e duração em ms/s/min, reescritos sobre a base do TI.

## 5. Card principal dinâmico

TI: grade `"bal flow" "temp pluv"` no Comparativo, hero fixo na balança. Pedido (confirmado em 30/10): Comparativo → **medidor de vazão como hero + pluviômetro ao lado; balança oculta** (a referência gravimétrica do ensaio aparece dentro do card do medidor). A troca reorganiza só classes e a ordem na grade, com transição curta; nada é recarregado.

## 6. Plano por arquivo

| Arquivo | Preservar | Corrigir | Melhorar |
|---|---|---|---|
| `app.py` | tudo (Pacer, merge, série, API) | — | `trial_duration_ms`/`unit` (parcial, mínimo 1 Scan), `scan_ms` no `public_cfg` |
| `trials.py` | compute, snapshot, acumulado | — | `timing` no resultado; duração em ms |
| `calc.py`, `datalogger.py` | tudo | — | — |
| `static/app.css` | tokens de movimento, drawer, método, acessibilidade | fontes, escala, cards, botões, barra de controles (volta à identidade original) | hierarquia, espaçamentos, estados, transições suaves, `prefers-reduced-motion` |
| `templates/index.html` | estrutura de abas, drawer, sprite | marca/modelo removidos; `#real` e "Parâmetros do medidor" duplicado removidos; "Exibir" para Configurações | hero dinâmico; controles do ensaio no hero; pulsos brutos |
| `static/js/app.js` | intervalos, `onSample`, `Charts.push`, eventos | — | `applyMethod` com hero; `renderTrialCtl`; duração com unidade |
| `static/js/flow.js` | seletor, drawer, validação | `renderCard` em pulsos: contagem bruta como principal | ensaio no card do medidor |
| `static/js/trials.js`, `templates/relatorio.html` | — | — | `timing`, K com unidade, duração em ms |
| `tests/` | 221 do TI | — | novos testes sobre a base do TI: pulsos brutos no ensaio, timing, duração em ms, API |

Riscos: (1) qualquer regressão de intervalo seria uma perda de desempenho: os valores de `SUMMARY_EVERY`/`CHART_RELOAD` ficam intocados e são verificados no navegador; (2) o drawer do TI usa `trial_duration_s` em pré-visualizações: passa a usar ms; (3) `trials` tem coluna `duration_cfg_s INTEGER`: ganha `duration_cfg_ms` (migração automática, como no TI).

Skills consultadas: `frontend-design` (processo: plano de tokens → revisão → build → crítica com capturas), `impeccable` (modo *Operate*: precisão e contenção; craft-floor: sem eyebrows em maiúsculas, sem mono como figurino, movimento 150–250 ms só para estado; contraste ≥ 4,5:1; foco visível; `prefers-reduced-motion`).
