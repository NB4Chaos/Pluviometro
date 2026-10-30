# Projeto Linha de Ar — CFW500 via Modbus RTU

Aplicação local Flask para ler telemetria do WEG CFW500 e enviar **somente o setpoint interno do PID (P0525)** via Modbus RTU.

## Configuração inicial do projeto

- Porta serial padrão: `COM28` (altere na interface se necessário)
- ID Modbus: `1`
- Serial: `19200`, `8E1` (paridade Even)
- Escala de processo configurada na interface: `4 mA = 0 m³/h`, `20 mA = 400 m³/h`
- Parâmetros verificados antes da escrita: `P0203=1`, `P0222=0`, `P0528=4000`, `P0529=1`
- Parâmetro escrito: `P0525`, com escala interna `0,0–100,0%`, representada no registrador como `0–1000` (décimos de porcentagem).

## Instalação no Windows

1. Extraia o ZIP para uma pasta local.
2. Instale Python 3.11 ou 3.12 (recomendado para compatibilidade com dependências atuais).
3. Abra PowerShell nessa pasta.
4. Execute:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

5. Abra `http://127.0.0.1:5050`.
6. Feche o WEG Programming Suite antes de conectar, pois a porta COM normalmente não pode ser usada simultaneamente por dois programas.

## Como enviar o setpoint

1. Confirme no inversor que a escala de AI1 realmente corresponde a 0–400 m³/h.
2. Conecte usando COM28 (ou a porta correta), endereço 1, 19200, paridade par.
3. Verifique os parâmetros exibidos. O servidor recusa a escrita se `P0203`, `P0222`, `P0528` ou `P0529` estiverem diferentes dos valores esperados.
4. Digite a vazão desejada, clique em **Enviar setpoint ao inversor** e confirme a caixa de diálogo.
5. O software escreve apenas `P0525` e lê o parâmetro novamente para confirmar a escrita.

Exemplo com a escala 0–400 m³/h:

- 100 m³/h → 25,0% → `P0525` bruto 250
- 200 m³/h → 50,0% → `P0525` bruto 500
- 400 m³/h → 100,0% → `P0525` bruto 1000

## Limites e segurança

- Esta versão **não envia comandos de partida, parada, habilitação geral, reset de falha nem palavra de controle**. Enviar setpoint não deve iniciar o motor.
- O software não substitui parada de emergência física, intertravamentos ou proteções da máquina.
- A escrita só está liberada se o inversor responder às leituras e os quatro parâmetros de validação coincidirem. Isso não comprova, por si só, a segurança mecânica nem a calibração da escala.
- A faixa 0–400 m³/h é uma configuração informada para este projeto. Confirme no manual/placa do medidor que 4 mA equivale a 0 m³/h e 20 mA a 400 m³/h. Se não corresponder, altere os dois campos na interface.
- A aplicação escuta somente em `127.0.0.1`, não a exponha diretamente à rede.
- Faça o primeiro teste com o motor parado e em condição segura. Confirme P0525 pela leitura de retorno antes de qualquer teste operacional.

## Estrutura

- `app.py`: Flask, comunicação serial Modbus, telemetria, validações e escrita de P0525.
- `templates/index.html`: interface web.
- `requirements.txt`: dependências Python.

## Comandos operacionais (partida/parada normal)

Esta versão adiciona comandos Modbus para o CFW500:

- Setpoint PID: `P0525` (escala interna em décimos de porcentagem, validada por leitura de retorno).
- Partida remota: `P0682 = 0x0017` (Gira/Para + Habilita Geral + sentido direto + remoto).
- Parada normal: `P0682 = 0x0016` (bit Gira/Para desligado; solicita parada pela rampa).

A partida exige confirmação na interface e valida conexão, estado sem falha/configuração, modo remoto, PID automático, parâmetros `P0203/P0222/P0227/P0316/P0528/P0529`, setpoint `P0525` e monitor `P0041`. Se os valores não forem coerentes, o servidor bloqueia a partida. A parada normal também exige comunicação Modbus ativa e não substitui a emergência física.

**Teste inicial:** mantenha a emergência física acessível, confirme que o sentido direto é seguro, que a área está livre, e que os limites de frequência, rampas, dados de placa do motor e intertravamentos foram verificados. O software não altera parâmetros de proteção nem executa reset de falhas. Nunca use a parada normal por software como substituta da parada de emergência.
