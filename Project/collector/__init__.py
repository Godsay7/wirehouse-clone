"""SNMP collector.

snmp/        net-snmp wrappers, OIDs and raw output parsers
interfaces   physical port detection, ordering, speed/link formatting
identity     sysName and model
fdb          MAC address tables (Q-BRIDGE, BRIDGE, Cisco per-VLAN)
ports        one switch -> list of port dicts
arp, dns     Core ARP snapshot with reverse DNS hostnames
config       YAML config
storage      saving through the data access layer
report       console/JSON/CSV output
cli          entry point (scripts/collector.py)
"""
