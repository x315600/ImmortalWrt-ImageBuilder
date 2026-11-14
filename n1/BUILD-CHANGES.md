# N1 ImageBuilder 改造与验收

基线：`060b236f36f6820fc08ffbbc629bccc4fbfe3aa6`。本次修改构建代码和公开默认模板；没有推送远程、触发 GitHub Actions、刷写镜像或再改真机。

## 用户选定项目

| 项 | 实现 |
|---|---|
| 1 | `include_openclash=yes/no`，默认 yes 保留安装。OpenClash、PassWall、MosDNS 首启停用；Lucky 保留。Nikki 填写订阅前关闭核心服务，透明代理参数预置开启。 |
| 2 | Nikki v1.26.2 官方 bundle，校验 archive SHA-256、usign Ed25519 签名、Packages/Packages.gz 一致性和每个 IPK。选择 `nikki 2026.10.10-r1`、`luci-app-nikki 1.26.2-r1`、`mihomo-meta 1.19.32`。OpenClash 0.48.002 使用独立官方 Mihomo 1.19.32 文件。 |
| 3 | 三个自定义首启脚本统一 0755；最后的 `zzz-n1-nikki.sh` 排在官方初始化之后，幂等、安装阶段保留、错误后可重试。 |
| 4 | `lan6.peerdns=0`、DHCPv6/SLAAC 动态获取；移除旧静态公网地址。dnsmasq 明确使用主路由 IPv4 DNS 作启动解析；N1 停用 DHCP/RA/DHCPv6/NDP 服务。 |
| 5 | 文档分别说明动态地址与 PD；`reqprefix=auto` 不代表已获 PD。主路由下发的终端 IPv6 DNS 必须按实际路径验收，N1 劫持无法处理未流经自己的流量。 |
| 7 | N1 首启移除固定 FRP 地址、token 和映射；N1 专用 `frpc.config` 无凭据，构建挂载该文件而非共享旧模板。FRPC 默认停用。 |
| 9 | 核心、Nikki、公钥、OpenClash、subs-check 锁版本及 SHA-256；Store 锁 commit。构建记录 Docker image ID、包源索引、IPK/overlay 哈希并校验缓存包；冻结本轮索引，安装后检查实际版本与核心文件来源。 |
| 10 | 最终自动输出 `BUILD-INFO.md`、`installed-packages.txt`、`SHA256SUMS`、`n1-build-audit.tar.gz`；Release 正文结合实际版本生成。预构建跳过路径明确标记定制未应用。 |

第 6 项防火墙区域重构和第 8 项 subs-check 认证/监听改造未纳入本次范围。共享其他平台的默认文件保持原样；FRP 脱敏覆盖的是本次 N1 打包链路。已有公开凭据的历史提交不会因这次模板修改消失。

## 真机模板与脱敏

`n1/nikki-dual.yaml` 来源于本次真机配置，保留 16 个策略组、40 条规则、176 条 Fake-IP 规则及 21 个规则提供商；其他地区和漏网之鱼都保留。p2 已撤回的去重过滤没有重新加入。

与读取的真机 YAML 做结构对比，仅四处差异：
1. p1 URL 替换成占位符。
2. p2 URL 替换成占位符。
3. 移除管理接口 secret。
4. 模板控制接口收敛为回环地址；Nikki 首启混入时绑定 N1 LAN IPv4 并生成独立认证。

没有把节点缓存、节点连接凭据、CF token、Lucky 域名/路径或路由器密码打入公开模板。公共分流列表中的域名是策略内容，不是订阅凭据；保留了原有命名风格与策略偏好。

占位订阅不具备出站能力。填写每个 `url` 字段的**完整值**后再启用 Nikki。规则文件与 Geo 数据的首次无缓存下载需要网络，配置语法测试并不证明首次联网下载成功。

## 版本渠道说明

真机此前临时替换为上游 Mihomo v1.19.34。本次构建使用的是 Nikki v1.26.2 官方签名 bundle 所附 `mihomo-meta 1.19.32`，不是把裸二进制冒充成官方包，也不会拿 OpenClash 路径覆盖 Nikki 的 `/usr/libexec/mihomo`。

## 权限判断更正

OpenWrt `uci-defaults` 以 source 方式执行，0644 本身不是不执行的证据。统一 0755 便于管理；真正修复的是：文件安装路径、脚本顺序、失败返回码、重复运行与位于 `exit 0` 后的不可达初始化。

## 本地测试

依赖：Python 3.10+、PyYAML、cryptography、ripgrep、ShellCheck、Bash。锁定下载缓存由 `inputs.lock.json` 定义。

```sh
python3 n1/prepare-inputs.py --cache .build/downloads --output .build/n1-inputs --files .build/test-files --include-openclash yes
NIKKI_OFFICIAL_ROOT="$PWD/.build/n1-inputs/official-root" python3 -B n1/tests/test_firstboot.py
N1_TEST_CACHE="$PWD/.build/downloads" python3 -B n1/tests/test_build_inputs.py
shellcheck -S warning n1/build.sh n1/99-n1-bypass-router.sh n1/99-install-subs-check.sh n1/zzz-n1-nikki.sh
git diff --check
```

本地实际结果：首启/模板隔离测试 15/15；构建输入与产物审计 11/11；官方 Mihomo 1.19.32 `-t` 通过；ShellCheck、shell 语法和 YAML 检查通过。构建测试中的 rootfs/img 是明确标记的合成夹具，核心载荷来自真实官方 IPK；没有冒充实际编译镜像。

## 完整镜像验收仍需执行

当前 Android Linux 沙箱没有 Docker daemon，本轮没有执行 amd64 ImageBuilder 容器或完整 ARM 镜像打包。下一次 CI 应确认：
- 固定包能与所选 ImmortalWrt 包源依赖共同安装。
- `after-manifest.json` 核验官方核心和独立 OpenClash 文件通过。
- 首启后官方 alternatives 指向 `/usr/libexec/mihomo`，三方代理保持停用。
- 填订阅、启动 Lucky，再启用 Nikki，核验运行配置和 nft cgroup 例外。
- LAN 终端 DNS、IPv6 出站和 Lucky 真实业务域名分别实测。

包源依赖及打包 action/内核/预构建底包尚有浮动输入；已记录并在单次构建内冻结可检查的包索引，但不宣称不同日期完全逐字节复现。详细范围见 `inputs.lock.json.reproducibility_gaps`。
