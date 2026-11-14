## ImmortalWrt for 斐讯N1
#### 固件版本以工作流选择和最终 BUILD-INFO / 包清单为准；ImageBuilder 默认 24.10.6；btrfs 镜像支持快照
#### 后台地址 `192.168.2.254`（旁路由模式）
#### 用户名 `root` 密码：password
#### 是否带docker: 根据用户选择
#### 默认软件包大小 1GB
#### Nikki：默认安装官方 v1.26.2 + Mihomo Meta v1.19.32；Nikki 代理默认关闭，填入私有订阅后再启用
#### 内核版本:根据用户选择
#### 晶晨宝盒：✅ 自带 用于写入emmc （这一步等以后稳定再考虑写入 非必要不写入 其实用U盘很自由）
#### rootfs.tar.gz 构建采用ImmortalWrt的ImageBuilder
#### 打包img 采用`onhub/amlogic-s9xxx-openwrt` 或 `flippy-openwrt-actions`
#### 默认底包位置：https://github.com/wukongdaily/AutoBuildImmortalWrt/releases/tag/rootfs


### Nikki 初始设置
刷机后在 LuCI → Nikki → 配置文件，编辑 `nikki-dual.yaml` 的 `proxy-providers.p1.url` 与 `p2.url`：**将各字段的整个值（包括占位的 `https://`）替换成完整私有订阅 URL**，保持 YAML 字符串正确转义。模板有 16 个策略组、40 条规则，包含其他地区和漏网之鱼；保留真机 DNS、筛选和策略，未加入重复节点过滤。

模板自带订阅占位符，故首启 `nikki.config.enabled=0`；透明代理参数已预置 `nikki.proxy.enabled=1`。填完两条订阅并通过配置检测后，在 Nikki 应用页启用服务即可。切换为 OpenClash 时，先停用 Nikki，再启用 OpenClash。`include_openclash=yes` 默认保留 OpenClash 安装和独立核心，但首启停用；选 `no` 时省略它。PassWall、MosDNS 仍可保留安装，首启停用。

官方包路径：Nikki 使用 `mihomo-meta` 的 `/usr/libexec/mihomo`，`/usr/bin/mihomo` 由官方 alternatives 管理；OpenClash 独立核心为 `/etc/openclash/core/clash_meta`。版本锁定见 `inputs.lock.json`，当前官方 Nikki bundle v1.26.2 携带 Mihomo Meta v1.19.32；与真机临时替换的上游稳定版 v1.19.34 是两条发布渠道。

`zzz-n1-nikki.sh` 在官方初始化后运行，保持每日重启关闭、双栈 DNS 劫持、IPv6 代理和 Lucky cgroup 直连例外；生成独立 API/代理认证密钥，面板仅绑定 `192.168.2.254:9090`。Lucky 应先启动，再启用 Nikki，确认其 cgroup 例外出现在实际 nft 规则中。修改 LAN 地址后同步修改 API 绑定地址。

### 斐讯N1为单网口旁路由模式：默认IP `192.168.2.254`，主路由/网关/DNS 为 `192.168.2.1`，已关闭N1自身DHCP<br> 已启用LAN侧IPv6客户端（RA/DHCPv6），并将 `br-lan` + `docker0` 直接加入 `lan` 防火墙区域，容器与LAN双向直通<br> 接入同网段后访问 `http://192.168.2.254`
### IPv6 / DNS / Lucky
- `lan6` 通过 DHCPv6/SLAAC 动态获取 IPv6；`reqprefix=auto` 表示请求 PD，`ipv6-prefix` 为空表示上游仅提供地址，不能称为获得独立委派前缀。
- N1 仅作同网段客户端，关闭自身 DHCPv4、RA、DHCPv6 和 NDP 服务；保留主路由的 IPv6 通告。
- `peerdns=0` 仅忽略上游下发的 DNS 地址，IPv6 地址/默认路由照常获取。N1 的 dnsmasq 明确使用主路由 IPv4 DNS `192.168.2.1` 作启动解析，主路由的 DNS 上游须避免再指回 N1，防止环路。
- 终端 IPv4 网关/DNS 可由主路由下发 N1 地址；终端 IPv6 默认路由和 RDNSS 由主路由决定。同一二层中直接到主路由的 IPv6 DNS，**即使 Nikki 开启 IPv6 劫持，也未必经过 N1**，应在终端侧单独验收。
- Lucky 使用本机动态公网 IPv6，CF DDNS 跟随有效地址更新 AAAA；不写死运营商前缀，也不内置域名、CF token 或穿透端口规则。

### 构建与验收
详见 [BUILD-CHANGES.md](BUILD-CHANGES.md)。固定 Nikki/OpenClash/subs-check 资产和 SHA-256；Nikki 原始 Packages 签名及所有包哈希都要通过校验。其余系统包源、可选 Store、打包 action/内核等仍有浮动输入，构建记录实际解析结果与清单，不宣称完全可复现。选择 `skip_imagebuilder=true` 会直接使用旧预构建底包，以上定制步骤会跳过。

### 若后续想设置其他ip或者旁路 请在web页面自行设置即可 <br> 总之 这个逻辑就是默认让它有网 和 普通电脑、NAS 无异
### 一定要阅读清楚 再刷机 推荐使用U盘做测试（0风险） 不建议一开始就写入EMMC
## 各位尽量不要直接使用项目中的release 要自己fork项目后自行构建  <br> 本项目中的release仅用于作者测试 且会定期删除
##### 若release中下载吃力 可在国内加速站下载 
[![Github](https://img.shields.io/badge/Release文件可在国内加速站下载-FC7C0D?logo=github&logoColor=fff&labelColor=000&style=for-the-badge)](https://wkdaily.cpolar.top/archives/1) 
