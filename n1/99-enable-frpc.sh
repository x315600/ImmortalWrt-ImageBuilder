#!/bin/sh
# Enable frpc service on first boot
LOGFILE="/etc/config/uci-defaults-log.txt"
echo "Enabling frpc service at $(date)" >> "$LOGFILE"

# Enable frpc daemon
uci set frpc.config.enabled='1'
uci set frpc.config.server_addr='38.14.'
uci set frpc.config.server_port='7000'
uci set frpc.config.token='315600'
uci commit frpc

# Start frpc
/etc/init.d/frpc enable
/etc/init.d/frpc start

echo "frpc enabled and started" >> "$LOGFILE"
exit 0
