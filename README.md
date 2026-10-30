# Monitor de calibração de pluviômetros · Elus Instrumentação

Dashboard web (Flask + Socket.IO + SQLite) que mostra **somente dados lidos do CR1000Xe**: massa (balança MK30K1), temperatura da água (termopar tipo T),
basculadas do pluviômetro e, no programa novo, o medidor de vazão (pulsos em P2 ou analógico em 2H/2L). Faz **ensaios de calibração** com resultado congelado.
Não existe modo demonstração: sem comunicação aparece “Sem dados”, “Aguardando dados novos” ou “Datalogger sem resposta”, e a leitura antiga deixa de ser exibida como atual.

```
CR1000Xe ──(HTTP/HTTPS, conta somente leitura)── app.py ──(Socket.IO + REST)── navegador
 tabelas                consulta sequencial 1 s     SQLite
```

Documentação: `docs/DIAGNOSTICO.md` (problemas, alterações, desempenho), `docs/CALCULOS_E_ENSAIOS.md` (fórmulas, ensaios, interface),
`docs/CRBASIC_VAZAO.md` (programa novo, ligações), `docs/DEBUG.md` (onde mexer), `docs/TESTES.md` (o que foi e o que não foi testado),
`docs/MAPA_VARIAVEIS.md`, `docs/CHECKLIST.md` (validação no equipamento), `docs/PESQUISA.md` (arquitetura e fontes).

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

Programas do datalogger: `crbasic/Pluviometria.CR1X` (o seu, perfil `programa_atual`) e `crbasic/Pluviometria_Vazao.CR1X` (com o medidor de vazão, perfil
`programa_vazao`). **Não compilei nenhum dos dois no CRBasic Editor.**

Configure em *Configurações*: resolução do pluviômetro, área de captação (cm²), densidade da água e, se houver medidor de vazão, fator K (pulsos/L)
ou faixa 4–20 mA. A **duração do ensaio** fica no card da balança (fixada no início de cada ensaio). Nenhum valor físico é presumido: o que depende
de um parâmetro vazio fica indisponível.

Tela: **Exibir** (Precipitação | Vazão) só muda a apresentação dos resultados; **Método** (Gravimétrico | Comparativo) escolhe o ensaio
(pluviômetro × balança ou medidor de vazão × balança) e mostra o Medidor de Vazão só no Comparativo. Nenhum dos dois altera a aquisição.

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
| `/api/config` | GET / POST* | configuração (o GET não traz o endereço) |
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
