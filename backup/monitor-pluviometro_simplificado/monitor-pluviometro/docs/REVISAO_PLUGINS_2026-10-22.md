# Revisão por ferramentas (22/10/2026): backend, frontend e CRBasic

Três revisores automáticos (plugins) analisaram o código a pedido do operador, com foco em latência e erros. Abaixo, o que cada um
encontrou, o que foi **aplicado** nesta versão e o que ficou **pendente** (depende de verificação no equipamento ou de decisão).

## Causa provável da "massa travada": duas camadas

1. **Datalogger (CRBasic)** — `Pluviometria.CR1X:188`: o laço lê no máximo **8 linhas por Scan**. Se a balança transmite mais do que
   isso por segundo, o buffer serial (1000 bytes) enche e o datalogger passa a ler linhas cada vez mais antigas: a massa na tela
   fica segundos atrás do visor, em degraus, com `StatusBal = 0`. Linhas truncadas na borda do buffer podem produzir pesos falsos.
   **Confirmação:** `NBuf` (Numeric Monitor) persistentemente alto. **Correção:** `crbasic/Pluviometria_v2.CR1X` (seção 3).
2. **Servidor** — (a) durante o ensaio o destaque era o Δm parcial, recalculado a cada 2–5 s, não a massa ao vivo; (b) o cursor era
   gravado **antes** de emitir para a tela, e o retry no Windows podia prender a thread por até 3 s; (c) cada amostra fazia um
   `commit` próprio e um `COUNT`, então uma rajada de recuperação segurava o lock por segundos sem emitir nada. Tudo corrigido.

## 1. Backend (app.py, datalogger.py, trials.py) — 17 achados

| # | Achado | Situação |
|---|---|---|
| 1 | cursor gravado antes do emit; retry de até 3 s na thread de aquisição | **aplicado**: emite antes do `ack`; retry curto (3×0,1 s) |
| 2 | um `commit` + um `COUNT` por amostra; rajadas seguram o lock | **aplicado**: `store_batch` = uma transação por lote |
| 3 | basculadas associadas à **última** leitura do lote → `tips_total` errado nas primeiras linhas de cada rajada (histórico/CSV) | **aplicado**: associadas à primeira; inseridas antes das amostras |
| 4 | `health()` (2 consultas, até 10 s) rodava na thread de aquisição | **aplicado**: tarefa em segundo plano |
| 5 | `lat_ms` só media ciclos "ao vivo" (escondia os travamentos) | **aplicado**: mede todo ciclo; contador `stalls` + log de ciclos > 1,5 s ou lotes > 2 |
| 6 | API e aquisição disputavam a mesma conexão SQLite e o mesmo lock | **aplicado**: leitores com conexão própria por thread (WAL) |
| 7 | parcial do ensaio O(n) por segundo em ensaios longos | **aplicado**: a cada amostra até 15 min; a cada 5 s acima |
| 8 | corrida em `_live` (tupla de 2 → IndexError esporádico) | **aplicado**: snapshot + tupla de 4 |
| 9 | `tick` × `stop` encerrando o mesmo ensaio → 500 | **aplicado**: `_finish` verifica o estado sob lock |
| 10 | `"INF"` da API passava por `_num` → OverflowError e aquisição presa | **aplicado**: `isfinite` |
| 11 | marca d'água sem escape: uma tabela parada segurava as outras sem erro | **aplicado**: libera após 5 s (tabela parada vira "sem comunicação") |
| 12 | 2ª consulta por ciclo só no perfil `elus_calib` (tabela esparsa) | pendente, não afeta o perfil em uso |
| 13 | `_ts_ms` em hora local (horário de verão) | pendente: Brasil sem horário de verão |
| 14 | janela do ensaio: 60 amostras = 59 s de referência | **decisão do operador**: manter |
| 15 | `tips_total` congelado por amostra após "Zerar contagem" | pendente (documentado) |
| 16 | log "fora de ordem" por linha em releituras | **aplicado**: limitado (1ª, 10ª, 100ª, a cada 1000) |
| 17 | cursor sem `fsync` (queda de energia → relê tudo do registro 0) | **aplicado** |

## 2. Frontend (static/js) — 13 achados

| # | Achado | Situação |
|---|---|---|
| 1/4 | durante o ensaio o número grande era o Δm parcial (congelado por segundos; "—" nos primeiros segundos) | **aplicado**: massa ao vivo em destaque durante o ensaio; Δm parcial na 1ª linha; concluído → Δm |
| 2 | falha na 1ª carga deixava a página sem polling nem relógio | **aplicado** |
| 3 | sem ressincronização de ensaio/basculadas após reconectar | **aplicado** |
| 5 | corrida: digitar a duração e clicar Iniciar podia usar a duração antiga | **aplicado**: espera o salvamento |
| 6 | ponto duplicado no sparkline a cada poll; render em dobro | **aplicado** |
| 7 | polls sobrepostos em períodos longos | **aplicado**: um de cada vez |
| 8 | decimação no Chart.js | não necessário: o servidor já limita a ~600 pontos |
| 9 | DOM reescrito sem mudança | **aplicado**: `setHtml` só quando muda |
| 10 | `null × 1000` mostrava "0,0 mL" | **aplicado** |
| 11 | painel de detalhes não refletia unidade nova após salvar | **aplicado** |
| 12 | separador de milhar nos campos | pendente (uso raro) |
| 13 | "Ver" no histórico travava em ensaio sem resultado | **aplicado** |

## 3. CRBasic (crbasic/) — 9 achados

| # | Achado | Situação |
|---|---|---|
| F1 | laço de 8 linhas/Scan → buffer enche → massa atrasada (causa provável do atraso) | **`Pluviometria_v2.CR1X`**: esvazia o buffer (até 100 linhas/Scan), usa a última completa; `NBufIni` para diagnóstico |
| F2 | `SerialIn` com timeout 100 ms × 8 (pior caso 800 ms); `Scan` sem buffer | verificar `SkippedScan` (já em `/api/diag → health`); pendente |
| F3 | `Pluviometria_Vazao.CR1X`: `PConfig = 3` e `PConfig = 0` para P2 | **alerta improcedente**: a tabela do Help (conferida em 22/10, CR1000X OS 9.0) diz 0 = Disabled, 1 = Switch Closure with pull up, 3 = High frequency with pull up, e aceita variável. O programa está correto |
| F4 | `Peso_g = NAN` passava com `StatusBal = 0` | **`Pluviometria_v2.CR1X`**: `If Peso_g = NAN Then StatusBal = 3` |
| F5 | `SplitStr` pega o 1º número: depende do formato da linha | confirmado: `LastLine` = `"+   19.7g  \r\n"` → 19,7 correto. A mensagem **não tem indicador de estabilidade** (modo contínuo). Verificar no menu da MK30K1 se há saída "somente estável". Sinal separado por espaços: conferir uma massa negativa |
| F6–F9 | resets, `Pluvio_Total`, tamanhos de tabela, troca de modo em tempo de execução | notas; nada bloqueante no programa atual |
| §3 | `PConfig = 1` em P1 (contato seco) | **confirmado** no Help: 1 = Switch Closure with pull up. Falta só o teste de 20 basculadas |

### Como usar o `Pluviometria_v2.CR1X`
1. Abra no CRBasic Editor e **compile** (não tenho o compilador aqui). Leia os avisos.
2. Antes de enviar, anote `NBuf` no Numeric Monitor com o programa atual (confirma a causa).
3. Envie; o servidor detecta a tabela reiniciada (`restarts` em `/api/diag`) e segue sem perder dados.
4. Depois: `NBufIni` deve ficar perto de 0 em regime; a massa na tela deve acompanhar o visor com ~1 s.
5. Só duas mudanças em relação ao programa carregado: o laço (8 → 100, com `NBufIni`) e o teste de `NAN`. O resto é idêntico.

**Confirmado em 22/10:** tabela `PConfig` (P1 = 1 correto; P2 = 3/0 corretos); formato da linha da balança. `Pluviometria_v2.CR1X` compilou e está
carregado (`NBuf` = 0, `SkippedScan` = 0, massa acompanhando o visor). **Ainda a confirmar:** entradas de corrente do CR1000Xe para o 4–20 mA
(página do manual); saída "somente estável" da MK30K1.
