"""MAC address helpers."""


def normalize_mac(value):
    """Return aa:bb:cc:dd:ee:ff for colon, dash or Cisco dotted notation."""

    if not value:
        return ""

    value = str(value).strip().lower()
    value = value.replace("-", ":")

    if "." in value and ":" not in value:
        compact = value.replace(".", "")

        if len(compact) == 12:
            value = ":".join(
                compact[i:i + 2]
                for i in range(0, 12, 2)
            )

    return value


def split_macs(value):
    """Split a comma-separated MAC list into unique normalized MACs."""

    if value in (None, "", "-"):
        return []

    result = []

    for item in str(value).split(","):
        mac = normalize_mac(item)

        if mac and mac != "-" and mac not in result:
            result.append(mac)

    return result
