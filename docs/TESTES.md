# Testes: o que foi executado e o que não foi

## Executado (com resultado)

| Teste | Resultado | O que prova | Limite |
|---|---|---|---|
| `pytest tests` (71) | 71 passaram | fórmulas e unidades (`test_calc`, 26), ensaios (`test_trials`, 18), adaptador com `Vazao1s` e casamento de horários (`test_adapter_vazao`), adaptadores anteriores | dados de exemplo/emulador |
| `tests/e2e_ensaio.py` | 26 ok, 0 falha | servidor real + emulador: ensaio completo, congelamento 6 s depois, banco recusando alteração, 409 em ensaio simultâneo, interrupção, queda e recuperação sem duplicar, endereço preservado, token, log sem segredos | emulador, não o CR1000Xe |
| `tests/e2e_programa_atual.py` | 17 ok, 0 falha | regressão do programa atual (backlog, cursor, reinício, queda) | idem |
| `tests/e2e_cr1000x_elus_calib.py` | 16 ok, 0 falha | regressão do perfil `elus_calib` | idem |
| Teste de mutação (manual) | 3 mutações estragando `trials.py` derrubaram 1, 1 e 6 testes | a suíte detecta erros de janela, imutabilidade e fim do ensaio | — |
| **Dados reais** (cópia do `dados_cr1000x.db` enviado) | migração do banco ok; 20/10 15:00–15:20: 57 basculadas = 11,4 mm, 34,2 mm/h, cobertura completa; 10:15–11:15: “parcial” (3.113 de 3.600 s, 4 lacunas); 02:00–03:00: indisponível; 23 h de histórico em < 0,1 s | cálculo de período, cobertura e desempenho sobre registros de verdade | é cálculo sobre dados já gravados, não aquisição ao vivo |
| Navegador (Chrome, servidor + emulador) | página e gráficos renderizam, sem erro de JavaScript; ensaio iniciado pela tela, parcial → concluído/congelado; legenda e valor da média nos gráficos | a interface funciona de ponta a ponta | emulador |
| Análise estática | `node --check` em todos os `.js`, `ast.parse` em `app.py`, revisão manual de concorrência (um lock global do SQLite, aquisição sequencial) e de injeção/XSS | sem erros de sintaxe | não usei analisador estático dedicado |

O que apareceu nos testes e foi corrigido: `flow_integrated` falso com o perfil novo; a marca d'água ignorava a tolerância de horário; a latência medida era contaminada pelo backlog recuperado.

## NÃO executado (precisa do seu equipamento)

- **CRBasic:** `Pluviometria_Vazao.CR1X` **não foi compilado** (sem o CRBasic Editor). Sintaxe baseada na documentação oficial (`PulseCount`, `VoltDiff`, `If x = NAN`), mas só o compilador confirma.
- Aquisição por pulsos em P2 (frequência real, nível do sinal, ausência de perdas) e analógica em 2H/2L (shunt, faixa, ligação).
- Medida da latência real (aquisição → tela) e da carga do datalogger: o emulador não representa a rede nem o tempo de resposta do CR1000Xe. Use `/api/diag`.
- Comunicação real por HTTPS e com `DASHBOARD_TOKEN` por trás de outro equipamento de rede.
- Ensaios com água e balança de verdade: formulas verificadas matematicamente, **sem validação experimental**. A resolução (0,2 mm?), a área de captação, a densidade e o K ainda precisam ser os do seu sistema.
- Formato real da linha da MK30K1 (`SplitStr` ainda marcado “experimental” no programa).
- Origem exata do “termopar sem comunicação” em 95 % dos seus registros antigos (ver `DIAGNOSTICO.md`, problema 1).
- Carga com meses de histórico (testado: ~18 mil amostras).

## Como reproduzir

```bat
.venv\Scripts\activate
python -m pytest tests
python tests\e2e_ensaio.py & python tests\e2e_programa_atual.py & python tests\e2e_cr1000x_elus_calib.py
```
(rode os `e2e` um de cada vez; cada um sobe um servidor e o emulador). Os testes usam pasta temporária e não tocam nos seus dados.
