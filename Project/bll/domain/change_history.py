"""Presentation rules for the Change History table."""

from ...core.mac import split_macs
from ...core.text import normalize_value


def short_change_value(
    value,
    change_type
):
    """Keep Change History values compact."""

    value = normalize_value(value)

    if str(change_type).lower() != "mac":
        return value

    macs = split_macs(value)

    if not macs:
        return "-"

    return ", ".join(macs)


def is_multiple_macs_history_row(row):
    """Return True for MAC-change rows where either side has 2 or more MACs."""

    if str(row["change_type"] or "").lower() != "mac":
        return False

    old_macs = split_macs(row["old_value"])
    new_macs = split_macs(row["new_value"])

    return len(old_macs) >= 2 or len(new_macs) >= 2


def prepare_change_history_rows(rows):
    """
    Mark consecutive rows that belong to the same physical change event.

    Rows with the same timestamp, switch and port are rendered as one
    merged Date / Time, Switch and Port cell using HTML rowspan.
    """

    prepared = [dict(row) for row in rows]

    index = 0
    while index < len(prepared):
        row = prepared[index]
        group_key = (
            row.get("detected_at"),
            row.get("host"),
            row.get("port"),
        )

        group_end = index + 1

        while group_end < len(prepared):
            candidate = prepared[group_end]
            candidate_key = (
                candidate.get("detected_at"),
                candidate.get("host"),
                candidate.get("port"),
            )

            if candidate_key != group_key:
                break

            group_end += 1

        group_size = group_end - index

        for group_index in range(index, group_end):
            prepared[group_index]["group_start"] = (
                group_index == index
            )
            prepared[group_index]["group_size"] = group_size
            prepared[group_index]["group_end"] = (
                group_index == group_end - 1
            )

        index = group_end

    return prepared
