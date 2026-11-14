#!/bin/bash
set -eo pipefail
cd /home/build/immortalwrt
CUSTOM_PACKAGES="${CUSTOM_PACKAGES:-}"
INCLUDE_OPENCLASH="${INCLUDE_OPENCLASH:-yes}"
ENABLE_STORE="${ENABLE_STORE:-true}"
export INCLUDE_OPENCLASH ENABLE_STORE
# Log file for debugging
source shell/custom-packages.sh
source shell/switch_repository.sh
echo "第三方软件包: $CUSTOM_PACKAGES"
LOGFILE="/tmp/uci-defaults-log.txt"
echo "Starting 99-custom.sh at $(date)" >> $LOGFILE
# yml 传入的路由器型号 PROFILE
echo "Building for profile: $PROFILE"
# yml 传入的固件大小 ROOTFS_PARTSIZE
echo "Building for ROOTFS_PARTSIZE: $ROOTFS_PARTSIZE"
# 输出调试信息
echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始构建arm64的rootfs.tar.gz"
# 定义所需安装的包列表 下列插件你都可以自行删减
PACKAGES=""
PACKAGES="$PACKAGES curl fdisk"
PACKAGES="$PACKAGES luci-i18n-diskman-zh-cn"
PACKAGES="$PACKAGES luci-i18n-package-manager-zh-cn"
PACKAGES="$PACKAGES luci-i18n-firewall-zh-cn"
# 服务——FileBrowser 用户名admin 密码admin
PACKAGES="$PACKAGES luci-i18n-filebrowser-go-zh-cn"
PACKAGES="$PACKAGES luci-i18n-filemanager-zh-cn"
PACKAGES="$PACKAGES luci-theme-argon"
PACKAGES="$PACKAGES luci-app-argon-config"
PACKAGES="$PACKAGES luci-i18n-argon-config-zh-cn"
PACKAGES="$PACKAGES luci-i18n-ttyd-zh-cn"
PACKAGES="$PACKAGES openssh-sftp-server"
# 判断是否需要编译 Docker 插件
if [ "$INCLUDE_DOCKER" = "yes" ]; then
    PACKAGES="$PACKAGES luci-i18n-dockerman-zh-cn"
    echo "✅ 已选择docker : luci-i18n-dockerman-zh-cn"
fi
# 斐讯N1 无线
PACKAGES="$PACKAGES kmod-brcmfmac wpad-basic-mbedtls iw iwinfo"
PACKAGES="$PACKAGES perlbase-base perlbase-file perlbase-time perlbase-utf8 perlbase-xsloader"
# 晶晨宝盒（追加第三方必备软件 用于写入emmc 请不要注释）
CUSTOM_PACKAGES="$CUSTOM_PACKAGES luci-app-amlogic luci-i18n-amlogic-zh-cn"

# N1 自定义插件
# Keep all original plugins; only first-boot scripts control service enablement.
# PassWall and MosDNS remain installed but are disabled by N1 first-boot defaults.
CUSTOM_PACKAGES="$CUSTOM_PACKAGES geoview xray-core sing-box hysteria luci-i18n-passwall-zh-cn"
CUSTOM_PACKAGES="$CUSTOM_PACKAGES luci-app-mosdns luci-i18n-mosdns-zh-cn"
# OpenClash 0.48.002 + independent official Mihomo 1.19.32 file.
if [ "$INCLUDE_OPENCLASH" = "yes" ]; then
    CUSTOM_PACKAGES="$CUSTOM_PACKAGES luci-app-openclash luci-compat kmod-tun kmod-inet-diag kmod-nft-tproxy bash curl ip-full unzip"
fi
# Lucky
CUSTOM_PACKAGES="$CUSTOM_PACKAGES luci-app-lucky lucky"
# Frp client
CUSTOM_PACKAGES="$CUSTOM_PACKAGES frpc luci-i18n-frpc-zh-cn"
# Nikki
CUSTOM_PACKAGES="$CUSTOM_PACKAGES nikki luci-app-nikki luci-i18n-nikki-zh-cn"
# Bandix 流量监控
CUSTOM_PACKAGES="$CUSTOM_PACKAGES luci-app-bandix luci-i18n-bandix-zh-cn"
# OpenList WebDAV
CUSTOM_PACKAGES="$CUSTOM_PACKAGES openlist luci-i18n-openlist-zh-cn"

mkdir -p bin/n1-audit
# This package repository supplies PassWall/MosDNS/Lucky/Bandix/Amlogic too.
# Disabling the Store UI must not silently remove these original plugins.
STORE_COMMIT=$(python3 -c 'import json; print(json.load(open("n1/inputs.lock.json"))["store"]["commit"])')
git init /tmp/store-run-repo
git -C /tmp/store-run-repo remote add origin https://github.com/wukongdaily/store.git
git -C /tmp/store-run-repo fetch --depth=1 origin "$STORE_COMMIT"
git -C /tmp/store-run-repo checkout --detach FETCH_HEAD
test "$(git -C /tmp/store-run-repo rev-parse HEAD)" = "$STORE_COMMIT"
printf '%s\n' "$STORE_COMMIT" > bin/n1-audit/store-commit.txt
mkdir -p extra-packages
cp -r /tmp/store-run-repo/run/arm64/. extra-packages/
python3 n1/build-audit.py before
sh shell/prepare-packages.sh
# Only install verified official IPKs through ImageBuilder's local packages/.
# make image -> package_reload -> package_index builds/signs this local index
# and invokes its own target-root opkg. Never run the Ubuntu host's opkg.
python3 n1/configure-builder.py
PACKAGES="$PACKAGES $CUSTOM_PACKAGES mihomo-meta"
if [ "$INCLUDE_OPENCLASH" != "yes" ]; then
    PACKAGES="$PACKAGES -luci-app-openclash"
fi
# Pass explicit IPK paths first: opkg's local-file install pins provenance,
# unlike a bare package name which can resolve to a newer remote feed.
FILTERED_PACKAGES=""
for package in $PACKAGES; do
    case "$package" in
        nikki|luci-app-nikki|luci-i18n-nikki-zh-cn|mihomo-meta|mihomo-alpha|luci-app-openclash) ;;
        *) FILTERED_PACKAGES="$FILTERED_PACKAGES $package" ;;
    esac
done
PACKAGES="$(cat bin/n1-audit/pinned-package-paths.txt) $FILTERED_PACKAGES"
printf '%s\n' "$PACKAGES" > bin/n1-audit/requested-packages.txt
# Freeze this run's resolved indexes before installation. ImageBuilder owns
# target opkg/cache/key handling. Its image recipe clears MAKEFLAGS, so use
# a guarded target override, not make -o, to prevent a second feed refresh.
make -s _check_keys
make package_reload
python3 n1/build-audit.py before
python3 n1/freeze-feeds.py

# 构建镜像
echo "$(date '+%Y-%m-%d %H:%M:%S') - Building image with the following packages:"
echo "$PACKAGES"

make image PROFILE="$PROFILE" PACKAGES="$PACKAGES" FILES="/home/build/immortalwrt/files" ROOTFS_PARTSIZE="$ROOTFS_PARTSIZE"
python3 n1/build-audit.py after

echo "$(date '+%Y-%m-%d %H:%M:%S') - Build completed successfully."
