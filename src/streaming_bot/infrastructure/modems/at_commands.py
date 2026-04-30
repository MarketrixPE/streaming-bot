"""Constantes y parsers para AT commands estandar de modems Quectel/Huawei.

Los modems 4G/5G LTE soportan un set comun de AT commands derivados de la
especificacion 3GPP TS 27.007. Aqui agrupamos los que necesitamos para:

- Health check (AT, AT+CSQ).
- Identidad (AT+CGSN, AT+CCID).
- Operador y red (AT+COPS?).
- Reconexion / rotacion de IP (AT+CFUN=4 -> AT+CFUN=1).
- Reset duro (AT+CFUN=1,1).

Las funciones de parseo aceptan la respuesta cruda multilinea del modem
(incluido el eco del comando + la linea final "OK").
"""

from __future__ import annotations

import re

# Comandos basicos.
AT_PING: str = "AT"
AT_GET_IMEI: str = "AT+CGSN"
AT_GET_ICCID: str = "AT+CCID"
AT_GET_SIGNAL: str = "AT+CSQ"
AT_GET_OPERATOR: str = "AT+COPS?"

# Reconexion sin reboot (rotacion de IP).
# CFUN=4 -> airplane mode (radio off). CFUN=1 -> radio on.
# El detach + reattach fuerza al carrier a asignar nueva IP publica.
AT_CFUN_AIRPLANE: str = "AT+CFUN=4"
AT_CFUN_FULL: str = "AT+CFUN=1"

# Reset duro del modulo (reinicia firmware). Util cuando el modem se cuelga.
AT_RESET: str = "AT+CFUN=1,1"

# Secuencia logica de rotacion de IP (no es un comando, es una "macro").
AT_RECONNECT_SEQUENCE: tuple[str, str] = (AT_CFUN_AIRPLANE, AT_CFUN_FULL)

# Terminadores estandar de respuesta del modem.
_OK_TERMINATOR: str = "OK"
_ERROR_TERMINATOR: str = "ERROR"

_CSQ_PATTERN: re.Pattern[str] = re.compile(r"\+CSQ:\s*(\d+)\s*,\s*(\d+)")
_COPS_PATTERN: re.Pattern[str] = re.compile(r'\+COPS:\s*\d+\s*,\s*\d+\s*,\s*"([^"]+)"')


def is_terminal_line(line: str) -> bool:
    """Indica si la linea cierra una respuesta AT (OK / ERROR / +CME ERROR)."""
    stripped = line.strip()
    if stripped == _OK_TERMINATOR:
        return True
    if stripped == _ERROR_TERMINATOR:
        return True
    return stripped.startswith("+CME ERROR") or stripped.startswith("+CMS ERROR")


def parse_csq(response: str) -> int | None:
    """Parsea la respuesta de AT+CSQ y devuelve la potencia de senal en dBm.

    Formato: ``+CSQ: <rssi>,<ber>``
    - rssi 0..31 -> mapea a -113..-51 dBm en pasos de 2 dBm.
    - rssi 99    -> sin senal (devolvemos None).

    Conversion documentada en 3GPP TS 27.007 secc. 8.5.
    """
    match = _CSQ_PATTERN.search(response)
    if match is None:
        return None
    rssi = int(match.group(1))
    if rssi == 99:
        return None
    if not 0 <= rssi <= 31:
        return None
    return -113 + rssi * 2


def parse_cops(response: str) -> str | None:
    """Parsea AT+COPS? y devuelve el nombre operador (alfanumerico).

    Formato esperado: ``+COPS: <mode>,<format>,"<name>"[,<act>]``
    Si format != 0 (alfanumerico) igual aceptamos lo que venga entre comillas.
    """
    match = _COPS_PATTERN.search(response)
    if match is None:
        return None
    name = match.group(1).strip()
    return name or None


def extract_imei(response: str) -> str | None:
    """Extrae el IMEI (15 digitos) de la respuesta de AT+CGSN."""
    for raw in response.splitlines():
        candidate = raw.strip()
        if candidate.isdigit() and len(candidate) == 15:
            return candidate
    return None


def extract_iccid(response: str) -> str | None:
    """Extrae el ICCID de la respuesta de AT+CCID.

    Algunos modems contestan ``+CCID: <iccid>``; otros sueltan el numero crudo.
    """
    for raw in response.splitlines():
        line = raw.strip()
        if line.startswith("+CCID:"):
            return line.split(":", 1)[1].strip().strip('"')
        if line.isdigit() and 18 <= len(line) <= 22:
            return line
    return None
