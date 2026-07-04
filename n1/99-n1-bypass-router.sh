#!/bin/sh
# N1 bypass router defaults.
# IP: 192.168.2.254, gateway/DNS: 192.168.2.1.
# This script runs on first boot from /etc/uci-defaults/.

LOGFILE="/etc/config/uci-defaults-log.txt"
echo "Configuring Phicomm N1 bypass router mode at $(date)" >> "$LOGFILE"

LAN_IP="192.168.2.254"
LAN_NETMASK="255.255.255.0"
MAIN_ROUTER="192.168.2.1"

# Configure LAN as static bypass-router address.
uci set network.lan.proto='static'
uci set network.lan.ipaddr="$LAN_IP"
uci set network.lan.netmask="$LAN_NETMASK"
uci set network.lan.gateway="$MAIN_ROUTER"
uci set network.lan.dns="$MAIN_ROUTER"
uci set network.lan.delegate='0'
uci commit network

# Disable DHCP server on N1. Main router should keep serving DHCP.
uci set dhcp.lan.ignore='1'
uci set dhcp.lan.dynamicdhcp='0'
uci commit dhcp

# Keep WebUI/SSH reachable on the single LAN interface.
uci -q delete ttyd.@ttyd[0].interface
uci set dropbear.@dropbear[0].Interface=''
uci commit ttyd
uci commit dropbear

echo "N1 bypass router mode done: LAN=$LAN_IP gateway=$MAIN_ROUTER dns=$MAIN_ROUTER DHCP=disabled" >> "$LOGFILE"

exit 0
