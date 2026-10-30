# CRBasic v4: `Pluviometria_v4_vazao_pulsos.CR1X` — o que muda, como carregar, como reverter

Programa **em uso** no CR1000Xe (segundo o relatório do TI de 28/10): `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X`.
Programa com pulsos: `crbasic/Pluviometria_v4_vazao_pulsos.CR1X` — **não compilado nem carregado** (não há CRBasic Editor nesta máquina).
Proposta para resolução de 100 ms: `crbasic/propostas/Pluviometria_v5_scan100ms_PROPOSTA.CR1X` — **não compilada; não carregar sem teste** (`docs/TEMPORIZACAO_E_PULSOS.md`).

## Diferenças v3 → v4 (confirmadas por `diff`)

| Onde | v3 (em uso) | v4 |
|---|---|---|
| Constantes | — | `ScanSeg = 1`, `Flow_PMaxHz = 12000` |
| Variáveis | — | `Flow_Pulsos` (Float), `Flow_PulsosTot` (Long), `Flow_PStatus` (Long); `Flow_Primeira` (Dim) |
| Tabela `Vazao1s` | `Flow_mV, Flow_mA, Flow_Status, Flow_mode` | os 4 iguais + `Flow_Pulsos, Flow_PulsosTot, Flow_PStatus` |
| `BeginProg` | `Flow_Status = 3` | + `Flow_mode = 2`, `Flow_Pulsos = NAN`, `Flow_PulsosTot = 0`, `Flow_PStatus = 1`, `Flow_Primeira = True` |
| 4–20 mA | `Flow_mA = NAN` saía com `Flow_Status = 0` | `If Flow_mA = NAN Then Flow_Status = 3` (sem leitura) |
| Pulsos | — | `PulseCount(Flow_Pulsos,1,P2,3,0,1,0)` em todo Scan + classificação `Flow_PStatus` + acumulado |
| Balança, termopar, pluviômetro | idênticos | idênticos |

Nenhuma pinagem, faixa, constante física ou formato de mensagem foi alterado.

## Ligações (as do v3, inalteradas) + a nova

| Instrumento | Terminais | Instrução |
|---|---|---|
| Balança MK30K1 | TX → C6, RX → C5, GND → G (`ComC5`, 9600 8N1) | `SerialOpen/SerialIn/SplitStr` |
| Termopar tipo T | 1H (+), 1L (−) | `TCDiff(…,1,mV200C,1,TypeT,PTemp_C,True,0,60,1,0)` |
| Pluviômetro | P1 – G | `PulseCount(…,P1,1,0,1,0)` (fechamento de contato, pull-up) |
| MAG 5000 4–20 mA | RG1 | `CurrentSE(Flow_mA,1,mV200,RG1,True,0,60,1,0)` |
| MAG 5000 pulsos (**novo, não validado**) | P2 (+ G) — **saída passiva com pull-up externo**; nunca a saída ativa de 24 V | `PulseCount(Flow_Pulsos,1,P2,3,0,1,0)` |

## Como carregar com segurança

1. Salvar o programa atual do datalogger (Device Configuration Utility / LoggerNet → *Retrieve*) e guardar o `.CR1X` junto com `crbasic/`.
2. Compilar `Pluviometria_v4_vazao_pulsos.CR1X` no CRBasic Editor; resolver avisos. Conferir que `PulseCount` em P2 não está dentro de `If`.
3. Parar o servidor (`parar.bat`). Enviar o programa. As tabelas são recriadas: na volta o servidor detecta "tabela reiniciada" (âncora some) e recomeça do primeiro registro, **sem apagar o histórico** do banco.
4. Rodar `python tools\probe_cr1000x.py --host <IP> --user <conta somente leitura> --profile programa_vazao`: deve listar `Vazao1s` com `Flow_mA`, `Flow_Status`, `Flow_mode`, `Flow_Pulsos`, `Flow_PulsosTot`, `Flow_PStatus` e apontar qualquer grafia diferente (`Flow_Mode` × `Flow_mode`).
5. Iniciar o servidor. No card do medidor (Método Comparativo), o seletor **Pulsos** passa a ser aceito; o card mostra "pulsos solicitado · aguardando…" até a primeira amostra calculada, depois "pulsos ativo · confirmado por dado do datalogger".
6. Conferir em *Status*: `SkippedScan` = 0, `ProcTime`/`MaxProcTime` < 1000 ms; e em *Numeric Monitor*: `Flow_PStatus = 0`, `Flow_Pulsos` ≥ 0, `Peso_g`, `TempAgua_C`, `Pluvio_Basculadas_1s` normais.

## Como reverter

Reenviar `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X`. O perfil `programa_vazao` trata os campos de pulso como opcionais: com o v3 o servidor informa "canal
indisponível no programa" para pulsos e continua com o 4–20 mA. Se `flow_method` ficou em `pulse`, escolher **Analógico 4–20 mA** no card (ou editar `config.json`).

## Pendências que dependem da bancada
- Compilar/carregar o v4 e conferir os campos (passo 4).
- Ligação da saída de pulsos (modo passivo, pull-up externo, terminais 56/57/58, polaridade) — `docs/TEMPORIZACAO_E_PULSOS.md`, seção 6.
- Fator K, Qmax e corte de vazão baixa lidos no menu do MAG 5000.
