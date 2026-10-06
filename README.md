# CZU 校园网自动认证助手

**Mac M 系列 · Windows x64｜自动识别场景｜后台重连｜实时倒计时**

面向本校公共区域和宿舍网络的个人桌面工具。识别学校已有的 Dr.COM 认证门户，在需要认证时按页面实际协议提交账号密码；不是绕过认证，也不是通用的跨学校破解工具。

当前版本：**v0.3.6**。软件包由 GitHub Actions 的两套原生环境构建：Mac **M 系列（Apple Silicon）**和 Windows **x64**，不提供 Intel Mac 版或安卓 APK。

[下载与版本发布](https://github.com/Mike666wq/CZU-Network-connect/releases) · [构建状态](https://github.com/Mike666wq/CZU-Network-connect/actions) · [资源占用报告](docs/RESOURCE_USAGE.md) · [发布指南](docs/RELEASING.md)

## 功能

- **场景自动识别**：先只读检查公共门户，无法识别时继续检查宿舍门户；不向两个入口试密码。
- **宿舍运营商**：校园网、中国移动、中国联通、中国电信，首次选择保存，以后自动使用。
- **共用或独立凭据**：账号密码可共用；入口、运营商及协议参数按场景分别保存和使用。
- **自动重连**：启动、网络变化、休眠唤醒及定时检查；已联网不重复提交登录。
- **午夜恢复**：北京时间 23:58–00:15 进入恢复窗口；前段每 60 秒检查，00:08 后每 30 秒检查，恢复后回到低频心跳。
- **过程可见**：左右布局、五步流程、状态动画、实际入口、运行记录及每秒更新的下次检查倒计时。
- **菜单栏／系统托盘**：关闭窗口后后台运行；可选登录系统后启动。
- **资源优化**：请求工作进程短生命周期，隐藏窗口暂停纯界面计时器；日志与展示记录有上限。

## 下载和使用

打开 [Releases](https://github.com/Mike666wq/CZU-Network-connect/releases)，选择符合设备的软件包。若尚无公开版本，可查看 Actions 构建状态；Release 草稿只有仓库管理员可见。

| 文件名 | 用途 |
|---|---|
| `campus-network-assistant-v版本-macos-arm64.zip` | **Mac M 系列版**，内含 `.app` |
| `campus-network-assistant-v版本-windows-x64.zip` | **Windows 便携版**，内含 `.exe` 和完整依赖目录 |
| `campus-network-assistant-v版本-source.zip` | 开发源码，不是可执行应用 |
| `SHA256SUMS-all.txt` | 两端应用包、源码包及构建说明的校验值 |
| `build-info.json` / `macos-build-info.json` | 依赖版本与构建／冒烟验证信息 |

### Mac M 系列

完整解压后，将“校园网助手.app”放入 Applications 并打开。Mac 包使用本地 ad-hoc 签名，**没有 Apple Developer ID 签名／公证**；首次打开可能出现来源提示。请先核实仓库来源、校验值，再按系统的隐私与安全提示操作，不建议关闭全局系统安全保护。

### Windows

将 ZIP **完整解压**到固定目录，再运行“校园网助手.exe”。必须保留 `_internal` 和 `http-worker` 目录，不能只复制 `.exe`。最终使用者无需安装 Python。

Windows 包**未使用 Authenticode 签名证书**，可能提示未知发布者。请确认来源并核对校验值，不关闭系统防护。升级前在旧程序中点击“退出”，再更换目录；启用开机启动后，不要随意移动应用目录。

### 首次配置

1. “认证场景”选择 **自动识别**；等待识别后，右侧表单自动切换到对应场景。
2. 输入账号密码。若两个场景一致，使用“两场景共用账号与密码”。
3. 在宿舍表单选择账号所属服务商，点击 **保存配置**。运营商不能仅凭所在网络推断，需要首次明确选择。
4. 保持“自动检查并认证”启用且已保存。已有网络时会显示本轮未提交登录，属于正常情况。
5. 关闭窗口后继续后台运行；点击“退出助手”才停止。登录系统后自动启动默认关闭，需要自行勾选并保存。

顶部“当前认证入口”表示实际识别目标，右侧“配置入口”是可编辑草稿，仅保存后生效。不要把公共网配置地址直接改为宿舍地址；手动编辑另一个场景仅暂时关闭表单跟随，不自动改变认证目标。

## 核心行为

| 状态 | 调度 |
|---|---|
| 稳定联网 | 每 600 秒（10 分钟）探测 |
| 通常时间断网 | 30 → 60 → 120 → 300 秒退避 |
| 北京时间 23:58–00:08 | 每 60 秒检查／重试 |
| 北京时间 00:08–00:15 | 每 30 秒检查／重试 |
| 23:58、00:00、00:08 | 恢复窗口边界强制检查 |
| 临时服务故障 | 按离线退避继续重试 |
| 未知失败连续三次 | 退避为 300 秒 |
| 明确账号、欠费、停用或配置问题 | 不重复提交认证；白天每 10 分钟只做联网检查，午夜窗口按恢复节奏检查 |

公共入口 `192.168.255.4`、宿舍入口 `172.19.0.1`。自动识别按“公共 → 宿舍”顺序，首个能确认的门户确定场景。两者都无法识别时显示未识别到校园网；这也可能由临时不可达造成，不能据此断言设备肯定不在校园。

只读查在线状态 → 明确未认证时验证配置和终端参数 → 提交认证 → 再次检查互联网。不将门户能打开、HTTP 请求成功或接口报告成功单独当作已经联网。配置缺失显示“需要检查配置”，不会误报成服务器拒绝。

倒计时直接读取真实调度期限，包括更早的午夜恢复边界，不会独立发起请求。后台使用单次 deadline 定时器直接睡到下一次检查；系统网络变化事件可提前触发，另以 60 秒接口签名轮询作为漏报兜底，不再每 5 秒轮询调度状态。

**机器必须开机、保持唤醒，应用运行且未暂停。** 它不会在睡眠／关机期间执行，不能替代连接 Wi-Fi、插入网线或修复学校服务故障。窗口隐藏只停界面刷新，后台调度继续运行。

## 安全和隐私

- 密码明文保存在本机用户目录 `校园网助手/config.json`，注意本机账户保护，不要上传或分享该文件。
- 门户使用学校现有的 **HTTP GET** 认证接口，不是加密凭据传输。公网探测使用 HTTPS 并校验预期响应。
- 探测和门户请求绕过系统 HTTP 代理，不修改代理、VPN、网卡或已有连接；VPN 路由仍可能影响实际访问。
- 请求有总时限：公网 4 秒、门户 10 秒。超时／暂停／切网后终止旧工作进程，不并发重试提交。
- 密码经私有 stdin 传给短生命周期工作程序，不出现在进程命令行、日志或公开构建数据中。
- `events.jsonl` 仅记录版本、北京时间、触发原因、场景、结果及是否尝试认证，约 1 MB 轮转；界面历史最近 160 条。不记录账号、密码、令牌、登录 URL 或服务端原文。
- 公共软件包与源码包不带本机配置、个人日志、缓存或真实门户采集文件。

## 验证情况与边界

- macOS 公共网和宿舍网均已有用户截图显示本轮认证成功且公网探测通过。
- 离线测试覆盖场景选择、服务商、配置重载、错误凭据、超时／取消、Qt 后台线程、倒计时、切网及跨午夜模拟恢复。
- 云端 Release 构建须先通过回归测试，再验证**打包后**程序的回环 HTTP、界面跟随和后台计时器；冒烟测试不读取个人配置、不访问校园门户，不代表现场网络和整夜使用已通过。
- Windows 本次版本及两端午夜真实恢复、托盘交互、开机启动仍应在设备上现场验证。
- 资源测量在 Mac M1、8 GB 环境进行；优化版本后台 footprint 约 74 MiB，RSS 是另一个口径。短时测试并非内存上限或长期零泄漏保证，不能用 Mac 数值代替 Windows 数值。完整数据见 [报告](docs/RESOURCE_USAGE.md)。
- 不支持验证码、短信登录、任意学校或运营商猜测。安卓如需实现，需要另行开发移动端和后台运行机制，不属于当前版本。

## 开发和本地验证

源码开发支持 Python 3.10+；**Release 构建统一 Python 3.12**，直接依赖固定在 `requirements-release.txt`。Windows 依赖入口 `requirements-windows.txt` 引用同一文件。

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-release.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python main.py
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install --index-url https://pypi.org/simple -r requirements-release.txt
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
.\.venv\Scripts\python.exe main.py
```

可选本机构建：Mac M 系列运行 `./build.sh`；Windows x64 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1`。脚本纯 ASCII；固定 Python 3.12，默认官方 HTTPS PyPI，不关闭 TLS 校验。受管理设备应遵循其执行策略。

两个平台的请求程序均单独以标准输入输出可用的控制台模式打包，主界面始终是窗口应用。Windows 由 GUI 以 `CREATE_NO_WINDOW` 启动，不弹终端窗口；Mac 工作程序在 `.app` 内直接启动，不打开 Terminal。这样避免无控制台 GUI 的 stdin/stdout 环境差异。

## GitHub 自动构建和 Release

工作流：[`.github/workflows/release.yml`](.github/workflows/release.yml)。

- 推送 `main`、提交 PR 或手动触发：在 **macos-15 arm64** 和 **windows-2022 x64** 原生 runner 完成测试、打包、冒烟验证，提供 Actions Artifacts。
- 推送 `vX.Y.Z` 标签：标签必须匹配源码版本。两个平台均成功后由云端整理目录、验证原始校验值及打包测试，自动上传并公开发布 Release，包含两个应用包、源码包、构建信息和校验值。
- 上传完成前使用草稿保护不完整附件，全部成功后自动公开。不会自动覆盖已公开的 Release。
- 不在本机跨系统伪造 Windows 应用，也不提供 Intel Mac 构建。

手动一条命令也可触发完整云端构建和发布，不需要本地下载／上传：

```sh
gh workflow run release.yml --repo Mike666wq/CZU-Network-connect --ref main -f publish=true
```

该模式在两个平台验证后自动给本次测试的源码提交创建版本标签；已存在标签指向不同提交或 Release 已公开时停止，不改写历史。详细步骤见 [发布指南](docs/RELEASING.md)。

## 目录

```text
main.py                          轻量入口
http_worker.py                   Windows 工作程序入口
campus_assistant/gui.py          桌面窗口与后台任务桥接
campus_assistant/dashboard.py    状态、动画、流程和倒计时展示
campus_assistant/service.py      门户识别及公共／宿舍适配
campus_assistant/protocol.py     HTTP、JSONP和请求进程边界
campus_assistant/engine.py       认证状态机
campus_assistant/scheduler.py    心跳／午夜／唤醒调度
tests/                          离线回归测试
tools/                          打包、校验、资源测量工具
docs/                           性能报告和发布指南
```

## 许可

目前**尚未指定项目开源许可证**，公开仓库并不自动授予开源许可。公开二进制前应确认项目许可和 Python、Qt/PySide6、PyInstaller 等第三方依赖的分发要求，不将“无需安装 Python”等同于“无需处理第三方许可”。请在最终公开发布前补齐许可与所需声明。
