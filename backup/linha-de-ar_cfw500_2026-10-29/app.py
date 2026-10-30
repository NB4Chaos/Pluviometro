from flask import Flask, render_template, request, jsonify
from pymodbus.client import ModbusSerialClient
import threading
import time
from datetime import datetime

app = Flask(__name__)

# Configuração inicial baseada nos parâmetros lidos no CFW500.
DEFAULT_PORT = "COM28"
DEFAULT_UNIT_ID = 1
DEFAULT_BAUDRATE = 19200
DEFAULT_PARITY = "E"  # P0311 = 1: 8E1
DEFAULT_FLOW_4MA = 0.0
DEFAULT_FLOW_20MA = 400.0
POLL_INTERVAL_SECONDS = 1.0

# Escritas habilitadas: setpoint P0525 e palavra de controle P0682.
# A partida exige confirmação explícita e valida pré-condições do inversor.
WRITE_COMMANDS_ENABLED = True
MOTOR_COMMANDS_ENABLED = True
CONTROL_RUN_FORWARD_REMOTE = 0x0017  # bit0 Gira/Para + bit1 Habilita Geral + bit2 sentido direto + bit4 Remoto
CONTROL_STOP_RAMP_REMOTE = 0x0016    # mesmos bits, bit0=0: parada pela rampa

client = None
client_lock = threading.RLock()
connection_info = {
    "connected": False,
    "port": DEFAULT_PORT,
    "unit_id": DEFAULT_UNIT_ID,
    "baudrate": DEFAULT_BAUDRATE,
    "parity": DEFAULT_PARITY,
    "last_error": None,
    "last_success": None,
}
latest_telemetry = {
    "connected": False,
    "timestamp": None,
    "data": {},
    "error": "Ainda não conectado ao inversor."
}


def parse_number(value, label):
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{label}: informe um número válido.")


def modbus_read_registers(modbus_client, address, count=1, unit_id=1):
    """Compatibilidade com variações da API pymodbus 3.x."""
    try:
        response = modbus_client.read_holding_registers(
            address=address, count=count, device_id=unit_id
        )
    except TypeError:
        try:
            response = modbus_client.read_holding_registers(
                address=address, count=count, slave=unit_id
            )
        except TypeError:
            response = modbus_client.read_holding_registers(
                address=address, count=count, unit=unit_id
            )
    if response is None or response.isError():
        raise RuntimeError(f"Sem resposta válida ao ler registrador {address} (P{address:04d}).")
    return response.registers


def read_parameter(parameter_number, unit_id=None):
    """No CFW500, o número do parâmetro equivale ao endereço holding, offset zero."""
    with client_lock:
        if client is None or not connection_info["connected"]:
            raise RuntimeError("Não conectado ao inversor.")
        selected_unit = connection_info["unit_id"] if unit_id is None else unit_id
        return modbus_read_registers(client, parameter_number, 1, selected_unit)[0]


def connect_serial(port, unit_id, baudrate, parity):
    global client
    with client_lock:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            client = None

        new_client = ModbusSerialClient(
            port=port,
            framer="rtu",
            baudrate=baudrate,
            bytesize=8,
            parity=parity,
            stopbits=1,
            timeout=1.0,
            retries=0,
        )
        if not new_client.connect():
            connection_info.update({
                "connected": False, "port": port, "unit_id": unit_id,
                "baudrate": baudrate, "parity": parity,
                "last_error": f"Não foi possível abrir {port}. Confira a porta e se outro programa está usando o conversor.",
            })
            latest_telemetry.update({
                "connected": False,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "data": {},
                "error": connection_info["last_error"],
            })
            client = None
            return False, connection_info["last_error"]

        client = new_client
        connection_info.update({
            "connected": True, "port": port, "unit_id": unit_id,
            "baudrate": baudrate, "parity": parity,
            "last_error": None, "last_success": None,
        })

        # Teste de leitura apenas: P0308 (endereço serial), sem escrever nada.
        try:
            echoed_address = read_parameter(308, unit_id)
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            client = None
            connection_info["connected"] = False
            connection_info["last_error"] = (
                "A porta abriu, mas não houve leitura Modbus válida de P0308. "
                f"Detalhe: {exc}"
            )
            latest_telemetry.update({
                "connected": False,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "data": {},
                "error": connection_info["last_error"],
            })
            return False, connection_info["last_error"]

        return True, f"Conexão estabelecida. Leitura de teste P0308 = {echoed_address}."


def disconnect_serial():
    global client
    with client_lock:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        client = None
        connection_info["connected"] = False
        latest_telemetry.update({
            "connected": False,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "error": "Desconectado pelo operador.",
            "data": {},
        })


def refresh_telemetry():
    """Aquisição Modbus de leitura; sem qualquer comando de escrita."""
    with client_lock:
        if client is None or not connection_info["connected"]:
            latest_telemetry.update({
                "connected": False,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "error": "Não conectado.",
                "data": {},
            })
            return latest_telemetry

        unit_id = connection_info["unit_id"]
        try:
            # Endereços são números de parâmetros, com offset zero no CFW500.
            # P0003 = corrente do motor; P0006 = frequência de saída;
            # P0040/P0041 = variável de processo/setpoint do PID;
            # P0203/P0233 = configuração de realimentação/AI;
            # P0308/P0310/P0311/P0312/P0316 = comunicação;
            # P0403 = frequência nominal; P0528/P0529 = escala/formato PID;
            # P0680 = palavra de estado; P0681 = velocidade via serial.
            p0003 = read_parameter(3, unit_id)
            p0006 = read_parameter(6, unit_id)
            p0040 = read_parameter(40, unit_id)
            p0041 = read_parameter(41, unit_id)
            p0018 = read_parameter(18, unit_id)
            p0203 = read_parameter(203, unit_id)
            p0220 = read_parameter(220, unit_id)
            p0222 = read_parameter(222, unit_id)
            p0227 = read_parameter(227, unit_id)
            p0233 = read_parameter(233, unit_id)
            p0308 = read_parameter(308, unit_id)
            p0310 = read_parameter(310, unit_id)
            p0311 = read_parameter(311, unit_id)
            p0312 = read_parameter(312, unit_id)
            p0316 = read_parameter(316, unit_id)
            p0403 = read_parameter(403, unit_id)
            p0525 = read_parameter(525, unit_id)
            p0528 = read_parameter(528, unit_id)
            p0529 = read_parameter(529, unit_id)
            p0536 = read_parameter(536, unit_id)
            p0680 = read_parameter(680, unit_id)
            p0681 = read_parameter(681, unit_id)
            p0682 = read_parameter(682, unit_id)

            # CFW500: P0003 e P0006 normalmente têm uma casa decimal.
            # P0040/P0041 usam P0529; o usuário informou wxy.z (uma casa).
            data = {
                "p0003_raw": p0003,
                "motor_current_a": p0003 / 10.0,
                "p0006_raw": p0006,
                "output_frequency_hz": p0006 / 10.0,
                "p0040_raw": p0040,
                "pid_process_value": p0040 / 10.0,
                "p0041_raw": p0041,
                "pid_setpoint": p0041 / 10.0,
                "p0018_raw": p0018,
                "ai1_percent": p0018 / 10.0,
                "p0203": p0203,
                "p0220": p0220,
                "p0222": p0222,
                "p0227": p0227,
                "p0233": p0233,
                "p0308": p0308,
                "p0310": p0310,
                "p0311": p0311,
                "p0312": p0312,
                "p0316": p0316,
                "p0403_raw": p0403,
                "p0525_raw": p0525,
                "pid_internal_setpoint_percent": p0525 / 10.0,
                "p0528": p0528,
                "p0529": p0529,
                "p0536": p0536,
                "p0680": p0680,
                "p0680_hex": f"0x{p0680:04X}",
                "p0681_raw": p0681,
                "p0682_raw": p0682,
                "p0682_hex": f"0x{p0682:04X}",
                "status_fault": bool(p0680 & 0x8000),
                "status_running": bool(p0680 & 0x0100),
                "status_enabled": bool(p0680 & 0x0200),
                "status_remote": bool(p0680 & 0x1000),
                "status_pid_auto": bool(p0680 & 0x4000),
                "status_config_mode": bool(p0680 & 0x0040),
                "pid_feedback_selected": p0203 != 0,
            }
            latest_telemetry.update({
                "connected": True,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "data": data,
                "error": None,
            })
            connection_info["last_success"] = latest_telemetry["timestamp"]
            connection_info["last_error"] = None
        except Exception as exc:
            connection_info["last_error"] = str(exc)
            latest_telemetry.update({
                "connected": False,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "data": {},
                "error": f"Falha ao ler parâmetros Modbus: {exc}",
            })
    return latest_telemetry


@app.get("/")
def index():
    return render_template(
        "index.html",
        flow_4ma=DEFAULT_FLOW_4MA,
        flow_20ma=DEFAULT_FLOW_20MA,
        default_port=DEFAULT_PORT,
        default_unit_id=DEFAULT_UNIT_ID,
        default_baudrate=DEFAULT_BAUDRATE,
        write_enabled=WRITE_COMMANDS_ENABLED,
    )


@app.get("/api/status")
def api_status():
    return jsonify({
        "application": "online",
        "connection": connection_info,
        "telemetry": latest_telemetry,
        "write_commands_enabled": WRITE_COMMANDS_ENABLED,
    })


@app.post("/api/connect")
def api_connect():
    data = request.get_json(silent=True) or {}
    port = str(data.get("port", DEFAULT_PORT)).strip()
    try:
        unit_id = int(data.get("unit_id", DEFAULT_UNIT_ID))
        baudrate = int(data.get("baudrate", DEFAULT_BAUDRATE))
        parity = str(data.get("parity", DEFAULT_PARITY)).upper()
        if not port:
            raise ValueError("Informe a porta COM.")
        if not 1 <= unit_id <= 247:
            raise ValueError("O ID Modbus deve estar entre 1 e 247.")
        if baudrate not in (9600, 19200, 38400, 57600, 115200):
            raise ValueError("Taxa serial não suportada por esta interface.")
        if parity not in ("N", "E", "O"):
            raise ValueError("Paridade deve ser N, E ou O.")
        ok, message = connect_serial(port, unit_id, baudrate, parity)
        return jsonify({"ok": ok, "message": message, "status": connection_info}), (200 if ok else 502)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/disconnect")
def api_disconnect():
    disconnect_serial()
    return jsonify({"ok": True, "message": "Conexão serial encerrada."})


@app.get("/api/telemetry")
def api_telemetry():
    if connection_info["connected"]:
        refresh_telemetry()
    return jsonify({
        "ok": bool(latest_telemetry["connected"]),
        "connection": connection_info,
        "telemetry": latest_telemetry,
        "write_commands_enabled": WRITE_COMMANDS_ENABLED,
    })


@app.post("/api/calculate")
def calculate():
    data = request.get_json(silent=True) or {}
    try:
        flow_4ma = parse_number(data.get("flow_4ma"), "Vazão em 4 mA")
        flow_20ma = parse_number(data.get("flow_20ma"), "Vazão em 20 mA")
        setpoint = parse_number(data.get("setpoint"), "Setpoint")
        if flow_20ma <= flow_4ma:
            raise ValueError("A vazão em 20 mA deve ser maior que a vazão em 4 mA.")
        if not flow_4ma <= setpoint <= flow_20ma:
            raise ValueError(f"A vazão desejada deve estar entre {flow_4ma:g} e {flow_20ma:g} m³/h.")
        percentage = (setpoint - flow_4ma) / (flow_20ma - flow_4ma) * 100.0
        equivalent_current = 4.0 + percentage * 0.16
        return jsonify({
            "ok": True, "flow_4ma": flow_4ma, "flow_20ma": flow_20ma,
            "setpoint": setpoint, "percentage": percentage,
            "equivalent_current_ma": equivalent_current,
            "write_enabled": WRITE_COMMANDS_ENABLED,
            "message": "Cálculo concluído. Para enviar, use o botão Enviar setpoint ao inversor."
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def modbus_write_register(modbus_client, address, value, unit_id=1):
    """Escreve um holding register, compatível com versões do pymodbus 3.x."""
    attempts = (
        {"address": address, "value": value, "device_id": unit_id},
        {"address": address, "value": value, "slave": unit_id},
        {"address": address, "value": value, "unit": unit_id},
    )
    last_type_error = None
    for kwargs in attempts:
        try:
            response = modbus_client.write_register(**kwargs)
            if response is None or response.isError():
                raise RuntimeError(f"O inversor rejeitou a escrita do registrador {address} (P{address:04d}).")
            return response
        except TypeError as exc:
            last_type_error = exc
    raise RuntimeError(f"API de escrita Modbus incompatível com esta versão do pymodbus: {last_type_error}")


@app.post("/api/setpoint")
def api_setpoint():
    """Escreve somente P0525 (setpoint PID); nunca liga/desliga o motor."""
    if not WRITE_COMMANDS_ENABLED:
        return jsonify({"ok": False, "error": "A escrita de setpoint está desabilitada no servidor."}), 403
    payload = request.get_json(silent=True) or {}
    try:
        flow_4ma = parse_number(payload.get("flow_4ma", DEFAULT_FLOW_4MA), "Vazão em 4 mA")
        flow_20ma = parse_number(payload.get("flow_20ma", DEFAULT_FLOW_20MA), "Vazão em 20 mA")
        flow = parse_number(payload.get("setpoint"), "Setpoint")
        if flow_20ma <= flow_4ma:
            raise ValueError("A vazão em 20 mA deve ser maior que a vazão em 4 mA.")
        if not flow_4ma <= flow <= flow_20ma:
            raise ValueError(f"A vazão deve estar entre {flow_4ma:g} e {flow_20ma:g} m³/h.")
        if not payload.get("confirmed"):
            raise ValueError("Marque a confirmação antes de enviar o setpoint.")

        with client_lock:
            if client is None or not connection_info["connected"]:
                raise RuntimeError("Conecte ao inversor antes de enviar o setpoint.")
            unit_id = connection_info["unit_id"]
            # Fail-safe: confirmar as condições de escala/origem antes de escrever.
            p0203 = read_parameter(203, unit_id)
            p0222 = read_parameter(222, unit_id)
            p0528 = read_parameter(528, unit_id)
            p0529 = read_parameter(529, unit_id)
            if p0203 != 1:
                raise RuntimeError(f"Bloqueado: P0203={p0203}; esperado P0203=1 (realimentação AI1). Nenhuma escrita foi feita.")
            if p0222 != 0:
                raise RuntimeError(f"Bloqueado: P0222={p0222}; esperado P0222=0 para referência do PID pela HMI/P0525. Nenhuma escrita foi feita.")
            if p0528 != 4000 or p0529 != 1:
                raise RuntimeError(f"Bloqueado: escala atual P0528={p0528}, P0529={p0529}; esperado 4000 e 1 para escala 0–400,0. Nenhuma escrita foi feita.")

            percent = (flow - flow_4ma) / (flow_20ma - flow_4ma) * 100.0
            # P0525 faixa 0,0–100,0%; formato de parâmetro com décima: 0–1000 raw.
            raw = int(round(percent * 10.0))
            modbus_write_register(client, 525, raw, unit_id)
            # Ler de volta para validar aceitação, sem assumir que a escrita funcionou.
            readback = read_parameter(525, unit_id)
            if readback != raw:
                raise RuntimeError(f"Escrita enviada, mas a leitura de retorno de P0525 foi {readback}, esperado {raw}. Verifique o inversor antes de continuar.")
            p0041 = read_parameter(41, unit_id)
            p0040 = read_parameter(40, unit_id)
        return jsonify({
            "ok": True,
            "flow_setpoint_m3h": flow,
            "percentage": percent,
            "p0525_raw_written": raw,
            "p0525_percent_readback": readback / 10.0,
            "p0041_raw": p0041,
            "p0041_display": p0041 / 10.0,
            "p0040_raw": p0040,
            "p0040_display": p0040 / 10.0,
            "message": f"Setpoint enviado e P0525 confirmado por leitura: {flow:g} m³/h = {percent:.2f}% (P0525 raw {raw}). Nenhum comando de partida foi enviado."
        })
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/motor/start")
def api_motor_start():
    """Envia comando Gira/Para via P0682 após validações e confirmação do operador."""
    if not MOTOR_COMMANDS_ENABLED:
        return jsonify({"ok": False, "error": "Comandos do motor estão desabilitados no servidor."}), 403
    payload = request.get_json(silent=True) or {}
    if not payload.get("confirmed"):
        return jsonify({"ok": False, "error": "Confirme explicitamente a partida."}), 400
    try:
        with client_lock:
            if client is None or not connection_info["connected"]:
                raise RuntimeError("Conecte ao inversor antes de comandar a partida.")
            unit_id = connection_info["unit_id"]
            # Verificações de configuração e estado antes de qualquer comando de movimento.
            p0006 = read_parameter(6, unit_id)
            p0203 = read_parameter(203, unit_id)
            p0222 = read_parameter(222, unit_id)
            p0227 = read_parameter(227, unit_id)
            p0316 = read_parameter(316, unit_id)
            p0525 = read_parameter(525, unit_id)
            p0041 = read_parameter(41, unit_id)
            p0528 = read_parameter(528, unit_id)
            p0529 = read_parameter(529, unit_id)
            p0680 = read_parameter(680, unit_id)
            if p0680 & 0x8000:
                raise RuntimeError("Partida bloqueada: P0680 indica falha ativa. Consulte o código de falha no inversor.")
            if p0680 & 0x0040:
                raise RuntimeError("Partida bloqueada: o inversor indica modo de configuração.")
            if not (p0680 & 0x1000):
                raise RuntimeError("Partida bloqueada: P0680 não indica modo remoto (bit 12). Confira P0220 e a seleção LOC/REM.")
            if p0006 != 0:
                raise RuntimeError(f"Partida bloqueada: P0006={p0006}; esperado estado pronto (0). Confira alarmes, permissivos e estado do inversor.")
            if p0203 != 1 or p0222 != 0 or p0227 != 2:
                raise RuntimeError(f"Partida bloqueada por configuração: P0203={p0203}, P0222={p0222}, P0227={p0227}; esperado 1, 0 e 2.")
            if p0316 != 1:
                raise RuntimeError(f"Partida bloqueada: interface serial não está ativa (P0316={p0316}).")
            if p0528 != 4000 or p0529 != 1:
                raise RuntimeError(f"Partida bloqueada: escala PID inesperada (P0528={p0528}, P0529={p0529}).")
            if p0525 <= 0:
                raise RuntimeError("Partida bloqueada: P0525 está em zero. Envie primeiro um setpoint positivo e confirme a faixa útil segura da bancada.")
            if not (p0680 & 0x4000):
                raise RuntimeError("Partida bloqueada: P0680 não indica modo automático do PID (bit 14). Confirme a configuração do regulador antes de partir.")
            # Não permita partir com valor diferente do setpoint atualmente exibido na interface.
            flow_4ma = parse_number(payload.get("flow_4ma", DEFAULT_FLOW_4MA), "Vazão em 4 mA")
            flow_20ma = parse_number(payload.get("flow_20ma", DEFAULT_FLOW_20MA), "Vazão em 20 mA")
            requested_flow = parse_number(payload.get("setpoint"), "Setpoint")
            if flow_20ma <= flow_4ma or not flow_4ma <= requested_flow <= flow_20ma:
                raise RuntimeError("Partida bloqueada: faixa ou setpoint da interface inválido.")
            expected_percent = (requested_flow - flow_4ma) / (flow_20ma - flow_4ma) * 100.0
            expected_raw = int(round(expected_percent * 10.0))
            if p0525 != expected_raw:
                raise RuntimeError(f"Partida bloqueada: P0525 atual={p0525} (raw), mas o setpoint exibido corresponde a {expected_raw}. Clique em Enviar setpoint ao inversor e tente novamente.")
            expected_p0041_raw = int(round(requested_flow * 10.0))
            if abs(p0041 - expected_p0041_raw) > 1:
                raise RuntimeError(f"Partida bloqueada: P0041={p0041 / 10.0:.1f}, mas a vazão solicitada é {requested_flow:.1f} m³/h. Confirme a origem/escala efetiva do setpoint PID antes de ligar.")

            modbus_write_register(client, 682, CONTROL_RUN_FORWARD_REMOTE, unit_id)
            time.sleep(0.35)
            p0680_after = read_parameter(680, unit_id)
            p0006_after = read_parameter(6, unit_id)
        # Resposta separa comando aceito de confirmação de estado físico.
        return jsonify({
            "ok": True,
            "command_hex": f"0x{CONTROL_RUN_FORWARD_REMOTE:04X}",
            "p0680_hex": f"0x{p0680_after:04X}",
            "p0006": p0006_after,
            "running_bit": bool(p0680_after & 0x0100),
            "enabled_bit": bool(p0680_after & 0x0200),
            "message": ("Comando de partida enviado. " +
                        ("P0680 confirma indicação de giro." if p0680_after & 0x0100 else
                         "O comando foi aceito pela comunicação, mas P0680 ainda não confirma giro. Verifique permissivos, referência mínima, rampa e configuração do PID; não repita continuamente."))
        })
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/motor/stop")
def api_motor_stop():
    """Solicita parada normal pela rampa. Não substitui a emergência física."""
    if not MOTOR_COMMANDS_ENABLED:
        return jsonify({"ok": False, "error": "Comandos do motor estão desabilitados no servidor."}), 403
    payload = request.get_json(silent=True) or {}
    if not payload.get("confirmed"):
        return jsonify({"ok": False, "error": "Confirme explicitamente a parada normal."}), 400
    try:
        with client_lock:
            if client is None or not connection_info["connected"]:
                raise RuntimeError("Sem conexão Modbus: não foi possível enviar a parada normal. Use o procedimento físico de segurança se necessário.")
            unit_id = connection_info["unit_id"]
            # Bit 0=0 solicita parada por rampa; mantém habilitação geral, sentido e remoto.
            modbus_write_register(client, 682, CONTROL_STOP_RAMP_REMOTE, unit_id)
            time.sleep(0.35)
            p0680_after = read_parameter(680, unit_id)
            p0006_after = read_parameter(6, unit_id)
        return jsonify({
            "ok": True,
            "command_hex": f"0x{CONTROL_STOP_RAMP_REMOTE:04X}",
            "p0680_hex": f"0x{p0680_after:04X}",
            "p0006": p0006_after,
            "running_bit": bool(p0680_after & 0x0100),
            "message": ("Comando de parada normal enviado pela rampa." +
                        (" O estado ainda indica giro; aguarde a desaceleração e atualize a leitura." if p0680_after & 0x0100 else " P0680 já não indica giro."))
        })
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


if __name__ == "__main__":
    # Somente acesso local; não exponha a interface diretamente à rede.
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
