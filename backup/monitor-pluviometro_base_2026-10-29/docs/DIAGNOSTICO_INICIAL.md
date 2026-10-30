# Diagnóstico inicial — Monitor de calibração de pluviômetros (Elus)

Data: 21/10/2026 · Base: `monitor-pluviometro_revisado.zip` (código lido arquivo a arquivo) · Nenhum arquivo do projeto foi alterado.

Legenda usada em todo o documento:

- **[CONFIRMADO]**: lido no código ou calculado de forma independente. Diz o que o *programa* faz, não o que o *hardware* faz.
- **[CONTRADIÇÃO]**: o contexto informado e o código discordam. Precisa decidir qual fonte vale.
- **[HIPÓTESE]**: explicação plausível, ainda sem teste.
- **[A VERIFICAR]**: depende de um documento, de uma medição ou de olhar a bancada.

Linha de base do software: `python -m pytest tests` deu **71 testes aprovados** (Python 3.13). Esses testes usam o emulador
`tests/fake_*.py`, não o CR1000Xe real. Eles provam a lógica do servidor, não a aquisição física.

---

## 0. Resumo para a gerência (5 pontos)

1. O software está bem estruturado. Ele não inventa dados, não transforma `NAN` em zero e congela cada ensaio no banco com gatilhos SQL.
   A parte frágil está **antes** do software: a leitura serial da balança é experimental, a configuração da entrada de pulsos não foi
   conferida e a resolução do pluviômetro está divergente.
2. A **resolução do pluviômetro está divergente**. O contexto diz 0,25 mm. O programa CRBasic diz 0,2 mm. O `config.example.json` diz 0,2 mm.
   Com 15 basculadas, isso muda o erro do ensaio de −26,8 % para −41,5 %. Enquanto isso não for resolvido, nenhum número de erro é defensável.
3. O ensaio de 21/10 alimentou cerca de **307 mm/h** de intensidade equivalente. Isso é mais de 3× o maior ponto de especificação citado
   (90 mm/h). Pluviômetros de báscula sabidamente **contam a menos** em intensidades altas, porque perdem água durante o basculamento.
   Um resultado negativo grande é coerente com isso. O ensaio não serve para aprovar nem reprovar o instrumento.
4. Os "59 s" **não são defeito**. É o tempo entre a primeira e a última leitura de massa usadas no cálculo. O erro percentual de
   volume/precipitação **não depende** dessa duração. Ela só afeta a vazão e a intensidade.
5. A senha **não é lida do keyring** no código atual, só da variável de ambiente `DATALOGGER_PASSWORD`. O contexto dizia que era. Isso
   precisa ser decidido e corrigido.

---

## 1. Arquitetura (como está no código)

### 1.1 Física e ligação (segundo os comentários do CRBasic, sem conferência na bancada)

| Instrumento | Sinal | Entrada no CR1000Xe (comentário do `.CR1X`) | Situação |
|---|---|---|---|
| Balança MK30K1 | RS-232 (DB9) | `ComC5`: TX da balança → C6, RX da balança → C5, GND → G | [A VERIFICAR] níveis elétricos RS-232 × terminais C, pinagem do DB9 |
| Termopar tipo T | mV diferencial | 1H (+), 1L (−) | [A VERIFICAR] na bancada |
| Pluviômetro | contato seco | P1 – G | [A VERIFICAR] na bancada; código de `PConfig` sob suspeita (§5) |
| Medidor de vazão | pulsos P2 ou 4–20 mA em 2H/2L (shunt) | só no `Pluviometria_Vazao.CR1X` | em desenvolvimento |
| Vaisala | — | **removida** do programa (comentário na linha 25) | sem integração; a interface não tem painel ambiental |

**Arranjo hidráulico (onde está a balança): [A VERIFICAR].** O software assume, em `calc.gravimetric`, que a massa **aumenta**
quando a água é coletada (Δm = m_fim − m_início ≥ 0; se diminuir, ele recusa o cálculo). Então o código pressupõe que a balança pesa
um recipiente que **recebe** água. Ele não sabe se essa água é a que saiu do pluviômetro.

### 1.2 Aquisição: `crbasic/Pluviometria.CR1X` [CONFIRMADO no código]

- Um único `Scan(1,Sec,0,0)` (linha 146). A cada 1 s ele faz, em sequência:
  - termopar: `PanelTemp` + `TCDiff(...,TypeT,PTemp_C,...,60,...)`, nas linhas 151 e 153. `PTemp_C` **é** a temperatura do painel do datalogger,
    usada como junta de referência. Não é a temperatura da água.
  - pluviômetro: `PulseCount(Pluvio_Basculadas_1s,1,P1,1,0,1,0)` na linha 158. Ele conta os pulsos ocorridos naquele Scan.
    `Pluvio_Total` acumula esses pulsos e **zera quando o programa reinicia**. `Pluvio_Chuva_mm = Total × 0,2`.
  - balança: lê até 8 linhas terminadas em LF, usa a última completa e extrai o **primeiro número** com
    `SplitStr(...,"",3,0)` (linha 242). O próprio código diz: "Extracao experimental: validar com mensagem real da MK30K1".
- Tabelas, com 20 000 registros cada:
  - `Balanca1s`: `Peso_g`, `StatusBal`, `LinhaNova`, `BaudInUse`, `LastLine`. Grava a cada Scan.
  - `Termopar1s`: `TempAgua_C`, `PTemp_C`. Grava a cada Scan.
  - `Pluviometro1s`: `Pluvio_Basculadas_1s`, `Pluvio_Total`, `Pluvio_Chuva_mm`, com `DataInterval(0,1,Sec)`.
  - `Resumo`: contadores OK/falha da balança, gravados a cada 1 min.
- Códigos de `StatusBal` no CRBasic:
  - 0: OK
  - 1: nenhum byte recebido no Scan
  - 2: chegaram bytes, mas nenhuma linha completa
  - 3: linha curta ou sem dígitos
  - 4: valor fora de −100…31 000 g

  O perfil mapeia 0 → ok, 1 → no_comm e 2/3/4 → invalid. **Mapeamento coerente com o CRBasic [CONFIRMADO].**

### 1.3 Comunicação: `datalogger.py` [CONFIRMADO no código]

- O servidor chama `GET http://<host>/?command=DataQuery&uri=dl:<Tabela>&mode=since-record&p1=<nº>&format=json` com Basic Auth.
  Faz uma consulta por tabela a cada ciclo (`_get`, `_pull`).
- O **cursor** fica em `cursor_cr1000x.json`: o próximo número de registro a pedir, por tabela.
- O cursor só avança **depois** que o SQLite gravou (`ack()`). Por isso uma queda do servidor não perde dados: na volta, ele relê do datalogger.
- **Marca d'água** (`read`): só entrega as linhas até o instante em que **todas** as tabelas já chegaram. O resto fica para a próxima rodada.
- As linhas das três tabelas são casadas pelo horário do datalogger, com tolerância de 500 ms (`_match`).

### 1.4 Aplicação: `app.py`, `calc.py`, `trials.py`, frontend [CONFIRMADO no código]

- `acquire()` roda num laço de aproximadamente 1 s: `dl.read()` → `store_reading()` → SQLite → `dl.ack()` → `sio.emit("sample")`.
- SQLite `dados_cr1000x.db`:
  - `samples`: uma linha por segundo, com `ts` igual ao **horário do datalogger**.
  - `tips`: **uma linha por basculada**, com uma chave única que impede contar a mesma basculada duas vezes.
  - `trials`, `trial_samples`, `trial_tips`: ensaios encerrados e imutáveis.
- O frontend usa **as duas coisas**:
  - Socket.IO, com os eventos `sample` e `trial` (`static/js/api.js`).
  - Polling HTTP: `/api/summary` ou gráficos a cada 3 s, e um relógio local de 1 s (`app.js:346-347`).
- Cálculos:
  - precipitação = nº de eventos × `tip_resolution_mm` **da tela**. O `Pluvio_Chuva_mm` do datalogger é ignorado.
  - referência gravimétrica: `calc.gravimetric`.
  - vazão: `calc.flow_from_sample`.

---

## 2. Informações confirmadas no código

| # | Fato | Onde |
|---|---|---|
| 1 | `NAN` vira `None` (ausente), nunca zero | `datalogger._num` |
| 2 | Massa só é aceita se o status mapear para `ok`. Status desconhecido vira `invalid` | `datalogger._mass` |
| 3 | `Pluvio_Basculadas_1s` é a contagem de pulsos no Scan de 1 s. Cada registro gera N eventos com o horário do registro | `.CR1X:158`, `datalogger.read` |
| 4 | O total de basculadas do dashboard vem do SQLite (eventos), não de `Pluvio_Total` | `app.tips_total` |
| 5 | Resolução, área, densidade, K e faixa 4–20 mA começam **vazias** (`None`) e não há valor presumido | `app.DEFAULTS` |
| 6 | O ensaio guarda uma cópia (snapshot) da configuração no início e as amostras no fim. Depois disso nada pode ser alterado | `trials.SCHEMA` (gatilhos) |
| 7 | A referência gravimétrica usa a **variação** de massa (Δm), não a massa absoluta | `calc.gravimetric` |
| 8 | O erro usa a convenção (pluviômetro − referência) / referência × 100 | `calc.gravimetric` |
| 9 | Precipitação de referência: P(mm) = 10 · V(cm³) / A(cm²). Dimensionalmente correto: cm³/cm² = cm = 10 mm | `calc.gravimetric` |
| 10 | Pulsos para vazão: Q = f/K × 60. Sem K, o resultado é `None` | `calc.flow_from_sample` |
| 11 | 4–20 mA: interpolação linear. Fora de 4–20, não extrapola (`None`) e o estado vira `out_of_range` | `calc.flow_from_sample`, `app.cor_class` |
| 12 | A interface mostra "desatualizada" após 8 s sem amostra nova | `docs/DIAGNOSTICO.md` item 8 (não reconferido no JS) |
| 13 | Não aparece "Coriolis" em nenhum texto da interface. Só nas descrições dos perfis e num teste | `grep` |

---

## 3. Contradições entre o contexto e o código

| # | Assunto | Contexto | Código | Impacto | Como resolver |
|---|---|---|---|---|---|
| C1 | **Resolução do pluviômetro** | 0,25 mm/basculada | `Const Pluvio_mmPorBasculada = 0.2` (`.CR1X:34`); `config.example.json`: `0.2`. O comentário do CRBasic diz "Confirmar a resolução real do sensor" | erro do ensaio: −26,8 % (0,25) ou −41,5 % (0,2) | ficha técnica do modelo + teste volumétrico estático (§8.4). Ver também o valor salvo no seu `config.json` real, que não veio no ZIP |
| C2 | **Credenciais por keyring** | `keyring` com o serviço `Elus-CR1000Xe` | nenhuma ocorrência de `keyring` no código nem no `requirements.txt`. A senha vem **só** de `DATALOGGER_PASSWORD` (`datalogger.py:115`) | se a variável não estiver definida, ele autentica com senha vazia e recebe 401. O erro aparece em `/api/diag` | decidir se o `app.py` deve ler do keyring (mudança pequena) ou se a variável é definida no script de inicialização |
| C3 | Usuário | `admin` | `config.example.json`: `dashboard`; interface: "conta somente leitura" | `admin` tem permissão de escrita no datalogger | criar uma conta somente leitura no CR1000Xe (Device Configuration Utility) |
| C4 | `PConfig` da entrada de pulsos | P1 = contato seco | P1 usa `PConfig = 1`, com o comentário "Switch Closure with pull-up". O programa de vazão usa `PConfig = 3` = "alta frequência, pull-up" e `0` = "desliga o P2" | se os códigos estiverem trocados, a entrada pode estar no modo errado para um contato seco (sem pull-up ou sem *debounce*), e isso causa **perda ou excesso de contagens**. Em outros dataloggers Campbell, que eu me lembro, a numeração é diferente (0 = alta frequência, 1 = AC de baixo nível, 2 = fechamento de contato). **Não confirmei para o CR1000Xe** | abrir o CRBasic Editor → Help → `PulseCount` → tabela PConfig do CR1000Xe. Comparar com as linhas 158 (P1) e 224/226 do programa de vazão |
| C5 | Programa carregado | "programa atual" | existem dois: `Pluviometria.CR1X` (perfil `programa_atual`) e `Pluviometria_Vazao.CR1X` (perfil `programa_vazao`) | se o perfil não bater com o programa, alguma tabela não existe e a aquisição para | olhar no datalogger: tabela `Status`, campos `ProgName` e `ProgSig` |
| C6 | Balança "desconectada" | `NAN` + `StatusBal = 1` | coerente: status 1 = nenhum byte no Scan | — | [CONFIRMADO] |

---

## 4. Ainda precisa ser verificado

**Físico / elétrico**
1. Arranjo hidráulico: o que a balança pesa e se é a mesma água que passou pelas básculas.
2. Área efetiva da boca do coletor (200 cm² = diâmetro ≈ 159,6 mm). Medir o diâmetro interno do anel.
3. Resolução real da báscula (C1).
4. Pinagem do DB9 da MK30K1 e compatibilidade de nível RS-232 com os terminais C5/C6 do CR1000Xe (manuais dos dois).
5. Ligação do termopar em 1H/1L e polaridade.

**CRBasic / datalogger**

6. Formato exato da linha serial da MK30K1: baud, paridade, terminador, unidade e indicador de estabilidade.
   - O CRBasic abre em 9600 baud com `SerFmtBal = 3`. O significado do código 3 precisa ser conferido no Help de `SerialOpen`.
   - O `SplitStr` pega o **primeiro número** da linha. Se a MK30K1 envia algo antes do peso (número de série, código, número do ID), o peso estará errado.
   - Leituras **instáveis** (balança em movimento) são aceitas, porque o código não verifica o indicador de estabilidade.
7. `PConfig` de P1 (C4).
8. Se ocorrem *skipped scans*: tabela `Status`, campo `SkippedScan`. A leitura serial pode bloquear até 8 × 100 ms dentro de um Scan de 1 s.
9. Relógio do datalogger × relógio do PC: o código assume o mesmo fuso e a mesma hora local (`_ts_ms`).

**Software (no seu PC)**

10. Conteúdo real do `config.json`: resolução, área e densidade. **Não veio no ZIP.**
11. Valor de `DATALOGGER_PASSWORD` no ambiente (só se existe, nunca o valor), interpretador `.venv` e pasta de execução.
12. Resultado salvo do ensaio de 21/10: `GET /api/trials` e `/api/trials/<id>/raw.csv`. Isso mostra Δm, t0, t1 e a resolução usada.

---

## 5. Riscos de erro de medição (por ordem de impacto)

| # | Risco | Camada | Efeito | Confirmação |
|---|---|---|---|---|
| M1 | Resolução errada (C1) | config | erro sistemático de 25 % entre 0,2 e 0,25 | ficha técnica + teste estático |
| M2 | **Intensidade alta demais** (~307 mm/h) | procedimento | contagem a menos por perda durante o basculamento (efeito conhecido em básculas) | repetir em 3+ intensidades ≤ 90 mm/h |
| M3 | Volume retido no ensaio curto | metrologia | sobra água no funil e na báscula, até cerca de 1 basculada (5 mL com 0,25 mm e 200 cm²). Em 100 mL isso é até cerca de 5 % | ensaios mais longos; contar o tempo até a última basculada; pesar o retido |
| M4 | Balança pesando outra água / Δm não correspondente | físico | a comparação perde o sentido | verificar o arranjo |
| M5 | Peso extraído do campo errado da linha serial | CRBasic | massa errada com `StatusBal = 0` (parece válida) | comparar `LastLine` (gravado na tabela) com o visor |
| M6 | Leitura instável aceita | CRBasic | ruído em Δm | verificar a flag de estabilidade no manual |
| M7 | `PConfig` inadequado em P1 | CRBasic | basculadas perdidas ou duplicadas (rebote do contato) | teste manual: 20 basculadas lentas e 20 rápidas, comparar com a contagem |
| M8 | Quantização no tempo: massa instantânea × contagem por segundo | método | ±1 s nas fronteiras | o código já usa (t0, t1] de forma coerente (`trials.py:126-127`) |
| M9 | Densidade fixa 0,9982 (≈ 20 °C) | metrologia | pequeno: ≈ 0,1 % entre 15 e 25 °C | usar `TempAgua_C` média do ensaio + tabela de densidade |

## 6. Riscos de comunicação

| # | Risco | O que acontece no código | Como enxergar |
|---|---|---|---|
| R1 | Senha não definida (C2) | 401 a cada consulta; `link.error` mostra a mensagem | `/api/diag` → `link.error` |
| R2 | Perfil ≠ programa (C5) | DataQuery de uma tabela inexistente gera exceção, e o ciclo inteiro falha (todas as tabelas são consultadas juntas) | `link.error`; log `servidor.log` |
| R3 | Tabela reiniciada (programa reenviado) | `"Lacuna em Balanca1s: pedi o registro 15685 e veio 0"` | ver §6.1 |
| R4 | Perda de registros por buffer circular | 20 000 registros ≈ 5,5 h a 1 s. Com o servidor parado por mais tempo, os mais antigos são sobrescritos e aparece "Lacuna" com número **maior** que o pedido | contador `gaps` em `/api/diag` |
| R5 | Relógios diferentes | o ensaio usa o horário do datalogger. A latência mostrada (`clock_skew_s`) mistura atraso e desvio de relógio | `/api/diag` → `lat_ms` |
| R6 | Falha numa tabela derruba as outras | `read()` consulta todas. Uma exceção em uma descarta o ciclo inteiro | `link.error` |
| R7 | Join por horário falha | massa ou temperatura vira "sem comunicação" mesmo existindo no datalogger | `join_miss` em `/api/diag` |

### 6.1 "Lacuna em Balanca1s: pedi o registro 15685 e veio 0"

O código (`datalogger.py:162-164`) registra "lacuna" sempre que o primeiro registro devolvido não é o pedido.

- **[HIPÓTESE principal]** O programa foi reenviado ou recompilado, ou a tabela foi zerada. Nos dataloggers Campbell, o número de registro
  normalmente continua crescendo mesmo quando o buffer circular sobrescreve, e só volta a 0 quando a tabela é recriada.
  Pedir `since-record 15685` numa tabela nova, com menos registros, fez a API devolver a partir do 0.
  - Como confirmar: comparar a hora do ocorrido no log com a hora de compilação na tabela `Status` (`ProgName`, `StartTime`/`CompileResults`)
    ou com o histórico do LoggerNet/Device Configuration.
  - Resultado esperado: as duas horas coincidem.
- **Consequência no código:** os dados novos **são** lidos (a partir do 0), mas o fato é rotulado como "lacuna" e não como "tabela
  reiniciada". O tratamento de reinício (linhas 154-160) só é acionado quando a resposta vem **vazia**. É um problema de diagnóstico
  (rótulo enganoso), não de perda de dados. Fica como correção na fase 2.
- **Hipótese alternativa:** buffer sobrescrito (R4). Nesse caso viria um número **maior** que 15685, não 0. Por isso é menos provável.

---

## 7. O problema dos 59 s × 60 s

**[CONFIRMADO no código]**

1. Ao iniciar, `trials.start()` define `start = último ts + 1 ms` e `end = start + 60 000 ms`. A janela é **[start, end)**.
2. Com um registro por segundo, cabem **60 amostras** nessa janela, nos instantes t, t+1, …, t+59 s.
3. `trials.compute()` pega a **primeira** e a **última** massa válidas: `(t0, m0), (t1, m1) = mrows[0], mrows[-1]`.
4. `calc.gravimetric()` calcula `duration_s = (t1 − t0)/1000 = 59 s`.
5. O frontend mostra isso com o rótulo **"Tempo entre as leituras de massa"** (`static/js/trials.js:37`).

Ou seja: 60 amostras definem 59 intervalos entre elas, como numa cerca de 60 postes com 59 vãos.

**Essa duração está correta?** Para a referência gravimétrica, **sim**.
- A massa só é conhecida nos instantes amostrados.
- A água que entrou na balança entre t0 e t1 é exatamente m1 − m0. Então a vazão gravimétrica deve dividir Δm por (t1 − t0) = 59 s.
- O código também conta as basculadas no mesmo intervalo (t0, t1] (`trials.py:126-127`), de forma coerente.
- O que fica de fora é o primeiro segundo da janela, antes de t0. Isso vale para a massa **e** para as basculadas.

**O que é preciso entender:**
- O **erro percentual de volume ou precipitação não depende de Δt**. Δt aparece no numerador e no denominador e se cancela.
  Δt só afeta **vazão** (mL/min) e **intensidade** (mm/h): 102,48 mL em 59 s = 104,2 mL/min; em 60 s = 102,5 mL/min.
- **Não** se deve dividir Δm por 60 s. Isso subestimaria a vazão em 1/60 ≈ 1,7 %.
- Ainda falta verificar se as amostras realmente têm 1 s de espaçamento (sem *skipped scans*). Basta conferir
  `Leituras de massa válidas` e `rows` no resultado do ensaio, ou a coluna de horário no `raw.csv`.

Recomendação (sem urgência): deixar o rótulo explícito, por exemplo "Intervalo da referência (1ª à última leitura válida): 59 s · janela
configurada: 60 s". É só texto. **Não** mudar a duração do ensaio.

---

## 8. Reavaliação do ensaio de 21/10 (15 basculadas, 102,3 g)

Cálculos refeitos de forma independente (Python):

| Grandeza | Fórmula | Com r = 0,25 mm | Com r = 0,2 mm |
|---|---|---|---|
| P pluviômetro | N · r | 3,75 mm | 3,00 mm |
| V pluviômetro | P(mm) · A(cm²) / 10 | 75,0 mL | 60,0 mL |
| V balança | m / ρ = 102,3 / 0,9982 | 102,48 mL | 102,48 mL |
| P referência | 10 · V / A | 5,124 mm | 5,124 mm |
| **Erro (ref. gravimétrica)** | (V_pl − V_ref)/V_ref | **−26,82 %** | **−41,45 %** |
| Basculadas esperadas | V_ref / (r·A/10) | 20,5 | 25,6 |
| Intensidade equivalente | P_ref / Δt | 307 mm/h (60 s) · 313 mm/h (59 s) | idem |

Separação das referências, sem misturar:
- **Contra a balança:** −26,82 % (se r = 0,25). Pergunta: "quanto o pluviômetro difere da água pesada?"
- **Contra os 100 mL nominais:** −25,0 %. Pergunta: "quanto difere do que achamos ter despejado?" Os 100 mL só valem como referência
  se vierem de um instrumento rastreável (proveta ou bureta calibrada). Caso contrário, são uma estimativa.
- A diferença de 2,48 mL (2,5 %) entre 100 mL e 102,48 mL é ela própria uma informação. Pode ser incerteza da medida volumétrica,
  massa que não era água do ensaio, tara ou densidade. **Não se deve escolher um dos valores arbitrariamente.**

**Perguntas que decidem a interpretação:**
1. Os 102,3 g são **Δm** calculado pelo dashboard (`delta_mass_g` no resultado do ensaio) ou a leitura absoluta do visor?
2. A água foi despejada **dentro** dos 60 s e toda ela atravessou as básculas dentro da janela? Água ainda escorrendo no fim gera erro negativo.
3. Qual resolução estava em `config.json` naquele momento? O ensaio a guardou em `cfg.res_mm`, em `/api/trials/<id>`.

**Conclusão técnica:** o resultado é **compatível** com três causas não excludentes: intensidade 3× acima da faixa especificada,
resolução possivelmente errada e água retida ou janela curta. Ele **não** indica defeito do pluviômetro.

### 8.4 Teste que separa as causas (sem o software)
Despejar **lentamente** um volume conhecido por massa (por exemplo, 500 g ⇒ ≈ 501 mL), a menos de 30 mm/h:
- com A = 200 cm², 30 mm/h ≈ 60 mL/min, então cerca de 8 min.
- Contar as basculadas.
- Esperado com r = 0,25: ≈ 100 basculadas. Com r = 0,2: ≈ 125.

Esse teste decide C1 e calibra a resolução efetiva. Depois, repetir em intensidades crescentes mostra a curva de erro × intensidade.

---

## 9. Documentos e arquivos necessários, por camada

| Camada | Preciso de | Para confirmar |
|---|---|---|
| Física | foto ou esquema da bancada (caminho da água, posição da balança) | M4, arranjo |
| Física | ficha técnica do pluviômetro (modelo exato) | resolução, área, faixa de intensidade |
| Elétrica | manual da MK30K1 (seção RS-232: pinagem, formato da linha, baud, estabilidade) | C1 da balança, M5, M6 |
| Elétrica | manual do CR1000Xe (terminais C, P, RS-232) | níveis elétricos, P1 |
| CRBasic | o `.CR1X` **realmente carregado** (baixar do datalogger) + a tabela `Status` | C4, C5, *skipped scans* |
| CRBasic | Help do CRBasic Editor: `PulseCount`, `SerialOpen`, `SplitStr` para o CR1000Xe | C4, SerFmt |
| Comunicação | `servidor.log`, `cursor_cr1000x.json`, saída de `/api/diag` | R1–R7, lacuna 15685 |
| Software | seu `config.json` (sem senha), `dados_cr1000x.db` (ou só o ensaio de 21/10) | resolução usada, Δm, t0, t1 |
| Metrologia | procedimento do laboratório e certificado da balança | incerteza, critério de aceitação |

---

## 10. Matriz de dependências (o que precisa mudar quando…)

Legenda: ● muda sempre · ○ pode mudar · em branco = não muda.

| Mudança | CRBasic | Tabela no datalogger | Perfil JSON | `datalogger.py` | SQLite | `app.py` (API) | `calc.py`/`trials.py` | Frontend | Testes/fakes |
|---|---|---|---|---|---|---|---|---|---|
| Nome de variável muda | ● | ● | ● | | | | | | ● |
| Nome de tabela muda | ● | ● | ● | | | | | | ● |
| Sensor substituído (mesmo sinal) | ○ (escala) | | | | | | ○ | | |
| Novo canal / nova grandeza | ● | ● | ● | ● (`Reading`, `_reading`) | ● (coluna + migração) | ● (`COLS`, endpoints, export) | ○ | ● | ● |
| Unidade muda na origem | ● | | ○ (`factor`) | | | ○ (rótulos de export) | ○ | ● (rótulos) | ● |
| Cálculo muda | | | | | | ○ | ● | ○ | ● |
| Endpoint muda | | | | | | ● | | ● (`api.js`, `app.js`) | ● (e2e) |
| Exibir uma variável já existente | | | | | | ○ | | ● | |
| Resolução, área, densidade, K | | | | | | (config) | | | |

Regras práticas:
- **Só renomear** no CRBasic → atualize o **perfil JSON** e pronto. O Python lê os nomes do perfil.
- **Grandeza nova** → percorre a cadeia toda. Nunca comece pelo frontend.
- **Parâmetro numérico** (resolução, área, ρ, K, 4–20 mA) → é configuração da tela. Ensaios já encerrados **não** mudam.
- **Não alterar o CRBasic** quando o problema é de interpretação no servidor, e vice-versa.

---

## 11. Ordem segura de investigação

| Etapa | Ação | Muda algo? | Critério para seguir |
|---|---|---|---|
| 0 | Backup do `dados_cr1000x.db`, `config.json`, `cursor_cr1000x.json` e do `.CR1X` carregado | não | cópias abertas e legíveis |
| 1 | Coletar `/api/diag`, `servidor.log`, tabela `Status` (ProgName, SkippedScan) e `/api/trials/<id>` do ensaio de 21/10 | não | sei qual programa está carregado e qual resolução o ensaio usou |
| 2 | Conferir no Help do CRBasic: `PulseCount` (PConfig), `SerialOpen` (formato 3), `SplitStr` | não | C4 resolvido |
| 3 | Teste manual do pluviômetro: 20 basculadas lentas e 20 rápidas, com o dashboard aberto | não | contagem = 40 |
| 4 | Comparar `LastLine` (tabela `Balanca1s`) com o visor da balança em 3 massas (vazio, ~100 g, ~1 kg) | não | número extraído = visor |
| 5 | Teste estático lento de §8.4 (≤ 30 mm/h, ~500 g) | não | resolução efetiva determinada (C1) |
| 6 | Decidir as credenciais (keyring × variável) e a conta somente leitura | sim (pequeno) | `/api/diag` sem erro com a nova forma |
| 7 | Correções pequenas no software: rótulo "tabela reiniciada", rótulo dos 59 s, leitura via keyring | sim | 71 testes + teste novo passando |
| 8 | Ensaios em 3 intensidades × 3 repetições | não | curva de erro × intensidade |
| 9 | Só então: densidade pela temperatura, incerteza, Vaisala e medidor de vazão | sim | procedimento aprovado |

Etapas 0–5 não alteram nada. Elas usam a **linha de base atual** para localizar a camada de cada problema antes de qualquer modificação.

---

## 12. O que preciso de você agora (objetivo)

1. Seu `config.json` real (pode apagar o campo `user` se quiser; a senha não fica nele).
2. A resposta de `http://127.0.0.1:5000/api/trials` e de `/api/trials/<id do ensaio de 21/10>` (JSON).
3. O `.CR1X` baixado do datalogger, ou o `ProgName` da tabela `Status`.
4. Manual da MK30K1 (parte RS-232) e ficha técnica do pluviômetro.
5. Uma descrição de 3 linhas do caminho da água na bancada: de onde sai, por onde passa, onde cai na balança.
