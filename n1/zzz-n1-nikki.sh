#!/bin/sh
# Runs after the official package's 99_init_nikki; retained on staging installs.
[ -z "${IPKG_INSTROOT:-}" ] || exit 1
set -eu
[ "$(uci -q get nikki.config.n1_initialized || true)" != '1' ] || exit 0

# Keep all installed alternatives; only Nikki may own transparent interception.
for name in openclash mosdns passwall passwall2; do
    if [ -x "/etc/init.d/$name" ]; then
        "/etc/init.d/$name" stop || true
        "/etc/init.d/$name" disable || true
    fi
done

# The public template has no subscription credentials. Select it now, but only
# enable after its two provider URLs have been entered and tested in LuCI.
uci set nikki.config.enabled='0'
uci set nikki.config.profile='file:nikki-dual.yaml'
uci set nikki.config.scheduled_restart='0'
uci set nikki.config.test_profile='1'
uci set nikki.procd.fast_reload='0'
uci set nikki.proxy.enabled='1'
uci set nikki.proxy.tcp_mode='redirect'
uci set nikki.proxy.udp_mode='tun'
uci set nikki.proxy.ipv4_dns_hijack='1'
uci set nikki.proxy.ipv6_dns_hijack='1'
uci set nikki.proxy.ipv4_proxy='1'
uci set nikki.proxy.ipv6_proxy='1'
uci set nikki.proxy.router_proxy='1'
uci set nikki.proxy.lan_proxy='1'
uci set nikki.mixin.ipv6='1'
uci set nikki.mixin.dns_ipv6='1'
uci set nikki.mixin.dns_enabled='1'
uci set nikki.mixin.dns_listen='[::]:1053'
uci set nikki.mixin.dns_mode='fake-ip'
uci set nikki.mixin.tun_enabled='1'
# Preserve the tested profile's DNS policies, fake-IP rules and service rules.
uci set nikki.mixin.fake_ip_filter='0'
uci set nikki.mixin.dns_nameserver='0'
uci set nikki.mixin.dns_nameserver_policy='0'
uci set nikki.mixin.dns_proxy_server_nameserver_policy='0'
uci set nikki.mixin.hosts='0'
uci set nikki.mixin.dns_hosts='0'
uci set nikki.mixin.dns_system_hosts='0'
uci set nikki.mixin.rule='0'
uci set nikki.mixin.rule_provider='0'
uci set nikki.mixin.api_listen='192.168.2.254:9090'
uci set nikki.mixin.authentication='1'

# Separate API/proxy credentials; no administrator password in the image.
# This guard also makes manually rerunning this script preserve existing keys.
if [ "$(uci -q get nikki.config.n1_initialized || true)" != '1' ]; then
    api_secret=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    auth_secret=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    [ "${#api_secret}" = 48 ] && [ "${#auth_secret}" = 48 ]
    uci set "nikki.mixin.api_secret=$api_secret"
    uci set "nikki.@authentication[0].password=$auth_secret"
fi

# Official first rule bypasses persistent system users as well as services.
# A standalone cgroup-only rule would match everything when Lucky is absent.
bypass='nikki.@router_access_control[0]'
[ "$(uci get "$bypass.dns")" = '0' ]
[ "$(uci get "$bypass.proxy")" = '0' ]
[ -n "$(uci get "$bypass.user")" ]
uci -q del_list "$bypass.cgroup=services/lucky" || true
uci add_list "$bypass.cgroup=services/lucky"
uci set nikki.config.n1_initialized='1'
uci commit nikki
chmod 0600 /etc/config/nikki
/etc/init.d/nikki stop || true
/etc/init.d/nikki enable
logger -t n1-defaults 'Nikki profile selected; enter private subscriptions before enabling. IPv6 and Lucky direct path preserved.'
exit 0
