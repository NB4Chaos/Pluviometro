# Diagnóstico, alterações e desempenho

Base: o zip enviado (código idêntico à versão anterior; o `config.json` dele tinha `address` e `user` vazios, então o endereço vem de
`DATALOGGER_HOST` ou da sua máquina) e uma **cópia** do `dados_cr1000x.db` real que veio junto (18.422 amostras, 19/10 16:47 a 20/10 15:20).
O banco original não foi alterado.

## 1. Fluxo dos dados (como é hoje)

| Etapa | Onde | O que acontece |
|---|---|---|
| Aquisição | `crbasic/Pluviometria.CR1X`, `Scan(1,Sec)` | a cada 1 s: termopar (`TCDiff`), pluviômetro (`PulseCount` em P1), balança (serial) |
| Gravação | `CallTable` | tabelas `Balanca1s`, `Termopar1s`, `Pluviometro1s`, `Resumo` (+ `Vazao1s` no programa novo), 20.000 registros cada |
| Coleta | `datalogger.py` `CR1000X.read()` | `DataQuery` por número de registro, cursor em disco, marca d'água entre tabelas |
| Processamento | `app.py` `acquire()` / `store_reading()` | grava `samples` e `tips` (SQLite); converte vazão a partir do dado bruto |
| Envio à tela | Socket.IO `sample` (1/s) e `/api/summary` (3 s) | a interface recebe a última amostra e consulta o período |

## 2. Problemas encontrados

| # | Problema | Arquivo e função | Causa | Consequência | Correção feita |
|---|---|---|---|---|---|
| 1 | **Temperatura “sem comunicação” em 95 % das linhas reais** (17.581 de 18.422) e balança “sem comunicação” em 68 % | `datalogger.py` `read()` (casamento por horário exato) | linhas de tabelas diferentes eram casadas por igualdade exata de milissegundos; qualquer diferença virava “sem comunicação” | histórico e médias com buracos falsos | casamento por horário mais próximo até 0,5 s (`_match`), marca d'água com a mesma tolerância e contador `join_miss` (log e `/api/diag`). **Causa exata nos seus dados não confirmada**: depois de 20/10 15:06:37 a temperatura vem normal; antes disso pode ter sido o termopar desligado ou uma versão anterior do programa. A balança “sem comunicação” (StatusBal = 1, sem bytes) é provavelmente real (balança desligada/sem cabo) e não é bug |
| 2 | “Precipitação acumulada” não era do período selecionado | `app.py` `summary()` (antes) | usava o total desde “Zerar contagem”, enquanto a intensidade usava o período | dois números com janelas diferentes lado a lado | acumulado = basculadas de `[início, fim)`; total desde zerar virou indicador separado e rotulado |
| 3 | Intensidade dividia pelo período inteiro, mesmo com o servidor desligado | `summary()` (antes) | `hours = (to-fr)` | subestimava (ex.: 17 h sem dados no seu banco) | `calc.precip_period`: tempo realmente coberto por amostras, resultado marcado “parcial” e duração coberta; sem amostras → indisponível |
| 4 | Contagem e duração com inícios diferentes após “Zerar contagem” | `summary()` (antes) | `max(fr, count_since)` só no numerador | intensidade errada logo após zerar | o período não depende mais do zeramento |
| 5 | Intervalo fechado nos dois lados | todas as consultas `BETWEEN` | `ts BETWEEN a AND b` | evento na fronteira contado em dois períodos | `ts >= a AND ts < b` em tudo |
| 6 | Média atrasava | `stats()` / `charts.js` | média aritmética de TODO o período (não é filtro) | degrau 0→120 leva minutos para aparecer | média móvel por janela de tempo (30 s, configurável) separada da média do período; ambas rotuladas |
| 7 | Valor da média não aparecia no gráfico | `charts.js` | só havia a linha tracejada | — | valor atual, média móvel e média do período com unidade na legenda e junto à linha |
| 8 | Dado velho parecia atual | `app.js` | a última leitura ficava na tela | leitura de minutos atrás exibida como atual | idade da leitura; após 8 s sem amostra nova os valores viram “—” e aparece “desatualizada” |
| 9 | Salvar configurações regravava o endereço | `app.py` `set_config()` (antes) | `comm` inteiro vinha do formulário | remover o campo de IP apagaria o endereço do `config.json` | endereço nunca vem da interface; campo ausente/vazio preserva; gravação atômica |
| 10 | Escrita sem proteção | `app.py` | nenhum endpoint exigia autenticação | qualquer PC da rede alterava configuração, zerava contagem (e iniciaria ensaios) | `DASHBOARD_TOKEN` opcional + exigência de JSON (barra POST de outro site) |
| 11 | Testes apagavam dados reais | `tests/e2e_*.py` | gravavam `dados_cr1000x.db` na pasta do projeto | risco de perder dados | `ELUS_DATA_DIR`: os e2e usam pasta temporária |
| 12 | Martelava o datalogger em falha | `app.py` `acquire()` | tentava a cada 1 s sempre | carga em rede/equipamento já com problema | recuo progressivo (1 s, 2 s, 4 s… até 10 s) |
| 13 | **Bug do meu código anterior** | `datalogger.py` | `has_flow` ignorava o bloco `flow` | com o perfil novo o medidor apareceria “aguardando integração” | corrigido; coberto pelo e2e |

Não encontrado: dados repetidos ou fora de ordem (0 nas 18.422 amostras reais: 1 registro por segundo, sem repetição), conversão dupla de pulsos
(o servidor ignora `Pluvio_Chuva_mm` do CRBasic e aplica a resolução da tela uma única vez).

**Resolução duplicada (CRBasic × tela):** confirmado. `Pluvio_mmPorBasculada = 0.2` no CRBasic e `tip_resolution_mm` na tela. Estratégia adotada:
fonte única = **tela/servidor**; o CRBasic registra os pulsos brutos (`Pluvio_Basculadas_1s`) e o servidor guarda cada basculada como evento. O
`Pluvio_Chuva_mm` do datalogger é ignorado. Se mudar a resolução na tela, ela passa a valer para os cálculos novos (ensaios concluídos guardam a
resolução usada).

## 3. Desempenho: onde está o gargalo

| Camada | Medida/análise | Conclusão |
|---|---|---|
| CRBasic | `Scan(1,Sec)`; uma linha por segundo por tabela | **gargalo de base: 1 s** (a menor mudança que a API enxerga) |
| Comunicação | 3 (4 com `Vazao1s`) consultas HTTP por ciclo, sequenciais, sem sobreposição | no emulador: consulta p50 ≈ 30–50 ms. **No equipamento real não foi medido** |
| Backend | processamento de 1 lote ≈ ms; `/api/summary` de 23 h (18 mil amostras reais): 0,07 s; `/api/series`: 0,05 s | não é gargalo |
| Frontend | antes: resumo a cada 5 s; agora 3 s; gráficos com no máx. 600 pontos | latência de tela ≤ ~1 s para valores ao vivo (Socket.IO), ≤ 3 s para períodos |

Latência esperada do valor ao vivo: até 1 s (Scan) + até 1 s (próxima consulta) + ~0,1 s. **Não alterei o `Scan` nem o intervalo de consulta**:
o `Scan` de 1 s casa com a balança serial (taxa de linhas da MK30K1 desconhecida), e reduzir a consulta para 0,5 s dobra a carga HTTP sobre o
datalogger para ganhar ~0,25 s médios. Se quiser tentar: `SAMPLE_PERIOD=0.5` e veja `/api/diag` (`lat_ms`, `poll_ms`). `lat_ms` é “hora do PC
− carimbo do datalogger” só de amostras ao vivo; inclui o desvio entre os dois relógios (a interface avisa se passar de 10 s).

Só exige mudança no CRBasic: ir abaixo de 1 s de aquisição, ou registrar eventos (basculadas) com horário exato em vez de contagem por segundo.
O que se resolve só no servidor: intervalo de consulta, janelas, médias, períodos.

Estratégia de atualização: continuei com **consulta (polling) sequencial**, porque a API web do datalogger não oferece conexão persistente
(não encontrei na documentação lida). Não há consultas acumuladas: a próxima só começa quando a anterior termina.

## 4. Alterações por arquivo

| Arquivo | Função/trecho | O que mudou | Motivo |
|---|---|---|---|
| `calc.py` (novo) | tudo | cálculos puros: períodos `[ini,fim)`, cobertura, precipitação/intensidade, média móvel, inclinação, gravimetria, vazão a partir do dado bruto | testável sem banco nem relógio |
| `trials.py` (novo) | `Trials`, `compute` | ensaios: janela no horário do datalogger, snapshot imutável (gatilhos SQL), um por vez (índice único) | itens 7 e 9 do pedido |
| `datalogger.py` | `_reading`, `_match`, `read`, `Reading` | tabela `Vazao1s` (pulsos/Hz/mA/modo/estado), casamento tolerante, marca d'água tolerante, `has_flow` | itens 1 e 6 |
| `app.py` | `acquire`, `summary`, `series`, `history`, `moving`, `set_config`, `/api/trials*`, `/api/diag`, `guarded`, logs | ver tabela do §2 | |
| `templates/index.html` | cards, período 1 min, Configurações (sem IP; Tempos; K; área) | | itens 3 e 11.6 |
| `static/js/app.js`, `trials.js`, `charts.js`, `api.js`, `app.css` | indicador principal, parcial/atual, ensaios, gráficos, token | | |
| `profiles/programa_vazao.json` (novo) | — | perfil do programa novo | |
| `crbasic/Pluviometria_Vazao.CR1X` (novo) | ver `CRBASIC_VAZAO.md` | só acréscimos; original intacto | item 6 |
| `tests/` | `test_calc`, `test_trials`, `test_adapter_vazao`, `e2e_ensaio` + ajustes | | |

Reversão: `../_backup/monitor-pluviometro_v1_antes_da_revisao.zip` tem o projeto anterior completo e o `.CR1X` original.
