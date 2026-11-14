#!/bin/sh
# N1 bypass router defaults.
# IPv4: 192.168.2.254, gateway/DNS: 192.168.2.1.
# IPv6: enable DHCPv6/SLAAC client on LAN.
# Docker: put docker0 into lan firewall zone directly, no separate docker zone.
# This script runs on first boot from /etc/uci-defaults/ after 99-custom.sh.

[ -z "${IPKG_INSTROOT:-}" ] || exit 1
set -eu
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
uci set network.lan6.peerdns='0'
uci set network.lan6.disabled='0'
# Public IPv6 follows upstream RA/DHCPv6; never retain an old static prefix.
uci -q delete network.lan.ip6addr || true
uci -q delete network.lan.ip6gw || true
uci commit network

# Disable DHCP server on N1. Main router should keep serving DHCP.
uci set dhcp.lan.ignore='1'
uci set dhcp.lan.dynamicdhcp='0'
uci set dhcp.lan.ra='disabled'
uci set dhcp.lan.dhcpv6='disabled'
uci set dhcp.lan.ndp='disabled'
# Router bootstrap DNS is explicitly the IPv4 main router. It must not forward
# back here. Client DNS belongs to Nikki only once private subscriptions are set.
uci set dhcp.@dnsmasq[0].noresolv='1'
uci -q delete dhcp.@dnsmasq[0].server || true
uci add_list dhcp.@dnsmasq[0].server="$MAIN_ROUTER"
uci commit dhcp

# Remove any separate docker zone/forwarding created by common defaults.
uci -q delete firewall.docker || true
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
uci -q delete "$LAN_ZONE.network" || true
uci add_list "$LAN_ZONE.network"='lan'
uci -q delete "$LAN_ZONE.device" || true
uci add_list "$LAN_ZONE.device"='br-lan'
uci add_list "$LAN_ZONE.device"='docker0'
uci commit firewall


# Keep FRPC package optional to configure and never bake shared endpoint credentials.
uci -q delete frpc.common || true
uci -q delete frpc.n1_web || true
uci commit frpc
/etc/init.d/frpc disable 2>/dev/null || true
/etc/init.d/frpc stop 2>/dev/null || true

# Nikki policy is applied by zzz-n1-nikki.sh AFTER the vendor 99_init_nikki.

# Reduce noisy logs for optional services.
uci -q set mosdns.config.log_level='error' && uci -q commit mosdns || true
uci -q set bandix.general.log_level='error' && uci -q commit bandix || true

# Keep WebUI/SSH reachable on all interfaces.
uci -q delete ttyd.@ttyd[0].interface || true
uci set dropbear.@dropbear[0].Interface=''
uci commit ttyd
uci commit dropbear

echo "N1 bypass router mode done: LAN=$LAN_IP gateway=$MAIN_ROUTER dns=$MAIN_ROUTER IPv6=lan6 DHCP=disabled firewall_lan=br-lan,docker0 frpc=config-only" >> "$LOGFILE"

# Configure amlogic only when installed; this used to be after an early exit.
if uci -q get amlogic.config >/dev/null 2>&1; then
    uci set amlogic.config.amlogic_firmware_repo='https://github.com/x315600/ImmortalWrt-ImageBuilder'
    uci set amlogic.config.amlogic_kernel_path='tree/master/n1'
    uci commit amlogic
fi
exit 0
