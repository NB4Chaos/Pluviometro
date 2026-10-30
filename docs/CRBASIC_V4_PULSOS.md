# CRBasic v4: medidor de vazão com 4–20 mA **e** pulsos

Arquivo: `crbasic/Pluviometria_v4_vazao_pulsos.CR1X`. Base: `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X` (o programa que está no
datalogger hoje, agora guardado dentro do projeto). **Não foi compilado aqui** (não há CRBasic Editor nesta máquina): compile e leia os
avisos antes de enviar.

## O que mudou em relação à v3

| Trecho | Mudança | Por quê |
|---|---|---|
| Balança, termopar, pluviômetro | **nenhuma** (diff conferido linha a linha) | não mexer no que funciona |
| `Flow_Status` | `If Flow_mA = NAN Then Flow_Status = 3` antes das comparações | na v3, `NAN < 4` e `NAN > 20` são falsos: uma leitura NAN saía com `Flow_Status = 0` |
| Constantes | `Flow_PConfig = 3`, `ScanSeg = 1`, `Flow_PulsoMax_Hz = 12000`, `Flow_PulsoSat = 16777215`, `Flow_TotMax = 2000000000` | parâmetros do canal de pulsos em um só lugar |
| Variáveis | `Flow_Pulsos` (Float), `Flow_PulsosTot` (Long), `Flow_PStatus` (Long), `Flow_Primeira` (Dim) | canal de pulsos |
| Tabela `Vazao1s` | 3 campos **no fim**: `Flow_Pulsos`, `Flow_PulsosTot`, `Flow_PStatus` | os 4 primeiros iguais à v3: o servidor antigo continua lendo |
| Scan | `PulseCount(Flow_Pulsos,1,P2,Flow_PConfig,0,1,0)` em todo Scan + estado | o `PulseCount` não pode ficar dentro de `If` |

## Os dois canais são medidos sempre; o método é escolhido no servidor

O CR1000Xe mede a corrente (RG1) **e** os pulsos (P2) em todo Scan e grava os dois. Analógico × Pulso é escolhido na interface (card de
Vazão) e gravado no `config.json`. **Nada é escrito no datalogger**: a conta continua somente leitura, nada volta ao padrão quando o
programa reinicia e os dois sinais ficam no histórico (dá para comparar e recalcular).

`Flow_mode` continua gravado com o valor 2 apenas para o servidor anterior funcionar com este programa (reversão sem trocar o CRBasic).

## Campos de `Vazao1s` (v4)

| Campo | Tipo | Significado |
|---|---|---|
| `Flow_mV` | IEEE4 | `Flow_mA × 10` (derivado, só compatibilidade; não é medição) |
| `Flow_mA` | IEEE4 | corrente em mA, como medida (mesmo fora de 4–20) |
| `Flow_Status` | Long | 0 = 4 a 20 mA · 1 = abaixo de 4 mA · 2 = acima de 20 mA · 3 = sem leitura (NAN) |
| `Flow_mode` | Long | sempre 2 (legado) |
| `Flow_Pulsos` | IEEE4 | pulsos contados **desde o Scan anterior** (contagem, não frequência; exata até 2²⁴) |
| `Flow_PulsosTot` | Long | acumulado das contagens válidas desde o início do programa; volta a 0 ao reiniciar ou ao passar de 2×10⁹ |
| `Flow_PStatus` | Long | 0 ok · 1 primeiro Scan (janela incompleta) · 2 contador saturado · 3 acima de 12 kHz · 4 sem leitura |

## Como o servidor usa os pulsos

- **Frequência** `f = Flow_Pulsos ÷ Δt`, com Δt = intervalo real entre o registro e o anterior da mesma tabela (1 s nominal; 2 s se um
  Scan foi pulado, porque o contador de hardware acumula). Sem registro anterior contíguo (início, lacuna > 2,5 s): Δt = 1 s, marcado
  como "janela presumida".
- **Vazão** `Q [L/min] = f ÷ K [pulsos/L] × 60`. K vem da interface (pulsos/L, pulsos/m³, L/pulso ou mL/pulso; guardado em pulsos/L).
- **Volume do ensaio** = diferença de `Flow_PulsosTot` entre os extremos ÷ K: não perde pulsos de registros ausentes. Se o acumulado
  diminuir no intervalo (programa reiniciado), volta à soma das contagens e o ensaio registra o motivo.
- **Comparação entre canais**: com os dois canais, a tela mostra a diferença pulsos − analógico e avisa quando a corrente indica vazão
  (> 2 % do span) e P2 fica sem pulsos por 5 leituras seguidas (cabo solto, saída desligada, K errado).

## Ligação dos pulsos: NÃO validada. Confirmar antes de ligar

Fontes: manual de operação SITRANS F M MAG 5000/6000 (ed. 05/2006) e especificações de pulso do CR1000X (Campbell Scientific).

| Item | MAG 5000 (manual) | CR1000Xe (especificação CR1000X) | Consequência |
|---|---|---|---|
| Saída ativa | 24 V DC, 30 mA, carga 1–10 kΩ | máx. ±20 V nas entradas de pulso | **não ligar a saída ativa direto** em P2 |
| Saída passiva | 3–30 V DC, máx. 110 mA, carga 200 Ω–10 kΩ | pull-up interno de 100 kΩ a 5 V | precisa de **pull-up externo** dentro de 200 Ω–10 kΩ |
| Níveis | — | baixo < 0,8 V, alto > 2,5 V | pull-up para o terminal 5V do CR1000Xe atende |
| Frequência | 0–10 kHz (50 % de ciclo) no modo frequência | alta frequência até 250 kHz; contato seco até 150 Hz | usar alta frequência (`PConfig = 3`) |
| Isolação | todas as entradas/saídas galvanicamente isoladas | — | ligar o comum da saída ao **G** do CR1000Xe |
| Terminais | saída digital 56/57/58 | P2 livre (P1 = pluviômetro; C5/C6 = balança) | confirmar a função de cada terminal no diagrama da unidade |

Proposta a ser conferida pelo responsável técnico (não validada): saída digital no modo **passivo**, resistor de 1 a 4,7 kΩ entre o
terminal de sinal e o **5V** do CR1000Xe, comum no **G**, sinal em **P2**, cabo blindado.

Também confirmar no transmissor: **Q<sub>max</sub>** (deve bater com a vazão em 20 mA configurada), **volume por pulso** ou f<sub>max</sub> (dá o K),
**largura do pulso** (W21 "pulse overflow" = pulsos perdidos no próprio transmissor), **corte de vazão baixa** (0–9,9 % de Q<sub>max</sub>: zera
**as duas** saídas) e **constante de tempo** (0,1–30 s: suaviza a saída analógica e a de frequência).

## Fator K

Não existe K padrão do MAG 5000: ele sai da configuração da saída digital.
- Modo pulso/volume: K = 1 ÷ (volume por pulso). Ex.: 1 mL/pulso → 1000 pulsos/L.
- Modo frequência: K = f<sub>max</sub> ÷ Q<sub>max</sub> (Q em L/s). Ex.: 10 kHz em 100 L/min (1,667 L/s) → 6000 pulsos/L.

Regra prática de resolução: o ensaio precisa de pelo menos ~1000 pulsos para que 1 pulso pese ≤ 0,1 % do volume (a tela e o resultado
do ensaio avisam abaixo de 200 pulsos). O `config.json` atual tem **K = 0,01 pulso/L** (1 pulso a cada 100 L), gravado em 27/10 sem
origem registrada: a 100 L/min isso dá 1 pulso por minuto, e um ensaio de 60 s contaria um único pulso (±100 % de quantização).
Confirme no transmissor antes de usar o método por pulsos.

## Como carregar com segurança

1. Guarde o programa atual (já está em `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X`) e faça o backup do projeto.
2. Compile `Pluviometria_v4_vazao_pulsos.CR1X` no CRBasic Editor; resolva avisos.
3. Envie pelo LoggerNet/Device Configuration Utility. As tabelas são recriadas: o servidor detecta o reinício pela âncora (número e
   horário do último registro) e recomeça do primeiro registro, sem regravar o histórico.
4. Numeric Monitor: `Flow_Status = 0`, `Flow_mA` igual ao de antes, `Flow_PStatus` 1 no primeiro Scan e 0 depois, `Peso_g`,
   `TempAgua_C` e `Pluvio_Basculadas_1s` normais. Tabela `Status`: `SkippedScan` não aumenta.
5. `python tools\probe_cr1000x.py --host <IP> --user <conta> --profile programa_vazao`: sem ERRO.
6. Só então ligue a saída de pulsos (seção acima) e confira contagem conhecida (gerador de pulsos ou totalizador do MAG).
