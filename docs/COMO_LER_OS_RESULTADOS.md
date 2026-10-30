# Como ler os resultados: pluviômetro × balança (mm e vazão)

Guia de leitura da interface do Monitor de calibração de pluviômetros. Para cada número exibido, diz **de onde ele vem, qual conta
é feita, em qual arquivo e linha está o código, e por que a conta é feita desse jeito**.

Os números de linha valem para a versão `monitor-pluviometro_simplificado` (interface simplificada). Se o código mudar, procure
pelo nome da função indicado ao lado.

Exemplo usado do começo ao fim: o ensaio de 21/10, com **15 basculadas**, **Δm = 102,3 g**, **ρ = 0,9982 g/cm³**, **A = 200 cm²**,
**r = 0,25 mm/basculada** e intervalo de referência de **59 s**. A resolução 0,25 ainda não foi confirmada; o CRBasic usa 0,2.

---

## Sumário

1. De onde vêm os dados brutos
2. O ensaio: quando começa, quando termina, quais leituras entram
3. Comparação em mm (Exibir → Precipitação)
4. Como interpretar o erro em mm
5. Comparação em vazão (Exibir → Vazão)
6. Método Comparativo: medidor de vazão × balança
7. Fora do ensaio: os números do período selecionado
8. "Por que esses dois números não batem?"
9. Limitações conhecidas dos cálculos atuais
10. Roteiro de leitura para ensinar a equipe
11. Mapa do código

---

## 1. De onde vêm os dados brutos

Todo cálculo parte de **dois dados medidos**: a massa e as basculadas. Antes de qualquer conta, é preciso saber exatamente o que
cada um representa.

### 1.1 Massa (balança MK30K1)

| Etapa | Onde | O que acontece |
|---|---|---|
| Leitura | `crbasic/Pluviometria.CR1X:244` | a cada Scan de 1 s, o datalogger lê a linha serial da balança e extrai o **primeiro número** (`Peso_g`) |
| Validade | mesmo arquivo, `StatusBal` | 0 = ok; 1 = nada recebido; 2, 3, 4 = linha incompleta, sem número ou fora da faixa |
| Gravação | tabela `Balanca1s` | um registro por segundo, com o **horário do datalogger** |
| Leitura pelo servidor | `datalogger.py:173` (`_mass`) | só aceita a massa se o status for `ok`. Qualquer outro caso vira `None` (ausente), **nunca 0** |
| Banco | tabela `samples`, coluna `mass_g` | uma linha por segundo; `NULL` = leitura inválida ou ausente |

**Por que "ausente" nunca vira zero:** zero grama é uma medida possível. Se uma falha virasse 0, uma conta de Δm poderia dar −1000 g
e parecer válida. Com `None`, a leitura é simplesmente pulada.

**Ponto de atenção:** a massa é a **leitura bruta** da balança (total no prato, com o recipiente). Por isso toda comparação usa
**diferença de massa** (Δm), nunca o valor absoluto (seção 3.2).

### 1.2 Basculadas (pluviômetro)

| Etapa | Onde | O que acontece |
|---|---|---|
| Contagem | `crbasic/Pluviometria.CR1X:158` (`PulseCount` em P1) | conta quantos fechamentos de contato houve **durante** aquele Scan de 1 s |
| Gravação | tabela `Pluviometro1s` (`.CR1X:108`) | `Pluvio_Basculadas_1s` = pulsos ocorridos no segundo **que terminou** no horário do registro |
| Leitura pelo servidor | `datalogger.py:264-265` | um registro com N pulsos vira **N eventos**, todos com o horário do registro e uma chave única |
| Banco | tabela `tips` | **uma linha por basculada**; a chave única (`src`) impede contar a mesma basculada duas vezes |

**Consequências práticas:**
- O horário de cada basculada tem **resolução de 1 s**. Uma basculada às 10:00:00,3 aparece como 10:00:01, o fim daquele Scan.
- O servidor **ignora** `Pluvio_Total` e `Pluvio_Chuva_mm` do CRBasic. A conversão de basculadas em mm é feita **uma única vez**, no
  servidor, com a resolução digitada em Configurações. Isso evita duas conversões diferentes (o CRBasic usa 0,2 e a tela pode usar
  outro valor).

### 1.3 Parâmetros que você digita (Configurações)

| Parâmetro | Símbolo | Unidade | Usado em |
|---|---|---|---|
| Resolução do pluviômetro | r | mm/basculada | basculadas → mm |
| Área de captação | A | cm² | volume ↔ mm |
| Densidade da água | ρ | g/cm³ | massa ↔ volume |
| Fator K | K | pulsos/L | medidor de vazão por pulsos |
| Vazão em 4 mA e em 20 mA | Q₄, Q₂₀ | unidade escolhida | medidor de vazão analógico |

**Regra:** se um parâmetro estiver vazio, a grandeza que depende dele aparece como **"—"** e, no resultado, com o motivo. Nenhum valor
é presumido.

**No ensaio, os parâmetros ficam congelados:** no momento em que o ensaio inicia, `trials.py` (função `start`) guarda uma cópia de r,
A, ρ, K, Q₄ e Q₂₀ junto com o ensaio. Mudar a configuração depois **não altera** um ensaio em andamento nem um concluído. Por isso,
no painel "Detalhes do ensaio", a linha "Parâmetros usados" mostra os valores **daquele** ensaio, que podem ser diferentes dos atuais.

---

## 2. O ensaio: quando começa, quando termina, quais leituras entram

Código: `trials.py`, funções `start` (linha 244), `tick` (272), `stop` (285), `_finish` (293) e `compute` (68).

### 2.1 A janela do ensaio

Ao clicar em **Iniciar ensaio**:

```
início = horário da última amostra já recebida + 1 ms      (trials.py:258)
fim    = início + duração × 1000 ms                         (trials.py:262)
janela = [início, fim)    → inclui o início, exclui o fim
```

- **Por que "+1 ms":** a leitura que já estava na tela quando você clicou **não** entra no ensaio. A primeira amostra do ensaio é a
  próxima que chegar. Isso evita usar uma massa medida antes do clique.
- **Por que "[início, fim)":** com intervalos semiabertos, uma amostra exatamente no fim pertence ao período seguinte. Assim dois
  ensaios ou períodos consecutivos nunca contam a mesma amostra duas vezes.
- **Relógio usado:** o do **datalogger** (o horário gravado em cada registro), nunca o do PC. O ensaio termina quando chega uma
  amostra com horário ≥ fim (`tick`), não quando o relógio do PC marca 60 s.

Com duração de 60 s e um registro por segundo, cabem **60 amostras**, nos instantes t, t+1, …, t+59 s.

### 2.2 Estados do ensaio (etiqueta no card da balança)

| Estado | Quando | Significado |
|---|---|---|
| Em andamento | entre o início e o fim | valores marcados como **parcial** |
| Concluído | chegou ao fim **e** passou nos critérios de qualidade | resultado utilizável |
| Incompleto | chegou ao fim, mas com lacunas ou menos de 95 % de leituras válidas da balança (`VALID_FRAC`, `trials.py:26`) | o motivo aparece em vermelho no card |
| Interrompido | encerrado pelo operador, ou sem dados 120 s depois do fim previsto | dados preservados; **não** use como calibração |

Critérios de qualidade (`trials.py:165-172`):
- **Cobertura:** o tempo sem amostras não pode passar de max(3 s, 2 % da janela) (`calc.window_coverage`, `calc.py:57`).
- **Ensaio gravimétrico:** pelo menos 95 % das amostras com massa válida.

### 2.3 Congelamento

Ao terminar, `_finish` **copia** as amostras e basculadas da janela para tabelas próprias do ensaio e calcula o resultado só com essa
cópia. O banco tem gatilhos que **recusam** qualquer alteração depois (`trials.py`, `SCHEMA`). Reabrir o ensaio no Histórico
mostra sempre o mesmo resultado, mesmo que a configuração ou os dados mudem depois.

---

## 3. Comparação em mm (Exibir → Precipitação)

Card da balança depois do ensaio (gravimétrico) → linhas: **Precipitação de referência**, **Precipitação do pluviômetro**,
**Erro do pluviômetro**, **Massa de água coletada**, **Massa atual**. O resto está em **Detalhes do ensaio**.

Toda a conta de mm está numa única função: **`calc.gravimetric`** (`calc.py:141`). Ela é chamada por `trials.compute`
(`trials.py:133`). A tela só exibe (`static/js/app.js:73`, `trialRows`; `static/js/trials.js:29`, `pluvHtml`).

### 3.1 Passo 1: escolher as duas leituras de massa (o intervalo de referência)

Código: `trials.py:127-130`

```python
mrows = [(r[0], r[1]) for r in rows if r[1] is not None]   # só massas válidas, em ordem de horário
(t0, m0), (t1, m1) = mrows[0], mrows[-1]                    # a PRIMEIRA e a ÚLTIMA válidas da janela
```

- **t0, m0:** horário e massa da primeira leitura válida do ensaio.
- **t1, m1:** horário e massa da última leitura válida.
- Leituras inválidas no meio **não atrapalham**: a conta só precisa das duas pontas.
- Se houver menos de duas leituras válidas, o resultado fica indisponível, com o motivo
  "sem duas leituras válidas de massa em instantes distintos" (`calc.py:153`).

**Exibido como:** "Massa inicial → final" e "Intervalo da referência (1ª à última leitura de massa)" (em Detalhes).

**Por que primeira e última, e não a média:** o que interessa é **quanta água entrou** no recipiente. Isso é a diferença entre o
fim e o começo. A média da massa (seção 3.8) não tem relação direta com o volume coletado.

**Por que o intervalo é de 59 s num ensaio de 60 s:** 60 amostras definem 59 intervalos entre elas, como 60 postes com 59 vãos.
A balança só "conhece" a massa nos instantes medidos, então a água que **certamente** entrou entre duas leituras é a dos 59 s
entre a primeira e a última. Dividir por 60 s seria errado: a massa do primeiro segundo da janela, antes da primeira leitura,
não foi medida.

### 3.2 Passo 2: massa de água coletada (Δm)

Código: `calc.py:157-158`

```
Δm = m1 − m0        [g]
```

Exemplo: Δm = **102,3 g**.

**Por que diferença e não valor absoluto:** a balança mede tudo o que está no prato: recipiente, água que já estava lá e a água
do ensaio. Na diferença, o recipiente e a água anterior aparecem nas duas leituras e se cancelam. Não importa se a balança foi
tarada ou não.

**Proteção:** se Δm < 0 (alguém esvaziou ou tarou a balança durante o ensaio), a referência fica indisponível com a mensagem
"a massa diminuiu no intervalo" (`calc.py:159-161`). Uma massa que diminui não pode ser água coletada.

### 3.3 Passo 3: volume (V)

Código: `calc.py:165-166`

```
V [cm³ = mL] = Δm [g] ÷ ρ [g/cm³]
```

Exemplo: V = 102,3 ÷ 0,9982 = **102,48 mL**.

**Por que dividir por ρ:** a densidade diz quantos gramas cabem em 1 cm³. A 20 °C, 1 cm³ de água pesa 0,9982 g, então 102,3 g
ocupam um pouco **mais** que 102,3 cm³. Usar ρ = 1 subestimaria o volume em 0,18 %.

**Por que 1 cm³ = 1 mL:** é a definição. Por isso o resultado sai direto em mL.

Exibido como **"Volume"** (Detalhes) ou **"Volume de referência"** (modo Vazão).

### 3.4 Passo 4: precipitação de referência (P_ref)

Código: `calc.py:169`

```
P_ref [mm] = 10 × V [cm³] ÷ A [cm²]
```

Exemplo: P_ref = 10 × 102,48 ÷ 200 = **5,124 mm**.

**De onde vem o "× 10":** precipitação é a **altura** que a água teria se ficasse parada sobre a área de captação. Altura =
volume ÷ área. Com volume em cm³ e área em cm², a altura sai em **cm**. Como 1 cm = 10 mm, multiplica-se por 10.

Conferência pelo princípio "1 mm sobre 1 m² = 1 L": 1 m² = 10 000 cm² e 1 L = 1000 cm³ → 10 × 1000 ÷ 10 000 = 1 mm. ✓

**Por que a área tem de ser a da boca do coletor:** a "chuva" que o pluviômetro deve medir é a que cai sobre a abertura dele.
Se você digitar a área errada, a referência fica errada **na mesma proporção**: 1 % de erro na área = 1 % de erro no resultado.
Meça o diâmetro interno do anel: A = π × d² ÷ 4. Com 200 cm², d = 159,6 mm.

Exibido como **"Precipitação de referência"** (com a etiqueta **ref.**), ou **"Precipitação gravimétrica"** em Detalhes.

### 3.5 Passo 5: basculadas no mesmo intervalo (N)

Código: `trials.py:132`

```python
n = sum(1 for t, _ in tips if t0 < t <= t1)
```

Conta as basculadas com horário **maior que t0 e menor ou igual a t1**.

**Por que exatamente esse intervalo, (t0, t1]:** é a nuance mais importante da comparação.
- A massa é **instantânea**: m0 é a massa **no instante** t0.
- A basculada registrada às t0 foi contada **durante o segundo que terminou em t0**, ou seja, (t0 − 1 s, t0]. Ela já tinha
  acontecido quando m0 foi medido; a água dela já estava na balança. Por isso **não entra**: `t0 < t`.
- A basculada registrada às t1 aconteceu durante (t1 − 1 s, t1], antes da medição de m1. A água dela está em m1. Por isso
  **entra**: `t <= t1`.

Assim as basculadas e o Δm representam **o mesmo trecho de tempo**. Se o intervalo fosse diferente, a comparação teria um erro
de até uma basculada em cada ponta.

Exibido como **"Pulsos (basculadas) no intervalo"** (Detalhes). Exemplo: N = **15**.

### 3.6 Passo 6: precipitação do pluviômetro (P_pluv)

Código: `calc.py:174`

```
P_pluv [mm] = N × r
```

Exemplo: P_pluv = 15 × 0,25 = **3,75 mm**.

**Por que essa conta:** por definição, cada basculada corresponde a r mm de chuva. É a **indicação** do instrumento em calibração,
exatamente como ele a reportaria em campo.

Exibido como **"Precipitação do pluviômetro"**.

### 3.7 Passo 7: diferença e erro percentual

Código: `calc.py:177-179`

```
Diferença [mm] = P_pluv − P_ref
Erro [%]       = (P_pluv − P_ref) ÷ P_ref × 100
```

Exemplo: diferença = 3,75 − 5,124 = **−1,374 mm**; erro = −1,374 ÷ 5,124 × 100 = **−26,82 %**.

**Convenção do sinal** (a mesma das normas de calibração: indicação − referência):
- **Negativo:** o pluviômetro indicou **menos** chuva do que a balança mediu (conta a menos).
- **Positivo:** indicou **mais** (conta a mais).

**Por que dividir por P_ref:** o erro é relativo ao **valor verdadeiro** (a melhor estimativa dele, que é a balança). Dividir por
P_pluv daria outro número (−36,6 % no exemplo) e não é a convenção usada.

Se P_ref = 0 (nenhuma água coletada), o erro fica indisponível, porque não existe divisão por zero.

### 3.8 O número grande do card da balança

Durante e depois do ensaio, o destaque do card é a **massa coletada (Δm)** do passo 3.2, não uma média. A média das leituras
de massa foi removida do resultado (desde 22/10): numa massa que cresce ao longo do ensaio ela não representa nada útil.
As leituras brutas, uma por segundo, continuam no CSV do ensaio para a planilha.

### 3.9 Intensidades (em Detalhes)

Código: `calc.py:170` e `calc.py:175`

```
Intensidade de referência [mm/h] = P_ref  ÷ (Δt ÷ 3600)
Intensidade do pluviômetro [mm/h] = P_pluv ÷ (Δt ÷ 3600)
Δt = t1 − t0 [s]
```

Exemplo, com Δt = 59 s:
- I_ref = 5,124 ÷ (59/3600) = **312,7 mm/h**
- I_pluv = 3,75 ÷ (59/3600) = **228,8 mm/h**

**Por que importa:** é a **intensidade de chuva simulada** no ensaio. O erro de um pluviômetro de báscula depende muito dela, e
as normas avaliam o erro **em cada intensidade** (WMO-No. 8, Anexo 6.C; EN 17277). **Sempre leia o erro junto com a intensidade
de referência.** Um erro de −27 % a 313 mm/h não diz nada sobre o erro a 30 mm/h.

**Repare:** as duas intensidades usam o **mesmo Δt**, então a razão entre elas é igual à razão entre as precipitações. O erro
percentual da intensidade é idêntico ao da precipitação.

---

## 4. Como interpretar o erro em mm

### 4.1 Antes de olhar o erro, confira estes cinco pontos

| # | Onde olhar | O que precisa estar certo | Se não estiver |
|---|---|---|---|
| 1 | Etiqueta do card | **Concluído** | Incompleto ou Interrompido: leia o motivo e não use o resultado |
| 2 | Detalhes → Parâmetros usados | r, A e ρ corretos **para aquele ensaio** | o resultado inteiro está deslocado; refaça o ensaio |
| 3 | Detalhes → Leituras de massa válidas | ≥ 95 % | a balança falhou durante o ensaio |
| 4 | Detalhes → Intensidade de referência | dentro da faixa que você quer avaliar | o resultado vale só para aquela intensidade |
| 5 | Detalhes → Pulsos no intervalo | ≥ 100 de preferência | o erro de quantização domina (4.2) |

### 4.2 O limite que o próprio método impõe: quantização

O pluviômetro só conta **basculadas inteiras**. Num instante qualquer, há uma concha parcialmente cheia: água que já entrou e ainda
não foi contada. Essa água pode valer entre 0 e 1 basculada, no começo **e** no fim do intervalo.

```
incerteza de quantização ≈ ± 1 basculada  =  ± r  (em mm)
em %:  ± r ÷ P_ref × 100   ≈   ± 100 ÷ N
```

| Basculadas no intervalo (N) | Erro possível só por quantização |
|---|---|
| 15 (ensaio de 21/10) | ± 6,7 % |
| 50 | ± 2 % |
| 100 | ± 1 % |
| 300 | ± 0,3 % |

**Conclusão:** para avaliar um instrumento cujo limite é ±4 % ou ±5 %, é preciso **N ≥ 100** basculadas por ponto. Com N = 15, o
resultado não consegue distinguir um bom pluviômetro de um ruim. O painel de Detalhes avisa isso: "Um basculamento a mais ou a
menos muda a precipitação do pluviômetro em r mm; em ensaios curtos isso domina a diferença" (`static/js/trials.js:40`).

### 4.3 O que cada padrão de erro costuma indicar (hipóteses para investigar)

| Padrão | Causas prováveis |
|---|---|
| Negativo, cresce com a intensidade | perda de água durante o movimento da báscula (comum em todo pluviômetro de báscula) |
| Constante em todas as intensidades | resolução r errada, área A errada ou báscula desregulada |
| Aleatório, grande em ensaios curtos | quantização (N pequeno) |
| Positivo | rebote do contato (pulso duplo), resolução r maior que a real, ou água entrando na balança por outro caminho |
| Muito negativo num ensaio curto | água ainda no funil ou na tubulação quando o ensaio terminou |

### 4.4 Reavaliando o ensaio de 21/10

| Item | Valor | Leitura |
|---|---|---|
| P_ref | 5,124 mm | referência |
| P_pluv | 3,75 mm (r = 0,25) | indicação |
| Erro | −26,82 % | conta a menos |
| Intensidade de referência | 313 mm/h | mais de 3× acima de 90 mm/h (o maior ponto da especificação) |
| N | 15 | quantização ± 6,7 % |
| Δt | 59 s | normas pedem pontos de pelo menos 30 min |

**Conclusão:** o resultado é coerente com intensidade excessiva + quantização + ensaio curto. **Não** serve para aprovar nem
reprovar o instrumento. Com r = 0,2, o erro seria −41,45 %, o que mostra que a resolução precisa ser confirmada antes de tudo.

**Exemplo de um ensaio bem dimensionado:** 30 mm/h por 60 min com A = 200 cm² → vazão de 10 mL/min, cerca de 600 g na balança,
P_ref ≈ 30,08 mm. O esperado é cerca de 120 basculadas com r = 0,25. Se o pluviômetro contar 118: P_pluv = 29,50 mm e
erro = **−1,94 %**, com quantização de ± 0,8 %. Esse resultado é interpretável.

---

## 5. Comparação em vazão (Exibir → Vazão)

**O que muda:** só a **forma de apresentar**. A conta de fundo é a mesma da seção 3, com os mesmos t0, t1, Δm e N. Trocar a
visualização não altera a aquisição, o ensaio nem o histórico. A escolha fica guardada só no seu navegador.

Card da balança depois do ensaio (gravimétrico), modo Vazão → **Volume de referência**, **Vazão de referência**,
**Volume do pluviômetro**, **Erro do pluviômetro**. Código da tela: `static/js/app.js:80-81` (`trialRows`).

### 5.1 Volume de referência

```
V_ref [mL] = Δm ÷ ρ                       (calc.py:165, o mesmo do passo 3.3)
```

Exemplo: **102,48 mL**.

### 5.2 Vazão de referência

Código: `calc.py:167`

```
Q_ref [L/min] = V_ref [L] ÷ (Δt [s] ÷ 60)
```

Exemplo: 0,10248 L ÷ (59/60 min) = **0,1042 L/min** = **104,2 mL/min**.

- **Por que Δt e não a duração configurada:** pelo mesmo motivo da seção 3.1. O volume foi medido entre t0 e t1.
- **Unidade na tela:** o servidor sempre calcula em L/min. A tela converte para a "Unidade de vazão" escolhida em Configurações →
  Exibição (`Flow.convert`, `static/js/util.js:26`). Se você escolher uma unidade **mássica** (kg/h, kg/s), a conversão usa ρ; sem ρ,
  aparece "—".

**Esta vazão é calculada, não medida.** A balança mede massa; a vazão é derivada da massa, da densidade e do tempo. Por isso o
número da balança continua em **g** mesmo no modo Vazão.

### 5.3 Volume do pluviômetro (volume equivalente)

Código: `static/js/app.js:23` (`volEq`)

```
V_pluv [mL] = P_pluv [mm] × A [cm²] ÷ 10
```

Exemplo: 3,75 × 200 ÷ 10 = **75,0 mL**. Equivale a **N × (volume de uma basculada)**: 15 × 5 mL.

**Por que essa conta:** é a conta da seção 3.4 ao contrário. Se o pluviômetro indicou 3,75 mm sobre 200 cm², a água que ele
"diz" ter recebido é 75 mL. Cada basculada vale **r × A ÷ 10** = 0,25 × 200 ÷ 10 = **5 mL**.

**Atenção:** a área usada é a **congelada no ensaio** (`g.area_cm2`), não a das Configurações atuais.

### 5.4 Erro em vazão

O card mostra **o mesmo erro %** da seção 3.7. Não é um descuido: matematicamente é o mesmo número.

```
Erro_volume = (V_pluv − V_ref) ÷ V_ref
            = (P_pluv × A/10 − P_ref × A/10) ÷ (P_ref × A/10)      → A/10 se cancela
            = (P_pluv − P_ref) ÷ P_ref = Erro_mm

Erro_vazão  = (V_pluv/Δt − V_ref/Δt) ÷ (V_ref/Δt)                  → Δt se cancela
            = Erro_volume
```

Conferência com o exemplo: (75 − 102,48) ÷ 102,48 = −26,82 % ✓, e (76,27 − 104,22) ÷ 104,22 = −26,82 % ✓.

**Lição para ensinar:** mm, mL e mL/min são **três formas de mostrar a mesma comparação**. O erro só mudaria se a área ou o tempo
fossem **diferentes** para os dois instrumentos, e o sistema garante que são os mesmos.

---

## 6. Método Comparativo: medidor de vazão × balança

Com **Método → Comparativo**, o botão da balança inicia um ensaio do tipo `flow`, que compara o medidor de vazão com a balança.
Código: `trials.py:90-121` (medidor) e `trials.py:145-157` (comparação).

### 6.1 Vazão instantânea do medidor (cada amostra de 1 s)

Código: `calc.py:184` (`flow_from_sample`)

| Modo | Fórmula | Se faltar parâmetro |
|---|---|---|
| Pulsos | Q [L/min] = f [Hz] ÷ K [pulsos/L] × 60 | sem K → "—" e "Informe o fator K" |
| 4–20 mA | Q = Q₄ + (I − 4) ÷ 16 × (Q₂₀ − Q₄), convertido para L/min | sem faixa → só o sinal em mA |

- **Por que × 60 (pulsos):** f ÷ K dá litros por **segundo**; × 60 dá litros por minuto.
- **Por que ÷ 16 (analógico):** a faixa útil do sinal vai de 4 a 20 mA, ou seja, tem 16 mA de largura.
- **Fora de 4–20 mA:** o resultado é "Fora da faixa", **sem extrapolar**. A corrente medida fica guardada.

### 6.2 Volume do medidor no ensaio

Código: `trials.py:108-114`

- **Pulsos:** V = Σ pulsos ÷ K. É a forma mais exata, porque conta cada pulso diretamente.
- **Analógico:** V = Σ (Qᵢ × wᵢ ÷ 60 000), uma integral da vazão no tempo. wᵢ é quanto tempo cada amostra representa
  (`calc.sample_weights_ms`, `calc.py:201`): até a próxima amostra, ou 1 s se houver lacuna. Assim uma lacuna não é preenchida
  com valores inventados.

### 6.3 Comparação com a balança, no mesmo intervalo

Código: `trials.py:147-156`

```
V_medidor [L] = volume do medidor nas amostras entre t0 e t1 (as mesmas pontas da balança)
V_ref [L]     = Δm ÷ ρ ÷ 1000
Erro [%]      = (V_medidor − V_ref) ÷ V_ref × 100
```

Exibido no card como **Vazão média do medidor**, **Volume do medidor**, **Volume pela balança (ref.)** e **Erro do medidor**.
**Mesma convenção de sinal:** negativo = o medidor indicou menos que a balança.

**Arranjo físico necessário:** para essa comparação valer, a água que passa pelo medidor tem de ser a mesma que cai na balança.

---

## 7. Fora do ensaio: os números do período selecionado

Quando **não há ensaio**, os cards e os gráficos mostram o **Período** escolhido (1 min, 15 min, 1 h…). São números de
**acompanhamento**. Os resultados de **calibração** são os do ensaio (seções 3 a 6).

### 7.1 Card do pluviômetro (Precipitação)

Código: `calc.py:66` (`precip_period`), chamado em `app.py:391`; tela em `static/js/app.js:134` (`renderPluv`).

| Número | Conta | Detalhe |
|---|---|---|
| **Precipitação acumulada** | N_período × r | N = basculadas com horário em [início, fim) do período |
| **Basculadas** | N_período | contagem bruta |
| **Intensidade média** | (basculadas nos trechos cobertos × r) ÷ (tempo coberto em horas) | ver abaixo |
| etiqueta **parcial** | tempo sem amostras > max(3 s, 2 % do período) | período não totalmente coberto por dados |

**Por que a intensidade usa "tempo coberto" e não a duração do período:** se o servidor ficou desligado 10 min de um período de
15 min, dividir por 15 min subestimaria a intensidade 3 vezes. O código mede quanto tempo **realmente** tem dados
(`calc.covered_intervals`, `calc.py:38`) e divide por ele. Por isso aparece a etiqueta **parcial**: o valor é calculado só sobre o
trecho com dados.

**Por que a intensidade "dá saltos" em períodos curtos:** com r = 0,25 mm, uma única basculada em 1 min vale 15 mm/h. Em janelas
curtas a intensidade só pode assumir múltiplos disso. É uma característica do instrumento, não um erro.

### 7.2 Card do pluviômetro (Vazão)

Código: `static/js/app.js:23-24` (`volEq`, `flowEq`)

```
Volume equivalente [mL]  = Precipitação acumulada [mm] × A ÷ 10
Vazão equivalente        = Intensidade média [mm/h] × A ÷ 10   → mL/h → convertido para a unidade escolhida
```

Usa a área **atual** das Configurações. Sem área → "—" e "Informe a área de captação".

### 7.3 Card da balança sem ensaio

| Modo | Número | Código |
|---|---|---|
| Precipitação | **Média do período**: média aritmética das massas válidas no período | `app.py:221` (`stats`) |
| Vazão | **Vazão pela balança** e **Volume coletado**: a mesma conta da seção 3 (primeira e última massa válida do período) | `app.py:231` (`period_grav`) → `calc.gravimetric` |

Se a massa **diminuiu** no período (alguém esvaziou a balança), a vazão fica "—" com o motivo em vermelho. Uma massa que diminui
não representa água coletada.

### 7.4 Gráficos

Código: `static/js/app.js:212` (`refreshCharts`) e `static/js/charts.js`.

- **Linha contínua:** os valores medidos, segundo a segundo. Em períodos longos, cada ponto é a média das leituras válidas de um
  trecho, com no máximo cerca de 600 pontos (`app.py:398`, `series`).
- **Linha tracejada cinza:** média do período (só leituras válidas).
- **Número grande no topo:** o **resultado do período**: Δm (massa coletada), precipitação acumulada ou temperatura média. No
  modo Vazão, a vazão pela balança e o volume equivalente do pluviômetro.

---

## 8. "Por que esses dois números não batem?"

| Você vê… | …e também… | Por que são diferentes |
|---|---|---|
| Precipitação do pluviômetro **no ensaio** (card da balança) | Precipitação acumulada **no card do pluviômetro** | o card da balança conta (t0, t1] **do ensaio**; o do pluviômetro conta o **período** selecionado (ex.: 15 min) |
| Pulsos no intervalo (ex.: 4) | Basculadas do ensaio no CSV (ex.: 5) | o intervalo de referência (t0, t1] é ~1 s menor que a janela do ensaio; uma basculada no 1º segundo fica fora (seção 3.5) |
| Intervalo da referência 59 s | Duração 60 s | 60 amostras = 59 intervalos (seção 3.1) |
| Média de massa do ensaio | Massa de água coletada | média = nível médio do prato; Δm = água que entrou. Grandezas diferentes |
| Intensidade média do período | Intensidade de referência do ensaio | períodos diferentes; e a do período divide pelo **tempo coberto** |
| Erro em mm | Erro em vazão | **são iguais** (seção 5.4); se forem diferentes, há bug |
| Valores mudam quando altero r, A ou ρ | Ensaio antigo não muda | o ensaio usa os parâmetros congelados no início (seção 1.3) |

---

## 9. Limitações conhecidas dos cálculos atuais

Pontos que o software **ainda não** faz e que um procedimento de calibração completo exige. Nenhum deles invalida a conta
mostrada, mas eles limitam a exatidão.

| # | Limitação | Efeito típico | O que seria o correto |
|---|---|---|---|
| L1 | ρ é um valor fixo digitado | até ≈ 0,1 % entre 15 e 25 °C | calcular ρ pela temperatura média da água no ensaio (fórmula de Tanaka et al., 2001) |
| L2 | Sem correção de empuxo do ar | ≈ +0,1 % (sistemático) | m = I × (1 − ρ_ar/ρ_peso) ÷ (1 − ρ_ar/ρ_água) |
| L3 | O intervalo de referência é a janela de tempo, não instantes de basculada | quantização de ± 1 basculada | começar e terminar o intervalo exatamente em basculadas |
| L4 | Cada ensaio é isolado | sem curva de erro × intensidade nem repetibilidade | série de ensaios por intensidade, com 3+ repetições |
| L5 | Sem cálculo de incerteza | não dá para declarar conformidade | balanço de incerteza (JCGM 100 / GUM) |
| L6 | ~~Medidor de vazão deslocado em 1 amostra~~ | corrigido em 22/10: o medidor usa (t0, t1], como as basculadas | — |
| L7 | A massa usada é a primeira e a última **leitura bruta**, uma por segundo | ruído da balança em cada ponta | média de algumas leituras estáveis em cada ponta |
| L8 | Leitura da balança aceita mesmo com o prato instável | ruído em m0 e m1 | validar o indicador de estabilidade da MK30K1 no CRBasic |

---

## 10. Roteiro de leitura para ensinar a equipe

Use esta sequência ao olhar qualquer resultado de ensaio gravimétrico:

1. **Estado:** está **Concluído**? Se não, leia o motivo e pare aqui.
2. **Parâmetros usados** (Detalhes): r, A e ρ corretos?
3. **Intensidade de referência:** é a intensidade que queríamos testar?
4. **Pulsos no intervalo:** N ≥ 100? Se N < 100, o erro tem pelo menos ± 100/N % de incerteza só por quantização.
5. **Massa de água coletada:** faz sentido com o que foi despejado?
6. **Erro do pluviômetro:** sinal (− conta a menos, + conta a mais) e tamanho, sempre **junto com a intensidade**.
7. **Compare com o limite** do procedimento do laboratório **na mesma intensidade**.
8. **Repita** o ponto pelo menos 3 vezes antes de concluir.

Frase para resumir a conta inteira:

> **"A balança diz quanta água entrou (Δm). Dividindo pela densidade temos o volume, e dividindo pela área temos os mm de
> referência. O pluviômetro diz quantas basculadas contou no mesmo intervalo; vezes a resolução, temos os mm indicados.
> O erro é a diferença dividida pela referência."**

---

## 11. Mapa do código

| Grandeza na tela | Calculada em | Exibida em |
|---|---|---|
| Massa inicial → final, Intervalo da referência | `trials.py:127-130` (escolha de t0, t1) | `static/js/trials.js:35-37` |
| Massa de água coletada (Δm) | `calc.py:157-158` | `static/js/app.js:83`, `trials.js:36` |
| Volume / Volume de referência | `calc.py:165-166` | `app.js:80`, `trials.js:36` |
| Precipitação de referência | `calc.py:169` | `app.js:82`, `trials.js:31` |
| Pulsos no intervalo (N) | `trials.py:132` | `trials.js:34` |
| Precipitação do pluviômetro | `calc.py:174` | `app.js:82`, `trials.js:31` |
| Diferença, Erro do pluviômetro | `calc.py:177-179` | `app.js:83`, `trials.js:32` |
| Intensidades de referência e do pluviômetro | `calc.py:170`, `calc.py:175` | `trials.js:33` |
| Vazão de referência / gravimétrica | `calc.py:167` | `app.js:80`, `trials.js:34` |
| Volume do pluviômetro (equivalente) | `static/js/app.js:23` (`volEq`) | `app.js:81` |
| Leituras de massa válidas, estado do ensaio | `trials.py:137`, `trials.py:165-172` | `trials.js:37`, `app.js:115-116` |
| Vazão do medidor (pulsos / 4–20 mA) | `calc.py:184` | `app.js:155` (`renderCor`) |
| Volume do medidor, Erro do medidor | `trials.py:108-114`, `trials.py:147-156` | `app.js:75-77`, `trials.js:23-24` |
| Precipitação acumulada e intensidade média do período, "parcial" | `calc.py:66` (`precip_period`), `calc.py:38`, `calc.py:57` | `app.js:134` (`renderPluv`) |
| Volume e vazão equivalentes do pluviômetro (período) | `static/js/app.js:23-24` | `app.js:140-142` |
| Média do período (balança, temperatura) | `app.py:221` (`stats`) | `app.js:109`, `app.js:217-223` |
| Vazão pela balança e volume coletado (período) | `app.py:231` (`period_grav`) → `calc.gravimetric` | `app.js:108`, `app.js:218` |
| Conversão entre unidades de vazão | `calc.py:21` (servidor), `static/js/util.js:26` (tela) | todas as vazões |
| Testes que conferem as contas à mão | `tests/test_calc.py`, `tests/test_trials.py` | `python -m pytest tests` |

**Referências:** WMO-No. 8, *Guide to Instruments and Methods of Observation*, Vol. I, Cap. 6 e Anexo 6.C (calibração de
pluviômetros); EN 17277:2019, *Hydrometry — Measurement requirements and classification of rainfall intensity measuring
instruments*; JCGM 100:2008 (GUM); Tanaka et al. (2001), *Metrologia* 38, 301 (densidade da água).
