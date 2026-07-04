#!/bin/sh
# N1 bypass router defaults.
# IPv4: 192.168.2.254, gateway/DNS: 192.168.2.1.
# IPv6: enable DHCPv6/SLAAC client on LAN.
# Docker: put docker0 into lan firewall zone directly, no separate docker zone.
# This script runs on first boot from /etc/uci-defaults/ after 99-custom.sh.

LOGFILE="/etc/config/uci-defaults-log.txt"
echo "Configuring Phicomm N1 bypass router mode at $(date)" >> "$LOGFILE"

LAN_IP="192.168.2.254"
LAN_NETMASK="255.255.255.0"
MAIN_ROUTER="192.168.2.1"

# Configure LAN as static IPv4 bypass-router address.
uci set network.lan.proto='static'
uci set network.lan.ipaddr="$LAN_IP"
uci set network.lan.netmask="$LAN_NETMASK"
uci set network.lan.gateway="$MAIN_ROUTER"
uci set network.lan.dns="$MAIN_ROUTER"
uci set network.lan.delegate='0'

# Enable IPv6 client mode on LAN. The main router should provide RA/DHCPv6.
uci set network.lan6='interface'
uci set network.lan6.device='@lan'
uci set network.lan6.proto='dhcpv6'
uci set network.lan6.reqaddress='try'
uci set network.lan6.reqprefix='auto'
uci set network.lan6.peerdns='1'
uci commit network

# Disable DHCP server on N1. Main router should keep serving DHCP.
uci set dhcp.lan.ignore='1'
uci set dhcp.lan.dynamicdhcp='0'
uci commit dhcp

# Remove any separate docker zone/forwarding created by common defaults.
uci -q delete firewall.docker
for idx in $(uci show firewall | grep '=forwarding' | cut -d[ -f2 | cut -d] -f1 | sort -rn); do
    src=$(uci -q get firewall.@forwarding[$idx].src)
    dest=$(uci -q get firewall.@forwarding[$idx].dest)
    if [ "$src" = "docker" ] || [ "$dest" = "docker" ]; then
        uci -q delete firewall.@forwarding[$idx]
    fi
done

# Put br-lan and docker0 directly into lan zone.
LAN_ZONE=""
for zone in $(uci show firewall | awk -F= '/=zone$/ {print $1}'); do
    name=$(uci -q get "$zone.name")
    if [ "$name" = "lan" ]; then
        LAN_ZONE="$zone"
        break
    fi
done

if [ -z "$LAN_ZONE" ]; then
    LAN_ZONE="firewall.lan"
    uci set firewall.lan='zone'
    uci set firewall.lan.name='lan'
fi

uci set "$LAN_ZONE.input"='ACCEPT'
uci set "$LAN_ZONE.output"='ACCEPT'
uci set "$LAN_ZONE.forward"='ACCEPT'
uci -q delete "$LAN_ZONE.network"
uci add_list "$LAN_ZONE.network"='lan'
uci -q delete "$LAN_ZONE.device"
uci add_list "$LAN_ZONE.device"='br-lan'
uci add_list "$LAN_ZONE.device"='docker0'
uci commit firewall

# Keep WebUI/SSH reachable on all interfaces.
uci -q delete ttyd.@ttyd[0].interface
uci set dropbear.@dropbear[0].Interface=''
uci commit ttyd
uci commit dropbear

echo "N1 bypass router mode done: LAN=$LAN_IP gateway=$MAIN_ROUTER dns=$MAIN_ROUTER IPv6=lan6 DHCP=disabled firewall_lan=br-lan,docker0" >> "$LOGFILE"

exit 0
