# Testes: o que foi executado e o que não foi (atualizado em 30/10/2026)

## Executado (com resultado)

| Teste | Resultado | O que prova | Limite |
|---|---|---|---|
| `pytest tests` (146) | **146 passaram** | fórmulas e unidades (`test_calc`, `test_calc_flow`), adaptador v3/v4/âncora/reinício/lacuna (`test_adapter_*`), ensaios gravimétricos e por pulsos (`test_trials`, `test_trials_pulsos`), temporização (`test_trials_timing`), API do medidor/configuração parcial/instância única/CSV bruto (`test_app_api`), probe (`test_probe`) | emulador e dados sintéticos |
| `tests/e2e_ensaio.py` | 37 ok, 0 falha | servidor real + emulador v4: método pulsos solicitado = ativo, `/api/flow`, ensaio de ponta a ponta com N bruto pela diferença do contador, bloco de temporização, 500 ms recusado / 1500 ms aceito, congelamento, banco imutável, queda e recuperação sem duplicar, token, log sem segredos, CSV bruto | emulador, não o CR1000Xe |
| `tests/e2e_programa_atual.py` | 17 ok | regressão do programa atual (backlog, cursor, reinício, queda) | idem |
| `tests/e2e_cr1000x_elus_calib.py` | 16 ok | regressão do perfil `elus_calib`; recuperação após queda de 10 s; reinício do servidor; tabela reiniciada | idem; emulador alinhado à API real (`since-record` de registro inexistente responde do mais antigo) |
| Navegador (Chromium/Playwright, servidor + emulador v4 e v3) | aprovado, 0 erros de JavaScript | tipografia `Urbanist` 72 px/300 no valor principal; hero = balança no Gravimétrico e = medidor no Comparativo (sem recarregar); seletor Analógico/Pulsos (confirmado por dado do datalogger; recusado no v3 com a mensagem do canal); pulsos brutos por Scan e contador; ensaio por pulsos parcial → congelado (500 pulsos em 5 s → 6 L/min) com detalhes e temporização; relatório; histórico; 400 px sem rolagem horizontal; método travado durante o ensaio | emulador |
| `node --check` nos 5 JS | ok | sintaxe | — |
| Banco real (cópia de 28/10, só leitura) | 27 160 amostras; 25 186 sem temperatura; 144 leituras analógicas `ok` em 4,0106–4,0109 mA | confirma o diagnóstico do TI (releitura do histórico) e o funcionamento do 4–20 mA em RG1 | dados já gravados, não aquisição ao vivo |

Testes atualizados nesta revisão e por quê: `e2e_ensaio.py` (o método do medidor passou a ser escolhido no servidor — `flow_method` — e não lido de `Flow_mode`;
acrescentadas as verificações de `/api/flow`, temporização e duração em ms), `e2e_programa_atual.py` (pill de estado única `#conn`), `e2e_cr1000x_elus_calib.py`
(espera de 13 s após a queda, compatível com o recuo progressivo de até 8 s que já existia), `fake_cr1000x.py` (comportamento real da API para registro inexistente).
Nenhum teste foi removido.

Defeitos encontrados pelos testes e corrigidos: `GET /api/trials/<id>/raw.csv` respondia 500; aviso de "sem registro" indevido para tabela esparsa.

## NÃO executado (precisa do equipamento)

- **Nada foi executado contra um CR1000Xe real** nem contra o MAG 5000.
- `Pluviometria_v4_vazao_pulsos.CR1X` e a proposta v5 **não foram compilados** (sem CRBasic Editor).
- Ligação da saída de pulsos do MAG 5000 em P2 (modo, pull-up, terminais) e o fator K: [FÍSICO].
- Verificação do temporizador contra referência externa (`docs/TEMPORIZACAO_E_PULSOS.md`, seção 4).
- Latência real e carga do datalogger com tabelas de 100 ms (proposta v5).

## Como reproduzir

```bat
.venv\Scripts\activate
python -m pytest tests
python tests\e2e_ensaio.py
python tests\e2e_programa_atual.py
python tests\e2e_cr1000x_elus_calib.py
```
(um `e2e` de cada vez). Os testes usam pastas temporárias e não tocam nos dados do laboratório.
