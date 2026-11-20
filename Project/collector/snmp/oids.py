"""SNMP OIDs used by the collector."""


OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"

# BRIDGE-MIB
OID_DOT1D_BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"

# Q-BRIDGE-MIB
# dot1qTpFdbPort.<VLAN>.<MAC>
OID_DOT1Q_TP_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"

# BRIDGE-MIB
# dot1dTpFdbPort.<MAC>
OID_DOT1D_TP_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"

# CISCO-VTP-MIB
# vtpVlanState.<managementDomainIndex>.<vlanId>
# Used as a fallback to discover VLANs on older Cisco Catalyst
# switches whose BRIDGE-MIB FDB is exposed through community@VLAN.
OID_CISCO_VTP_VLAN_STATE = "1.3.6.1.4.1.9.9.46.1.3.1.1.2"

# System identity
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_ENT_PHYSICAL_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"
OID_MIKROTIK_BOARD_NAME = "1.3.6.1.4.1.14988.1.1.7.8.0"

# IP-MIB / MIB-II ARP/neighbor tables.
# Modern devices: ipNetToPhysicalPhysAddress.<ifIndex>.<addrType>.<address>
OID_IP_NET_TO_PHYSICAL_PHYS_ADDRESS = "1.3.6.1.2.1.4.35.1.4"
# Legacy fallback: ipNetToMediaPhysAddress.<ifIndex>.<IPv4>
OID_IP_NET_TO_MEDIA_PHYS_ADDRESS = "1.3.6.1.2.1.4.22.1.2"

# LLDP-MIB (IEEE 802.1AB)
# lldpRemTable index: lldpRemTimeMark.lldpRemLocalPortNum.lldpRemIndex
OID_LLDP_REM_CHASSIS_ID = "1.0.8802.1.1.2.1.4.1.1.5"
OID_LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
OID_LLDP_REM_PORT_DESC = "1.0.8802.1.1.2.1.4.1.1.8"
OID_LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
# lldpLocPortTable index: lldpLocPortNum
OID_LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3"
OID_LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4"

# CISCO-CDP-MIB cdpCacheTable index: ifIndex.cdpCacheDeviceIndex
OID_CDP_CACHE_DEVICE_ID = "1.3.6.1.4.1.9.9.23.1.2.1.1.6"
OID_CDP_CACHE_DEVICE_PORT = "1.3.6.1.4.1.9.9.23.1.2.1.1.7"
OID_CDP_CACHE_PLATFORM = "1.3.6.1.4.1.9.9.23.1.2.1.1.8"

# Q-BRIDGE-MIB VLANs
# dot1qPvid.<bridgePort>: the untagged (access / native) VLAN of a port
OID_DOT1Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
# dot1qVlanCurrentEgressPorts / UntaggedPorts.<timeMark>.<vlan>: PortList bitmaps
OID_DOT1Q_VLAN_CURRENT_EGRESS = "1.3.6.1.2.1.17.7.1.4.2.1.4"
OID_DOT1Q_VLAN_CURRENT_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.2.1.5"
# dot1qVlanStaticEgressPorts / UntaggedPorts.<vlan>
OID_DOT1Q_VLAN_STATIC_EGRESS = "1.3.6.1.2.1.17.7.1.4.3.1.2"
OID_DOT1Q_VLAN_STATIC_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.3.1.4"

# Cisco IOS VLANs, indexed by ifIndex
# CISCO-VLAN-MEMBERSHIP-MIB vmVlan: access VLAN
OID_CISCO_VM_VLAN = "1.3.6.1.4.1.9.9.68.1.2.2.1.2"
# CISCO-VTP-MIB vlanTrunkPortTable
OID_CISCO_TRUNK_NATIVE_VLAN = "1.3.6.1.4.1.9.9.46.1.6.1.1.5"
OID_CISCO_TRUNK_VLANS_ENABLED = "1.3.6.1.4.1.9.9.46.1.6.1.1.4"       # VLANs 0-1023
OID_CISCO_TRUNK_VLANS_ENABLED_2K = "1.3.6.1.4.1.9.9.46.1.6.1.1.17"   # 1024-2047
OID_CISCO_TRUNK_VLANS_ENABLED_3K = "1.3.6.1.4.1.9.9.46.1.6.1.1.18"   # 2048-3071
OID_CISCO_TRUNK_VLANS_ENABLED_4K = "1.3.6.1.4.1.9.9.46.1.6.1.1.19"   # 3072-4095
OID_CISCO_TRUNK_STATUS = "1.3.6.1.4.1.9.9.46.1.6.1.1.14"             # 1 trunking, 2 not

# IF-MIB error counters, indexed by ifIndex (32-bit, may wrap or reset)
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
# EtherLike-MIB dot3StatsFCSErrors.<ifIndex>: CRC errors (bad cable / optics)
OID_DOT3_FCS_ERRORS = "1.3.6.1.2.1.10.7.2.1.3"
