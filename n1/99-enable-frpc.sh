#!/bin/sh
# Enable frpc service on first boot. Configuration is provided by /etc/config/frpc.

LOGFILE="/etc/config/uci-defaults-log.txt"
echo "Enabling frpc service at $(date)" >> "$LOGFILE"

# Ensure core server settings are correct even if package defaults changed.
uci set frpc.common.server_addr='38.14.254.183'
uci set frpc.common.server_port='7000'
uci set frpc.common.token='315600'

# Ensure LuCI HTTP tunnel and SSH tunnel exist and are correct.
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

/etc/init.d/frpc enable
/etc/init.d/frpc restart

echo "frpc enabled: server=38.14.254.183:7000 http=ys.315600.xyz ssh=38.14.254.183:2222" >> "$LOGFILE"
exit 0
