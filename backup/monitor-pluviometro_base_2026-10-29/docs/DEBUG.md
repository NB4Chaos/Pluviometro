# Onde mexer quando algo falha

Logs: `logs/servidor.log` (rotativo, 3 × 2 MB; `LOG_LEVEL=DEBUG` grava cada amostra com valor bruto, convertido, estado e horário). Um resumo por minuto
(`resumo: consultas=… erros=… lat… lacunas=… sem-correspondencia=…`). Nunca contém senha nem token. Estado em tempo real: `http://127.0.0.1:5000/api/diag`.

## 1. Instrumento ↔ CR1000Xe

| Instrumento | Arquivo / instrução / variável | Sintoma | Causa provável | Como confirmar | Correção |
|---|---|---|---|---|---|
| Balança | `Pluviometria*.CR1X`: `SerialOpen(ComC5,BaudSel…)`, `SerialIn`, `SplitStr`; `StatusBal`, `LastLine`, `TotalFalha`, `FalhasSeguidas` | massa “Sem comunicação” (`StatusBal = 1`) | sem bytes: cabo C5/C6/G, baud, balança desligada ou em outro modo de envio | *Numeric Monitor*: `BaudInUse`, `LastLine` vazio, `TotalFalha` subindo. **No seu banco: 68 % das amostras estavam assim** | conferir cabo e configuração serial da MK30K1 |
| Balança | `SplitStr(NumLido(1),LastLine,"",3,0)` (marcada “experimental”) | `StatusBal = 3 ou 4`, massa inválida | formato real da linha ≠ o esperado | ver `LastLine` com a balança ligada e ajustar a extração | ajustar o `SplitStr` com uma linha real |
| Termopar | `TCDiff(TempAgua_C,1,mV200C,…)`; `TempAgua_C`, `PTemp_C` | temperatura inválida | termopar solto ou invertido (`NAN`) | `TempAgua_C = NAN` no *Numeric Monitor* | verificar 1H/1L e polaridade |
| Pluviômetro | `PulseCount(Pluvio_Basculadas_1s,1,P1,1,0,1,0)` | sem basculadas | contato P1–G, `PConfig` | fechar o contato à mão e ver a contagem subir | cabo/sensor |
| Medidor (pulsos) | `PulseCount(…P2…)`, `Flow_Pulsos_1s`, `Flow_Freq_Hz`, `Flow_PConfig` | 0 pulsos com vazão, ou `Flow_Status = 4` | sinal não chega a P2, nível errado (limiar 0,8/2,5 V), frequência acima do limite | `Flow_Pulsos_1s`, `Flow_Mode = 1`, osciloscópio/multímetro | cabo, nível, condicionador |
| Medidor (analógico) | `VoltDiff(Flow_mV,…,2,…)`, `Flow_Shunt_ohm`, `Flow_mA` | `Flow_Status = 2 ou 3`, mA < 4 | laço aberto, shunt não configurado, fora de −100…+5000 mV | `Flow_mV`, `Flow_Shunt_ohm` | configurar shunt, conferir ligação |

## 2. CR1000Xe ↔ servidor

| Arquivo / função | Sintoma na tela / log | Causa provável | Como confirmar | Correção |
|---|---|---|---|---|
| `datalogger.py` `_get()` (HTTP) | “Datalogger sem resposta”; log `Falha na leitura do datalogger: <erro>` (uma linha por erro novo) | IP/rede, HTTP desabilitado, datalogger offline | `ping <IP>`; abrir `http://<IP>/`; `python tools/probe_cr1000x.py` | cabo, IP fixo, habilitar HTTP |
| idem | `HTTP Error 401` | conta/senha | `DATALOGGER_PASSWORD`, conta somente leitura no `.csipasswd` | corrigir senha/conta |
| `app.py` `acquire()` | log `Endereço do datalogger não configurado` | `DATALOGGER_HOST` ausente e `config.json` sem `address` | `/api/diag` → `link.error` | definir `DATALOGGER_HOST` (o endereço **não** se edita na interface) |
| `datalogger.py` `_pull()` | log `Lacuna em <tabela>`; `gaps` > 0 em `/api/diag` | servidor ficou fora mais de ~5,5 h e o datalogger sobrescreveu | `gaps`; período “parcial” | nada a recuperar; reduzir indisponibilidade |
| `datalogger.py` `_match()` | log `Sem registro de <tabela> para <ts>`; `join_miss` | tabelas com horários diferentes (> 0,5 s) | `/api/diag` → `join_miss`; comparar horários das tabelas | ver `JOIN_TOL_MS`; conferir o `Scan` e `DataInterval` das tabelas |
| `app.py` `link_view()` | aviso “relógio do datalogger difere do PC” | hora do datalogger errada | `/api/diag` → `link.clock_skew_s` | acertar a hora (períodos relativos dependem dela) |
| perfil | medidor “aguardando integração” com o programa novo | perfil errado (`programa_atual`) | `Configurações` → Perfil; `link.flow_integrated` | `programa_vazao` e reiniciar |
| `profiles/*.json` | “tabela reiniciada” no log | programa recarregado no datalogger | normal após reenviar o programa | — |

## 3. Servidor ↔ interface

| Arquivo / função | Sintoma | Causa provável | Como confirmar | Correção |
|---|---|---|---|---|
| `app.js` `isStale()` / Socket.IO | “Servidor desconectado” | `app.py` parado ou outra porta | terminal do servidor; `http://127.0.0.1:5000/api/diag` | reiniciar; conferir `PORT` |
| `app.js` `setPills()` | “Aguardando dados novos” (servidor ok) | datalogger sem amostras novas (programa parado) | `/api/diag` → `link.data_fresh = false` | conferir o programa no datalogger |
| `api.js` `Api.post()` | pede “token” ao salvar/zerar/iniciar ensaio | `DASHBOARD_TOKEN` definido no servidor | resposta HTTP 401; log `Escrita negada` | informar o token (fica só na aba) |
| `trials.py` | “Já existe um ensaio em andamento” | ensaio anterior ainda `running` | `/api/trials` | encerrar pelo botão; se o datalogger sumiu, ele se encerra sozinho 120 s após o fim previsto |
| `trials.py` `start()` | “Sem dados atuais do datalogger” | sem amostra nova nos últimos 10 s | `/api/diag` | restabelecer a comunicação |
| `calc.py` / `/api/summary` | período “parcial” | lacunas de aquisição no período | `period.covered_s`, `period.gaps` | normal; veja a causa em 2 |
| navegador (F12 → Console) | tela em branco ou valores parados | erro de JavaScript | mensagens `[Elus] erro:` | enviar a mensagem |
