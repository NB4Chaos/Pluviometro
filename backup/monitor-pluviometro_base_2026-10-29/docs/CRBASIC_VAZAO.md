# CRBasic: medidor de vazão em P2 (pulsos) ou 2H/2L (analógico)

Arquivo novo: `crbasic/Pluviometria_Vazao.CR1X`. **O seu programa original não foi alterado** (`crbasic/Pluviometria.CR1X` continua sendo o de antes, só com a linha de
três crases removida). O novo é o mesmo programa **só com acréscimos**: comparado com o original, nenhuma linha foi removida ou modificada. **Não foi compilado
no CRBasic Editor** (não tenho o compilador aqui): compile-o e leia os avisos antes de enviar.

## O que foi acrescentado

| Onde | Acréscimo | Para quê |
|---|---|---|
| Cabeçalho | comentário do medidor | documentação |
| Constantes | `Const ScanSeg = 1` | intervalo do Scan para calcular Hz (mantenha igual ao `Scan(1,Sec,0,0)`) |
| Variáveis | `Flow_Mode`, `Flow_Shunt_ohm`, `Flow_PConfig`, `Flow_Pulsos_1s`, `Flow_Freq_Hz`, `Flow_Pulsos_Total`, `Flow_mV`, `Flow_mA`, `Flow_Status` (+ `Flow_Primeira`) | uma só estrutura para os dois modos |
| Tabela | `Vazao1s` (1 registro por Scan, valores brutos) | disponibiliza ao servidor |
| `BeginProg` | `Flow_Mode = 1`, `Flow_Shunt_ohm = 0`, inicializações em `NAN` | valores iniciais |
| Dentro do `Scan` | bloco “MEDIDOR DE VAZAO” antes da balança | medição |
| Final do `Scan` | `CallTable Vazao1s` | gravação |

## Como escolher o modo

- `Flow_Mode = 1` → **pulsos em P2**. `PulseCount(Flow_Pulsos_1s,1,P2,Flow_PConfig,0,1,0)` com `PConfig = 3` (alta frequência, pull-up).
- `Flow_Mode = 2` → **analógico em 2H/2L**. `PConfig = 0` desliga o P2 e `VoltDiff(Flow_mV,1,mV5000,2,True,0,60,1,0)` lê o canal diferencial 2; `Flow_mA = Flow_mV ÷ Flow_Shunt_ohm`.
- Troca **sem recompilar**: em *Numeric Monitor* (LoggerNet/Device Configuration) altere `Flow_Mode`. Ao reiniciar o programa ele volta ao valor de `BeginProg`;
  para fixar, edite a linha `Flow_Mode = 1` e reenvie. No servidor, use o perfil `programa_vazao`.

`PulseCount` roda **em todo Scan** (a documentação proíbe colocá-lo dentro de `If`/sub-rotina/`SlowSequence`); por isso o modo analógico o desativa pelo `PConfig`
(que pode ser variável; 0 = desabilitado), e só o `VoltDiff` fica dentro do `If`.

## `Flow_Status` (gravado em `Vazao1s`)

0 ok · 1 modo inválido · 2 leitura analógica `NAN`/estouro · 3 resistor shunt não configurado (`Flow_Shunt_ohm ≤ 0`) · 4 contador saturado (≥ 16.777.216 no Scan) · 5 primeiro Scan
(sem intervalo de contagem). Valor ≠ 0 vira “leitura inválida” no servidor; nunca é enviado como medição.
Em pulsos, **0 pulso é leitura válida (vazão 0)**: não dá para distinguir “sem vazão” de “cabo solto” só pela contagem.

## Capacidade e limites (fonte: documentação oficial, ver `PESQUISA.md`)

| Item | Valor | Consequência |
|---|---|---|
| Frequência máxima na entrada de pulso (alta frequência) | 250 kHz (especificação CR1000X; a página da instrução cita 1 MHz para portas de controle: usei a especificação, mais conservadora) | confirme a frequência máxima do **seu** medidor |
| Contador | 24 bits por terminal; máx. 16.777.216 contagens por Scan | com Scan de 1 s o limite prático é o de 250 kHz; `Flow_Pulsos_1s` (IEEE4) é exato até esse valor; acima disso `Flow_Status = 4` |
| Limiar lógico | baixo < 0,8 V, alto > 2,5 V; pull-up de 100 kΩ a 5 V; máx. ±20 VDC sem dano | confirme o nível do sinal do medidor (coletor aberto serve; saída de 24 V **exige divisor** ou condicionador) |
| Contagem sem perdas | o contador é por hardware e conta entre execuções | sem perdas enquanto `PulseCount` rodar a cada Scan (e rodar em Scan de 1 s com folga) |
| Resolução da contagem | 1 pulso por registro | em baixa frequência a vazão por segundo é “em degraus” (K = 1000 pulsos/L: 1 pulso = 0,06 L/min); por isso o ensaio usa o total de pulsos |
| `Flow_Pulsos_Total` (Long) | diagnóstico; zera ao passar de 2 × 10⁹ ou ao reiniciar | **o servidor usa as contagens por registro**, não este total |
| Entrada diferencial 2 | `DiffChan 2` = SE 3/4 (terminais 2H/2L); faixa `mV5000`; as duas entradas devem ficar entre −100 mV e +5000 mV em relação ao terra | ver abaixo |

## Analógico 4–20 mA: não ligue sem confirmar

A página oficial da instrução `VoltDiff` **não trata de medir corrente**; o datalogger mede **tensão**. Para 4–20 mA a solução usual é um **resistor shunt de precisão**
(conclusão minha, a confirmar na documentação do instrumento e do CR1000Xe). Pontos a confirmar antes de ligar:

1. Valor do resistor: com `mV5000`, `20,5 mA × R` deve ficar abaixo de 5000 mV ⇒ **R ≤ ~243 Ω**; 250 Ω (1–5 V) estoura a faixa em 20 mA. Ex.: 100 Ω ⇒ 400–2000 mV. Resistor de precisão (0,1 %, baixo coeficiente térmico). O valor entra em `Flow_Shunt_ohm`.
2. Posição do resistor: as duas pontas (2H e 2L) precisam estar dentro de −100…+5000 mV em relação ao terra do datalogger.
3. Alimentação do laço (24 V externa ou do instrumento) e polaridade, conforme o manual do medidor.
4. Se a saída do medidor é realmente 4–20 mA (e não 0–20 mA, 0–10 V, etc.).
5. Proteção contra sobretensão no laço.

## O que ainda falta preencher (não inventei)

| Parâmetro | Onde | Estado |
|---|---|---|
| Modo (1 ou 2) | `Flow_Mode` em `BeginProg` | padrão 1 (pulsos); defina conforme o medidor |
| Fator K (pulsos/L) | Configurações → Medidor de Vazão | **vazio**: sem ele a vazão por pulsos fica indisponível |
| Resistor shunt (Ω) | `Flow_Shunt_ohm` em `BeginProg` | **0 = não configurado** (status 3) |
| Vazão em 4 mA / 20 mA e unidade | Configurações → Medidor de Vazão | **vazios** |
| Resolução do pluviômetro | Configurações → Pluviômetro | **vazia** (o CRBasic usa 0,2, a confirmar) |

## Impacto na aquisição atual

Acréscimos por Scan: um `PulseCount` (desprezível) e, no modo 2, um `VoltDiff` com 60 Hz e inversão (da ordem de dezenas de ms, como o `TCDiff` que você já usa).
Balança, termopar e pluviômetro não foram tocados. Confira em *Status* (`ProcTime`/`MaxProcTime`, `SkippedScan`) depois de carregar. A tabela `Vazao1s` ocupa pouco
(20.000 registros).

## Como carregar com segurança

1. Salve o programa atual (Device Configuration Utility/LoggerNet) e guarde o `.CR1X` original.
2. Compile `Pluviometria_Vazao.CR1X` no CRBasic Editor; resolva avisos.
3. Envie. As tabelas são recriadas: o servidor detecta “tabela reiniciada” e recomeça do primeiro registro (o histórico do banco é mantido).
4. No servidor use o perfil `programa_vazao` (`CR1000X_PROFILE=programa_vazao` ou Configurações + reiniciar).
5. Confira em *Numeric Monitor*: `Flow_Status = 0`, `Flow_Mode` esperado, e que `Peso_g`, `TempAgua_C`, `Pluvio_Basculadas_1s` continuam normais.

## Cálculos no CRBasic × servidor

| Grandeza | Onde | Observação |
|---|---|---|
| Pulsos por Scan, Hz, mV | CRBasic | brutos |
| mA = mV ÷ shunt | CRBasic | única conversão que depende do hardware |
| Vazão (L/min), volume, K, faixa 4–20 mA | **servidor** | uma só conversão; parâmetros editáveis sem reenviar o programa |
| Basculadas → mm | **servidor** (resolução da tela) | `Pluvio_Chuva_mm` do CRBasic é ignorado |
| Massa → volume → precipitação/vazão | **servidor** | densidade e área da tela |
