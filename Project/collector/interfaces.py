"""Interface naming rules: which interfaces are physical ports, their order
and how speed/link values are displayed."""

import re


def is_physical_ethernet(
    interface_name: str
) -> bool:
    """
    Определяет, является ли интерфейс физическим Ethernet-портом.

    Поддерживаются:

    Dell EMC OS10:
        ethernet1/1/1
        ethernet1/1/48
        ethernet1/2

    Cisco:
        Gi1/1
        Gi1/48
        Gi0/1
        Te1/49
        Te1/52
        Fa1/1
        Eth1/1
        Twe1/1
        Fo1/1
        Hu1/1

    MikroTik:
        ether1
        ether24
        sfp9
        sfp12
        sfp-sfpplus1
        sfp-sfpplus2

    НЕ считаются физическими:

        Po1
        Po41
        VLAN-140
        Vl140
        vlan140-adm
        Nu0
        Fa0
        SW81
        LACP-SW-core
        Loopback
        Bridge
    """

    name = interface_name.strip()

    if not name:
        return False

    # --------------------------------------------------------
    # Исключения
    # --------------------------------------------------------

    excluded_prefixes = (
        "Po",
        "Port-channel",
        "VLAN",
        "vlan",
        "Vl",
        "Nu",
        "Loopback",
        "Lo",
        "Bridge",
        "Bond",
        "LACP",
        "SW",
    )

    for prefix in excluded_prefixes:
        if name.startswith(prefix):
            return False

    # --------------------------------------------------------
    # Dell EMC OS10
    # --------------------------------------------------------

    dell_patterns = [
        r"^ethernet\d+/\d+/\d+$",
        r"^ethernet\d+/\d+$",
    ]

    for pattern in dell_patterns:

        if re.match(
            pattern,
            name,
            re.IGNORECASE
        ):
            return True

    # --------------------------------------------------------
    # Cisco
    # --------------------------------------------------------

    cisco_patterns = [

        # Short names

        r"^Gi\d+/\d+$",
        r"^Gi\d+/\d+/\d+$",

        r"^Te\d+/\d+$",
        r"^Te\d+/\d+/\d+$",

        r"^Fa\d+/\d+$",
        r"^Fa\d+/\d+/\d+$",

        r"^Eth\d+/\d+$",
        r"^Eth\d+/\d+/\d+$",

        r"^Twe\d+/\d+$",
        r"^Twe\d+/\d+/\d+$",

        r"^Fo\d+/\d+$",
        r"^Fo\d+/\d+/\d+$",

        r"^Hu\d+/\d+$",
        r"^Hu\d+/\d+/\d+$",

        # Long names

        r"^GigabitEthernet\d+/\d+$",
        r"^GigabitEthernet\d+/\d+/\d+$",

        r"^TenGigabitEthernet\d+/\d+$",
        r"^TenGigabitEthernet\d+/\d+/\d+$",

        r"^FastEthernet\d+/\d+$",
        r"^FastEthernet\d+/\d+/\d+$",

        r"^Ethernet\d+/\d+$",
        r"^Ethernet\d+/\d+/\d+$",

        r"^TwentyFiveGigE\d+/\d+$",
        r"^TwentyFiveGigE\d+/\d+/\d+$",

        r"^FortyGigabitEthernet\d+/\d+$",
        r"^FortyGigabitEthernet\d+/\d+/\d+$",

        r"^HundredGigE\d+/\d+$",
        r"^HundredGigE\d+/\d+/\d+$",
    ]

    for pattern in cisco_patterns:

        if re.match(
            pattern,
            name,
            re.IGNORECASE
        ):
            return True

    # --------------------------------------------------------
    # MikroTik
    # --------------------------------------------------------

    mikrotik_patterns = [

        # ether1 ... ether99

        r"^ether\d+$",

        # sfp1 ... sfp99

        r"^sfp\d+$",

        # sfp-sfpplus1 ... sfp-sfpplus99

        r"^sfp-sfpplus\d+$",

        # sfpplus1 ... sfpplus99

        r"^sfpplus\d+$",

        # sfp28-1 etc. — встречается на некоторых моделях

        r"^sfp\d+-\d+$",
    ]

    for pattern in mikrotik_patterns:

        if re.match(
            pattern,
            name,
            re.IGNORECASE
        ):
            return True

    return False


def extract_port_number(
    interface_name: str
) -> int:
    """
    Возвращает номер физического порта.

    Примеры:

        Gi1/1          -> 1
        Gi1/48         -> 48
        Te1/49         -> 49

        Gi0/1          -> 1

        ether1         -> 1
        ether24        -> 24

        sfp9           -> 9
        sfp-sfpplus2   -> 2

        ethernet1/1/1  -> 1
        ethernet1/1/48 -> 48

    Если определить номер невозможно:
        возвращает 0
    """

    name = interface_name.strip()

    # --------------------------------------------------------
    # Cisco / Dell
    #
    # Берём последнее число после "/"
    # --------------------------------------------------------

    if "/" in name:

        parts = name.split("/")

        last_part = parts[-1]

        match = re.search(
            r"(\d+)$",
            last_part
        )

        if match:
            return int(
                match.group(1)
            )

    # --------------------------------------------------------
    # MikroTik
    # --------------------------------------------------------

    match = re.search(
        r"(\d+)$",
        name
    )

    if match:
        return int(
            match.group(1)
        )

    return 0


def interface_sort_key(
    interface_name: str
):
    """
    Естественная сортировка физических интерфейсов.

    Основная задача — не смешивать разные группы портов.

    Например Cisco:

        Gi1/0/1
        Gi1/0/2
        ...
        Gi1/0/48
        Gi1/1/1
        Gi1/1/2
        ...
        Te1/1/1
        Te1/1/2

    MikroTik:

        ether1
        ether2
        ...
        ether24
        sfp9
        sfp10
        ...

    Dell OS10:

        ethernet1/1/1
        ethernet1/1/2
        ...

    Возвращаем ключ:
        (приоритет_типа, все_числа_из_имени, имя)

    Поэтому Gigabit-порты идут раньше TenGigabit-портов,
    а внутри одного типа сохраняется естественный числовой
    порядок.
    """

    name = interface_name.strip()
    lower = name.lower()

    # --------------------------------------------------------
    # Тип интерфейса / приоритет
    # --------------------------------------------------------

    # MikroTik сначала проверяем отдельно, потому что ether1
    # не должен смешиваться с другими типами.

    if re.fullmatch(
        r"ether\d+",
        lower
    ):
        type_priority = 20

    elif re.fullmatch(
        r"sfp\d+",
        lower
    ):
        type_priority = 40

    elif re.fullmatch(
        r"sfp-sfpplus\d+",
        lower
    ):
        type_priority = 50

    elif re.fullmatch(
        r"sfpplus\d+",
        lower
    ):
        type_priority = 50

    elif re.fullmatch(
        r"sfp\d+-\d+",
        lower
    ):
        type_priority = 50

    # Cisco / Dell

    elif lower.startswith(
        "fastethernet"
    ) or re.match(
        r"^fa\d",
        lower
    ):
        type_priority = 10

    elif lower.startswith(
        "gigabitethernet"
    ) or re.match(
        r"^gi\d",
        lower
    ):
        type_priority = 20

    elif (
        lower.startswith(
            "ethernet"
        )
        or re.match(
            r"^eth\d",
            lower
        )
    ):
        type_priority = 30

    elif lower.startswith(
        "tengigabitethernet"
    ) or re.match(
        r"^te\d",
        lower
    ):
        type_priority = 40

    elif lower.startswith(
        "twentyfivegige"
    ) or re.match(
        r"^twe\d",
        lower
    ):
        type_priority = 50

    elif lower.startswith(
        "fortygigabitethernet"
    ) or re.match(
        r"^fo\d",
        lower
    ):
        type_priority = 60

    elif lower.startswith(
        "hundredgige"
    ) or re.match(
        r"^hu\d",
        lower
    ):
        type_priority = 70

    else:
        type_priority = 100

    numbers = tuple(
        int(number)
        for number in re.findall(
            r"\d+",
            name
        )
    )

    return (
        type_priority,
        numbers,
        lower,
    )


def format_speed(value: str) -> str:

    try:

        speed = int(value)

    except (
        ValueError,
        TypeError
    ):

        return "-"

    if speed <= 0:
        return "-"

    if speed >= 1000:

        if speed % 1000 == 0:

            return (
                f"{speed // 1000}G"
            )

        return (
            f"{speed / 1000:g}G"
        )

    return f"{speed}M"


def format_link(value: str) -> str:

    try:

        status = int(value)

    except (
        ValueError,
        TypeError
    ):

        return "-"

    if status == 1:
        return "UP"

    if status == 2:
        return "DOWN"

    return "-"
