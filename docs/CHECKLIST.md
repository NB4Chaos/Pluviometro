# Checklist de validação (ponta a ponta)

Marque só depois de comparar com o datalogger (LoggerNet, Device Configuration Utility ou tabela *Public*).

- [ ] `ping <IP do datalogger>` responde e `http://<IP>/` abre a página web do CR1000Xe
- [ ] `python tools/probe_cr1000x.py --host <IP> --user <conta>` lista `Balanca1s`, `Termopar1s` e `Pluviometro1s`
- [ ] Topo da tela: **Recebendo dados do CR1000Xe** (verde); "Atualizado em" avança a cada segundo
- [ ] Massa na tela = `Peso_g` no datalogger, e a linha da MK30K1 em `LastLine` bate com o peso
- [ ] Balança vazia: aparece 0, não "—"
- [ ] Temperatura = `TempAgua_C` (termopar em água morna sobe na tela)
- [ ] Cada basculada manual (fechar P1–G) aparece nos eventos com o horário certo; total = contagem do datalogger
- [ ] Horário das leituras = relógio do datalogger (PC e datalogger na mesma hora e fuso)
- [ ] Medidor de vazão com o v3: Analógico ativo e confirmado; escolher Pulsos é recusado ("canal indisponível no programa") e nenhum número aparece
- [ ] Gráficos atualizam e não têm trechos preenchidos quando a balança estava desligada
- [ ] Desligar a balança: massa vira "Leitura inválida" ou "Sem comunicação"; temperatura e basculadas continuam
- [ ] Desconectar a rede do datalogger por 1 min: a tela mostra **Datalogger sem resposta**, valores viram "—" com a última leitura; ao reconectar, os segundos perdidos são recuperados sem buracos nem duplicatas (se < 5,5 h)
- [ ] Reiniciar o servidor Python: não duplica amostras nem basculadas
- [ ] Recarregar o programa no datalogger (`Pluvio_Total` volta a 0): o total da tela não é apagado

## Novos (ensaios, períodos, medidor de vazão, médias)

- [ ] Sem `DATALOGGER_HOST` o servidor informa “Endereço do datalogger não configurado” e **não** mostra números
- [ ] Salvar Configurações não muda o endereço (confirme `config.json` e o log de inicialização)
- [ ] Período de 1 min disponível; acumulado e intensidade média mudam com o período; “parcial” aparece se houver lacuna
- [ ] Gráficos: resultado do período em destaque (massa coletada / precipitação acumulada / média), média do período em texto menor e linha tracejada discreta
- [ ] Configurações → Exibição → "Vazão e volume": pluviômetro em volume equivalente (mL) e vazão equivalente; balança continua em g; nada muda na aquisição
- [ ] Método → Comparativo: o card principal (azul) passa a ser o Medidor de vazão, com a balança ao lado como referência; Gravimétrico: o card principal volta a ser a balança, com o pluviômetro ao lado. Sem recarregar a página; o período e a configuração não mudam
- [ ] Card principal: Iniciar → acompanha no mesmo card (decorrido, restante, valores "parcial") → depois mostra o resultado congelado; o seletor de método fica travado durante o ensaio
- [ ] Duração: digitar 500 ms é recusado com "mínimo 1000 ms (resolução efetiva)"; 1500 ms é aceito com aviso de quantização; trocar só a unidade converte o número sem mudar a duração
- [ ] Medidor por pulsos (v4 carregado): "Pulsos no último Scan" = `Flow_Pulsos` no *Numeric Monitor*; "Contador do datalogger" = `Flow_PulsosTot`; no ensaio, N = Δ contador; com K informado, vazão = N ÷ K ÷ Δt confere com um padrão; sem K, "não configurado" (nunca um número)
- [ ] Detalhes do ensaio / relatório: bloco Temporização com 1ª e última amostra, configurado × efetivo, diferença e resolução (Scan)
- [ ] Medidor analógico (RG1): `Flow_mA` no *Numeric Monitor* = Corrente no card; medidor parado ≈ 4,011 mA → vazão 0 válida (tolerância 0,02 mA); < 3,6 mA → "Falha do sinal"
- [ ] Ensaio (1 s a 6 h): inicia, mostra tempo restante e valores “parcial”, encerra sozinho, vira “congelado”; reabrir no Histórico dá o mesmo resultado
- [ ] Ensaio gravimétrico: Δ massa, volume, precipitação e vazão de referência conferem com a conta manual (ver `CALCULOS_E_ENSAIOS.md`)
- [ ] Desligar a rede durante um ensaio curto: ao voltar, os registros são recuperados; se algum se perdeu o ensaio sai “Incompleto”
- [ ] Com `DASHBOARD_TOKEN`: salvar/zerar/iniciar ensaio sem o token é negado
- [ ] `/api/diag`: `lat_ms.p50` (hora do PC − carimbo) compatível com ~1 s; `join_miss` vazio
