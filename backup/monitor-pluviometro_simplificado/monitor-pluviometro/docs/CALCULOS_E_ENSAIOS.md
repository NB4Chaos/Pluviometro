# Cálculos, ensaios e interface

Todos os tempos são **horário do datalogger** (carimbo de cada amostra). Intervalos são semiabertos `[início, fim)`.
Indisponível = “—”. Ausência de dado nunca vira zero; massa 0 g, 0 °C, 0 basculadas e 0 pulsos são medições válidas.

## Precipitação, intensidade e média

| Indicador | Janela | Fórmula | Observações |
|---|---|---|---|
| Precipitação acumulada no período | o **Período** selecionado (1 min … 24 h, personalizado) | `P = N × r` (N = basculadas em `[ini,fim)`, r = resolução da tela, mm) | “parcial” se a cobertura de dados for incompleta |
| Intensidade média no período | idem | `I = N_cobertas × r ÷ t_coberto(h)`; mm/h | `t_coberto` = tempo realmente coberto por amostras (cada amostra cobre até a próxima se a distância ≤ 2,5 s). Descoberto > max(3 s, 2 % da janela) ⇒ “parcial”. Sem amostras ⇒ indisponível |
| Total desde “Zerar contagem” | do zeramento até agora | contagem de eventos | indicador separado; não entra no acumulado do período |
| Média do período | o período selecionado | média aritmética dos valores válidos | rótulo “Média do período (15 min)” |
| Vazão pela balança (derivada da massa) | o período selecionado | `Δm = m(última válida) − m(primeira válida)`; `V = Δm ÷ ρ`; `Q = V ÷ (t_última − t_primeira)` — a mesma regra dos ensaios (`calc.gravimetric`) | a balança mede massa; a vazão é calculada. Massa diminuiu no período ⇒ indisponível, com o motivo |
| Média de massa do ensaio | a janela do ensaio `[início, fim)` | média aritmética das leituras **válidas** de massa (não é média móvel) | valor em destaque no card da balança depois do ensaio |

Exemplos verificados nos testes: 0,5 mm em 15 min = 2 mm/h; os mesmos 0,5 mm em 1 h = 0,5 mm/h.
A resolução 0,2 mm ainda **não é comprovada** (veio do CRBasic: “confirmar a resolução real do sensor”). Configure o valor do sensor.

## Gravimetria (balança que coleta água)

Usa **variação** de massa dentro da janela do ensaio, nunca a massa total:
`Δm = m_fim − m_início` (primeira e última leituras válidas da janela, em `t0` e `t1`), `Δt = t1 − t0`.

| Grandeza | Fórmula | Unidade |
|---|---|---|
| Volume | `V = Δm ÷ ρ` (g ÷ g/cm³ = cm³ = mL) | mL; `V(L) = V(mL) ÷ 1000` |
| Precipitação de referência | `P = 10 × V(cm³) ÷ A(cm²)` | mm |
| Intensidade de referência | `I = P ÷ Δt(h)` | mm/h |
| Vazão gravimétrica | `Q = V(L) ÷ Δt(min)` | L/min |
| Precipitação do pluviômetro | `N × r`, com N = basculadas em `(t0, t1]` | mm |
| Diferença e erro | `P_pluv − P_ref`; `100 × (P_pluv − P_ref) ÷ P_ref` (só se `P_ref > 0`) | mm; % |

- Por que `(t0, t1]` nas basculadas: o registro em *t* traz as basculadas de `(t−1 s, t]`, enquanto a massa é instantânea em *t*.
- Δm < 0 (balança esvaziada/tarada) ⇒ referência indisponível, com aviso. Sem ρ ou sem área ⇒ o que depende deles fica indisponível, com aviso.
- ρ vem da configuração (`density_g_cm3`). O termopar mede “TempAgua_C”, mas não sei onde fica em relação à água coletada, então a densidade
  **não** é deduzida da temperatura; a temperatura média do ensaio fica registrada no resultado.
- Atraso e retenção: a água que ainda não chegou à balança, ou ficou no funil/báscula, entra na diferença; pulsos são discretos (±1 basculada = ±r mm),
  então em ensaios curtos essa quantização domina. Nenhum pulso “esperado” é inventado.
- A **área de captação** (cm², abertura superior do coletor) fica em *Configurações → Densidade e área de captação*; a resolução, em *Pluviômetro de báscula*.

## Medidor de Vazão

| Modo (`Flow_Mode`) | Dado bruto | Vazão |
|---|---|---|
| 1 pulsos (P2) | `Flow_Pulsos_1s`, `Flow_Freq_Hz` | `Q(L/min) = f(Hz) ÷ K × 60`; volume = pulsos ÷ K. **K** (pulsos/L) em Configurações; sem K ⇒ indisponível |
| 2 analógico (2H/2L) | `Flow_mV`, `Flow_mA` (= mV ÷ shunt) | faixa linear 4–20 mA (Configurações); fora de 4–20 mA ⇒ “fora da faixa”, não entra na média |

## Ensaios

- **Iniciar**: botão no card do Medidor de Vazão (ensaio de vazão) ou do Pluviômetro (ensaio gravimétrico). Só inicia com dados novos chegando; o início
  é a *próxima* amostra do datalogger. Um ensaio por vez (o servidor recusa o segundo com 409 e o botão reflete o estado do servidor).
- **Duração**: *Configurações → Tempos → Duração do ensaio* (10 s a 6 h), fixada no início de cada ensaio.
- **Acompanhar**: tempo restante (pelo relógio do datalogger), nº de amostras e valores **parciais** (etiqueta “parcial”).
- **Encerrar**: sozinho quando chega uma amostra com horário ≥ fim, ou pelo botão (“interrompido”).
- **Estados**: *Concluído* (cobertura completa e ≥ 95 % de leituras válidas do sinal exigido), *Incompleto* (chegou ao fim com lacunas ou leituras inválidas),
  *Interrompido* (parado pelo usuário ou sem dados 120 s após o fim previsto).
- **Congelamento**: ao terminar, as amostras e basculadas da janela são **copiadas** para tabelas do ensaio e o resultado é calculado só com elas. O banco
  tem gatilhos que recusam UPDATE/DELETE de ensaio encerrado e de seus dados. Mudar configuração, chegar leitura nova ou a janela de 15 min avançar não altera nada.
  A configuração usada (ρ, área, resolução, K, faixa) fica guardada junto.
- **Consultar**: o último ensaio aparece no próprio card; *Histórico → Ensaios de calibração* lista todos e mostra o detalhe; CSV das amostras e das basculadas.
- Queda de comunicação durante o ensaio **não** o interrompe: o datalogger guarda os registros e o servidor os recupera pelo horário original; se algum se
  perdeu, o ensaio sai *Incompleto*. Reinício do servidor também não interrompe (o ensaio continua e termina com os dados recuperados).

## Interface

- **Indicador em destaque** (card da balança, seletor “Em destaque”): Massa, Vazão (instantânea pela balança), Vazão média, máxima ou mínima (do período).
  Os outros quatro ficam como botões pequenos abaixo (clique para trocar). A escolha fica salva no navegador. Cada um traz nome, janela e unidade.
- **Período**: 1 min, 15 min, 1 h, 6 h, 24 h ou personalizado; controla acumulado, intensidade média, média do período, estatísticas e gráficos.
- Cada valor tem etiqueta: *parcial* (período/ensaio incompleto), *congelado* (ensaio encerrado), *ref.* (referência pela balança); sem etiqueta = medido.
