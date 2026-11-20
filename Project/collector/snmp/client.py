"""net-snmp command line wrappers (snmpwalk / snmpget)."""

import re
import subprocess
import sys
from typing import Dict, List


def snmp_walk(
    host: str,
    community: str,
    oid: str
) -> Dict[int, str]:
    """
    Выполняет snmpwalk и возвращает:

        index -> value

    Например:

        10101 -> Gi1/0/1
        10102 -> Gi1/0/2
    """

    command = [
        "snmpwalk",
        "-v2c",
        "-c",
        community,
        "-On",
        "-t",
        "3",
        "-r",
        "1",
        host,
        oid,
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )

    except FileNotFoundError:
        print(
            "ERROR: команда snmpwalk не найдена.\n"
            "Установи:\n"
            "  sudo apt install snmp"
        )
        sys.exit(1)

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"SNMP timeout: {host}"
        )

    if result.returncode != 0:
        error = result.stderr.strip()

        if not error:
            error = "unknown SNMP error"

        raise RuntimeError(
            f"SNMP error on {host}: {error}"
        )

    data = {}

    for line in result.stdout.splitlines():

        line = line.strip()

        if not line:
            continue

        if "No Such Instance" in line:
            continue

        if "No Such Object" in line:
            continue

        match = re.match(
            r"^.*\.(\d+)\s*=\s*(.*)$",
            line
        )

        if not match:
            continue

        index = int(
            match.group(1)
        )

        value = match.group(2).strip()

        if ":" in value:
            value = value.split(
                ":",
                1
            )[1].strip()

        if (
            len(value) >= 2
            and value.startswith('"')
            and value.endswith('"')
        ):
            value = value[1:-1]

        data[index] = value

    return data


def snmp_walk_raw(
    host: str,
    community: str,
    oid: str
) -> List[str]:
    """
    Возвращает строки snmpwalk без преобразования индексов.

    Нужно для MAC-адресов, потому что индекс FDB содержит
    несколько чисел MAC и VLAN.
    """

    command = [
        "snmpwalk",
        "-v2c",
        "-c",
        community,
        "-On",
        "-t",
        "3",
        "-r",
        "1",
        host,
        oid,
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )

    except FileNotFoundError:
        raise RuntimeError(
            "Команда snmpwalk не найдена. "
            "Установи: sudo apt install snmp"
        )

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"SNMP timeout: {host}"
        )

    if result.returncode != 0:
        return []

    return result.stdout.splitlines()


def snmp_get_value(
    host: str,
    community: str,
    oid: str
) -> str:
    """Returns one SNMP scalar value, or an empty string on failure."""

    command = [
        "snmpget",
        "-v2c",
        "-c",
        community,
        "-On",
        "-t",
        "3",
        "-r",
        "1",
        host,
        oid,
    ]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""

    line = result.stdout.strip()

    if not line:
        return ""

    if (
        "No Such Object" in line
        or "No Such Instance" in line
    ):
        return ""

    if "=" not in line:
        return ""

    value = line.split("=", 1)[1].strip()

    # Typical net-snmp output:
    #   STRING: "name"
    #   INTEGER: 1
    if ":" in value:
        value = value.split(":", 1)[1].strip()

    if (
        len(value) >= 2
        and value.startswith('"')
        and value.endswith('"')
    ):
        value = value[1:-1]

    return value.strip()


def parse_table_output(lines: List[str], oid: str) -> Dict[tuple, str]:
    """snmpwalk -On output -> {index tuple after ``oid``: value}.

    Long Hex-STRING values are printed over several lines; the lines that do
    not start with an OID continue the previous value. The type prefix
    ("INTEGER: ", "Hex-STRING: ") and surrounding quotes are dropped.
    """

    prefix = "." + oid.strip(".") + "."
    data: Dict[tuple, str] = {}
    key = None
    for line in lines:
        if line.startswith("."):
            key = None
            if not line.startswith(prefix) or " = " not in line:
                continue
            name, value = line.split(" = ", 1)
            if "No Such" in value or "No more variables" in value:
                continue
            try:
                key = tuple(int(part) for part in name[len(prefix):].split("."))
            except ValueError:
                continue
            value = value.strip()
            if ":" in value and not value.startswith('"'):
                value = value.split(":", 1)[1].strip()
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            data[key] = value
        elif key is not None and line.strip():
            data[key] = (data[key] + " " + line.strip()).strip()
    return data


def snmp_walk_table(
    host: str,
    community: str,
    oid: str,
    hex_values: bool = False,
) -> Dict[tuple, str]:
    """snmpbulkwalk of a table -> {index tuple: value}; {} when the switch
    does not have it or does not answer. hex_values: octet strings as hex
    (port and VLAN bitmaps)."""

    command = ["snmpbulkwalk", "-v2c", "-c", community, "-On", "-t", "3", "-r", "1", "-Cr25"]
    if hex_values:
        command.append("-Ox")
    command += [host, oid]

    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    return parse_table_output(result.stdout.splitlines(), oid)
