#!/bin/sh
# Install subs-check on first boot for Phicomm N1.
# The service runs as nobody (UID/GID 65534), which Nikki bypasses.
set -u
LOG=/etc/config/subs-check-install.log
BIN=/opt/subs-check/subs-check
DATA=/opt/subs-check/data
URL=https://github.com/beck-8/subs-check/releases/download/v1.4.9/subs-check_Linux_aarch64.tar.gz
mkdir -p /opt/subs-check "$DATA"
if [ ! -x "$BIN" ]; then
  TMP=/tmp/subs-check.tar.gz
  if command -v curl >/dev/null 2>&1; then curl -fsSL --noproxy '*' "$URL" -o "$TMP"; else wget -O "$TMP" "$URL"; fi
  tar -xzf "$TMP" -C /opt/subs-check
  chmod 755 "$BIN"
  rm -f "$TMP"
fi
[ -f "$DATA/config.yaml" ] || cat > "$DATA/config.yaml" <<'YAML'
api-key: "subscheck-8199"
check-interval: 1440
enable-speedtest: true
proxy: ""
sub-store-port: ""
sub-urls-remote: []
# 构建时不写入订阅地址，刷机后编辑 /opt/subs-check/data/config.yaml 手动添加
sub-urls: []
YAML
cat > /etc/init.d/subs-check <<'INIT'
#!/bin/sh /etc/rc.common
START=98
STOP=15
USE_PROCD=1
PROG=/opt/subs-check/subs-check
CONF=/opt/subs-check/data/config.yaml
start_service() {
 [ -x "$PROG" ] || return 1
 mkdir -p /opt/subs-check/data
 chown -R nobody:nogroup /opt/subs-check/data
 procd_open_instance
 procd_set_param command "$PROG" -f "$CONF"
 procd_set_param user nobody
 procd_set_param group nogroup
 procd_set_param env HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy=
 procd_set_param env HOME=/opt/subs-check/data
 procd_set_param stdout 1
 procd_set_param stderr 1
 procd_set_param respawn 3600 5 5
 procd_close_instance
}
INIT
chmod 755 /etc/init.d/subs-check
/etc/init.d/subs-check enable
/etc/init.d/subs-check start
printf 'installed at %s\n' "$(date)" >> "$LOG"
exit 0
