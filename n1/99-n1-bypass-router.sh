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


# Preload frpc configuration only. Do not auto-start frpc.
uci set frpc.common='conf'
uci set frpc.common.server_addr='38.14.'
uci set frpc.common.server_port='7000'
uci set frpc.common.token='315600'

uci set frpc.n1_web='conf'
uci set frpc.n1_web.type='http'
uci set frpc.n1_web.local_ip='127.0.0.1'
uci set frpc.n1_web.local_port='80'
uci set frpc.n1_web.custom_domains='ys.315600.xyz'

uci set frpc.n1_ssh='conf'
uci set frpc.n1_ssh.type='tcp'
uci set frpc.n1_ssh.local_ip='127.0.0.1'
uci set frpc.n1_ssh.local_port='22'
uci set frpc.n1_ssh.remote_port='2222'
uci commit frpc

# Keep frpc disabled by default; user can start it manually from LuCI or SSH.
/etc/init.d/frpc disable 2>/dev/null || true
/etc/init.d/frpc stop 2>/dev/null || true

# Reduce noisy logs for optional services.
uci -q set mosdns.config.log_level='error'
uci -q commit mosdns
uci -q set bandix.general.log_level='error'
uci -q commit bandix

# Keep WebUI/SSH reachable on all interfaces.
uci -q delete ttyd.@ttyd[0].interface
uci set dropbear.@dropbear[0].Interface=''
uci commit ttyd
uci commit dropbear

echo "N1 bypass router mode done: LAN=$LAN_IP gateway=$MAIN_ROUTER dns=$MAIN_ROUTER IPv6=lan6 DHCP=disabled firewall_lan=br-lan,docker0 frpc=config-only" >> "$LOGFILE"

exit 0
