# Checklist de validação (ponta a ponta)

Marque só depois de comparar com o datalogger (LoggerNet, Device Configuration Utility ou tabela *Public*).

- [ ] `ping <IP do datalogger>` responde e `http://<IP>/` abre a página web do CR1000Xe
- [ ] `python tools/probe_cr1000x.py --host <IP> --user <conta>` lista `Balanca1s`, `Termopar1s` e `Pluviometro1s`
- [ ] Topo da tela: **Dados reais do datalogger** (verde) e **Recebendo dados**
- [ ] Massa na tela = `Peso_g` no datalogger, e a linha da MK30K1 em `LastLine` bate com o peso
- [ ] Balança vazia: aparece 0, não "—"
- [ ] Temperatura = `TempAgua_C` (termopar em água morna sobe na tela)
- [ ] Cada basculada manual (fechar P1–G) aparece nos eventos com o horário certo; total = contagem do datalogger
- [ ] Horário das leituras = relógio do datalogger (PC e datalogger na mesma hora e fuso)
- [ ] Medidor de Vazão: "Aguardando integração" e nenhum número
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
- [ ] Exibir → Vazão: pluviômetro em volume equivalente (mL) e vazão equivalente; balança continua em g; nada muda na aquisição
- [ ] Método → Comparativo: aparece o Medidor de Vazão; Gravimétrico: some sem deixar espaço
- [ ] Card da balança: Iniciar → acompanha no mesmo card (decorrido, restante, média parcial) → depois mostra a média de massa do ensaio
- [ ] Medidor por pulsos: com K informado, vazão = Hz ÷ K × 60 confere com um padrão; sem K, “não configurado” (nunca um número)
- [ ] Medidor analógico (só após confirmar shunt e ligação): mA no *Numeric Monitor* = mA na tela
- [ ] Ensaio (10 s a 6 h): inicia, mostra tempo restante e valores “parcial”, encerra sozinho, vira “congelado”; reabrir no Histórico dá o mesmo resultado
- [ ] Ensaio gravimétrico: Δ massa, volume, precipitação e vazão de referência conferem com a conta manual (ver `CALCULOS_E_ENSAIOS.md`)
- [ ] Desligar a rede durante um ensaio curto: ao voltar, os registros são recuperados; se algum se perdeu o ensaio sai “Incompleto”
- [ ] Com `DASHBOARD_TOKEN`: salvar/zerar/iniciar ensaio sem o token é negado
- [ ] `/api/diag`: `lat_ms.p50` (hora do PC − carimbo) compatível com ~1 s; `join_miss` vazio
