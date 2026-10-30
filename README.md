# Monitor de calibração de pluviômetros · Elus Instrumentação

Dashboard web (Flask + Socket.IO + SQLite) que mostra **somente dados lidos do CR1000Xe**: massa (balança MK30K1), temperatura da água (termopar tipo T),
basculadas do pluviômetro e o medidor de vazão SITRANS FM MAG 5000 (4–20 mA em RG1 no programa em uso; pulsos em P2 no programa v4). Faz **ensaios de calibração**
com resultado congelado, contagem bruta de pulsos e registro de temporização.
Não existe modo demonstração: sem comunicação aparece “Sem dados”, “Aguardando dados novos” ou “Datalogger sem resposta”, e a leitura antiga deixa de ser exibida como atual.

```
CR1000Xe ──(HTTP/HTTPS, conta somente leitura)── app.py ──(Socket.IO + REST)── navegador
 tabelas                consulta sequencial 1 s     SQLite
```

Documentação (mais recente primeiro): `docs/ENTREGA_2026-10-30.md` (entrega desta revisão, tabela de referência, pendências), `docs/DIAGNOSTICO_2026-10-30.md`,
`docs/PLANO_2026-10-30.md`, `docs/TEMPORIZACAO_E_PULSOS.md` (resolução temporal real, pulsos brutos, ligação do MAG 5000), `docs/CRBASIC_V4_PULSOS.md`
(programa v4: carregar e reverter), `docs/MAPA_VARIAVEIS.md`, `docs/Elus_Monitor_Relatorio_Tecnico_Rev1_2026-10-28.pdf` (relatório do TI),
`docs/CALCULOS_E_ENSAIOS.md`, `docs/TESTES.md`, `docs/DEBUG.md`, `docs/CHECKLIST.md`, `docs/PESQUISA.md`; anteriores: `docs/DIAGNOSTICO_2026-10-29.md`,
`docs/PLANO_2026-10-29.md`, `docs/CRBASIC_VAZAO.md` (programa 2H/2L, não é o em uso).

## Instalação e execução (Windows)

```bat
cd C:\caminho\para\monitor-pluviometro
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Credenciais: o `app.py` lê usuário e senha do Gerenciador de Credenciais do Windows (pacote `keyring`, serviço `Elus-CR1000Xe`,
chaves `DATALOGGER_USER` e `DATALOGGER_PASSWORD`) e usa por padrão o host `169.254.244.82`, HTTP e o perfil `programa_atual`.
Se `DATALOGGER_PASSWORD` já estiver definida no ambiente (testes automáticos), o keyring não é consultado.

Abra `http://127.0.0.1:5000`. Antes, rode o diagnóstico (só lê): `python tools\probe_cr1000x.py --host <IP> --user dashboard`.

| Variável | Para quê |
|---|---|
| `DATALOGGER_HOST`, `DATALOGGER_USER`, `DATALOGGER_PROTOCOL`, `CR1000X_PROFILE` | conexão e perfil das tabelas (têm prioridade sobre o `config.json`). O endereço **não** é editado na interface |
| `DATALOGGER_PASSWORD` | senha (nunca em arquivo, tela ou log). Normalmente vem do keyring; definida no ambiente, o keyring não é consultado |
| `DASHBOARD_TOKEN` | se definido, exige o cabeçalho `X-Dashboard-Token` em toda **escrita** (configurações, zerar contagem, iniciar/encerrar ensaio); a tela pede o token uma vez por aba |
| `HOST`, `PORT` | `HOST=0.0.0.0` expõe na rede: use com `DASHBOARD_TOKEN` (o servidor avisa se não houver) |
| `SAMPLE_PERIOD` | segundos entre consultas (padrão 1) |
| `ELUS_DATA_DIR` | pasta do banco, cursor, `config.json` e `logs/` (padrão: a pasta do projeto) |
| `LOG_LEVEL` | `INFO` (padrão) ou `DEBUG` (uma linha por amostra) |
| `DATALOGGER_CA`, `DATALOGGER_TLS_VERIFY` | HTTPS: certificado próprio / (só para teste) desligar verificação |

Programas do datalogger: `crbasic/Pluviometria_v3_com_vazao_4-20mA.CR1X` (**em uso**, perfil `programa_vazao`), `crbasic/Pluviometria_v4_vazao_pulsos.CR1X`
(mesmo programa + pulsos em P2, mesmo perfil; **não compilado**) e `crbasic/propostas/Pluviometria_v5_scan100ms_PROPOSTA.CR1X` (proposta para resolução de
100 ms; não compilada, não carregar sem teste). Os anteriores (`Pluviometria.CR1X`, `_v2`, `_v3`, `_Vazao`) ficam para referência.

Configure em *Configurações*: resolução do pluviômetro, área de captação (cm²), densidade da água, fator K **com unidade** (pulsos/L, pulsos/m³, L/pulso, mL/pulso),
faixa 4–20 mA e tolerância nos limites. Nenhum valor físico é presumido: o que depende de um parâmetro vazio fica indisponível.

Tela: **Método** (Gravimétrico | Comparativo) escolhe o ensaio e o **card principal**: no Gravimétrico é a balança (pluviômetro ao lado); no Comparativo é o
Medidor de vazão (balança ao lado, como referência). No card do medidor fica o seletor **Analógico 4–20 mA | Pulsos** (o método *solicitado* só vira *ativo*
quando uma amostra do datalogger é calculada com ele; a troca é recusada durante um ensaio e quando o programa carregado não tem o canal). A **duração do
ensaio** (ms, s ou min; mínimo = Scan do datalogger) e o botão de iniciar ficam no card principal. A forma de exibir os resultados do pluviômetro
(precipitação ou vazão/volume) fica em *Configurações → Exibição*. Nada disso altera a aquisição: o CR1000Xe mede os dois canais sempre.

## Como os dados entram

- Consulta por **número de registro** com cursor em disco (`cursor_cr1000x.json`): se a rede ou o servidor cair, o datalogger continua gravando e o servidor
  recupera tudo com o horário original, sem duplicar. Tabelas circulares: 20.000 registros a 1 Hz ≈ 5,5 h (depois disso aparece “Lacuna”).
- As tabelas são casadas por horário (tolerância de 0,5 s) e lidas só até o instante em que todas chegaram.
- Cada basculada vira um evento com chave única. `NAN`/estado inválido nunca vira 0.
- Em falha de comunicação o servidor recua (1, 2, 4… até 10 s entre tentativas) e não grava nada inventado.

## API

| Endpoint | Método | Função |
|---|---|---|
| `/api/summary?from&to` | GET | última leitura, período (acumulado, intensidade, cobertura), estatísticas, referência gravimétrica do período (`grav`: Δm, volume, vazão), `link` |
| `/api/series?from&to` | GET | séries medidas (até ~600 pontos) e estatísticas do período para os gráficos |
| `/api/history`, `/api/tips` | GET | tabela paginada; eventos de basculamento |
| `/api/trials`, `/api/trials/<id>` | GET | ensaio em andamento (parcial), último encerrado e histórico; detalhe |
| `/api/trials/start`, `/api/trials/stop` | POST* | inicia (`{"kind":"flow"\|"pluv"}`) / encerra o ensaio |
| `/api/trials/<id>/raw.csv`, `/tips.csv` | GET | dados brutos do ensaio |
| `/api/config` | GET / POST* | configuração parcial (campo ausente preserva; o GET não traz o endereço) |
| `/api/flow`, `/api/flow/method` | GET / POST* | estado do medidor (solicitado × ativo, canais, dado bruto); troca do método (409 em ensaio; 400 sem o canal no programa) |
| `/api/reset-count` | POST* | zera a contagem exibida (histórico e ensaios mantidos) |
| `/api/diag` | GET | latência, consultas, erros, lacunas, correspondência de tabelas |
| `/export.csv`, `/export.xlsx`, `/export-eventos.csv` | GET | exportações |
| Socket.IO `sample`, `trial` | eventos | nova leitura; estado do ensaio |

\* exige `Content-Type: application/json` e, se definido, `X-Dashboard-Token`.

## Estrutura

| Arquivo | Papel |
|---|---|
| `datalogger.py` | comunicação com o CR1000Xe (DataQuery), cursor, casamento de tabelas |
| `calc.py` | cálculos puros (períodos, cobertura, precipitação, médias, gravimetria, vazão) |
| `trials.py` | ensaios: janela, snapshot imutável, estados |
| `app.py` | aquisição, estado da conexão, banco, API, Socket.IO, exportação, segurança, logs |
| `templates/`, `static/` | interface (Chart.js e Socket.IO locais: funciona sem internet) |
| `profiles/*.json` | quais tabelas/campos do CRBasic alimentam cada grandeza |

## Testes

```bat
pip install pytest
python -m pytest tests
python tests\e2e_ensaio.py
python tests\e2e_programa_atual.py
python tests\e2e_cr1000x_elus_calib.py
```

Usam emuladores com dados fictícios e pasta de dados temporária (não tocam nos seus dados). **Nenhum teste foi feito contra um CR1000Xe real.**
