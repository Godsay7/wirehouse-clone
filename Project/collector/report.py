"""Console table, JSON and CSV output of collected ports."""

import csv
from typing import Dict, List


def print_table(
    host: str,
    ports: List[Dict]
):

    headers = [
        "Port",
        "Device",
        "Speed",
        "Link",
        "MAC",
    ]

    rows = []

    for port in ports:

        rows.append(
            [
                str(port["Port"]),
                port["Device"],
                port["Speed"],
                port["Link"],
                port["MAC"],
            ]
        )

    if not rows:
        return

    widths = []

    for index, header in enumerate(
        headers
    ):

        width = len(header)

        for row in rows:

            width = max(
                width,
                len(row[index])
            )

        widths.append(width)

    separator = (
        "+"
        + "+".join(
            "-" * (
                width + 2
            )
            for width in widths
        )
        + "+"
    )

    print()
    print(separator)

    print(
        "| "
        + " | ".join(
            headers[i].ljust(
                widths[i]
            )
            for i in range(
                len(headers)
            )
        )
        + " |"
    )

    print(separator)

    for row in rows:

        print(
            "| "
            + " | ".join(
                row[i].ljust(
                    widths[i]
                )
                for i in range(
                    len(headers)
                )
            )
            + " |"
        )

    print(separator)


def build_json_result(
    all_results: Dict[
        str,
        List[Dict]
    ]
) -> Dict:

    result = {}

    for host, ports in all_results.items():

        result[host] = []

        for port in ports:

            result[host].append(
                {
                    "Port": port["Port"],
                    "Device": port["Device"],
                    "Speed": port["Speed"],
                    "Link": port["Link"],
                    "MAC": port["MAC"],
                }
            )

    return result


def write_csv(
    all_results: Dict[
        str,
        List[Dict]
    ],
    output_file: str
):

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(
            file
        )

        writer.writerow(
            [
                "Switch",
                "Port",
                "Device",
                "Speed",
                "Link",
                "MAC",
            ]
        )

        for host, ports in all_results.items():

            for port in ports:

                writer.writerow(
                    [
                        host,
                        port["Port"],
                        port["Device"],
                        port["Speed"],
                        port["Link"],
                        port["MAC"],
                    ]
                )
