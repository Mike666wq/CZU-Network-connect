# GitHub 构建和发布

目标：Mac **M 系列（arm64）**和 Windows **x64**。不包含 Intel Mac 或安卓。

## 流程

1. 修改版本时同步 `campus_assistant/__init__.py` 与 `pyproject.toml`。
2. 提交到 `main`。GitHub Actions 对两个原生平台安装固定依赖、执行回归、构建原生应用，再执行不访问校园门户的打包冒烟测试。
3. 查看 Actions 验证报告与 Artifacts；测试失败时不会生成 Release。
4. 确认版本后推送相同版本的标签，例如：

```sh
git tag -a v0.3.5 -m "Campus Network Assistant v0.3.5"
git push origin v0.3.5
```

5. 标签触发两个平台构建，全部成功后由云端验证原始哈希、上传全部附件，再自动公开 Release。上传完成前保留草稿，失败不会公开不完整版本。

也可一条命令完整重建并发布当前main版本（不需要本地打包或下载产物）：

```sh
gh workflow run release.yml --repo Mike666wq/CZU-Network-connect --ref main -f publish=true
```

这个模式在测试完成后给本次构建的准确源码提交创建版本标签；已存在标签必须指向同一提交，否则停止，不覆盖。

不要随意删除／移动已发布版本标签。修正一个已经公开的版本时应升版本并推送新标签，不用 `--force` 覆盖历史。

## 自动附件

- Windows 便携 ZIP，包含 GUI、`http-worker` 与完整依赖目录。
- Mac M 系列 ZIP，包含权限／符号链接保持完整的 `.app`。
- 源码 ZIP，按白名单收集，不包含个人配置、日志、真实门户采集数据、虚拟环境或构建缓存。
- `SHA256SUMS-all.txt`。
- Windows 与 Mac 构建元数据；包括依赖版本、离线测试状态、回环冒烟标记。

Release在上传过程中暂为草稿，全部附件上传成功后自动公开。未开启publish的主分支或手动构建只产生Actions Artifacts，不创建公开Release。

## 验证与发布门槛

- Windows PE检查必须是x64；Mac主程序必须是arm64，内置版本一致且本地签名完整性检查通过。
- 两端打包冒烟测试使用隔离配置和本机127.0.0.1服务器，不会读取真实账号密码或向校园提交登录。
- 冒烟覆盖生产HTTP进程、Qt信号、宿舍表单跟随、倒计时、隐藏窗口保留后台调度。
- 真机校园登录、托盘菜单、开机启动、睡眠唤醒和午夜恢复仍需现场验证；不能把CI绿灯当作学校环境实测。
- Windows无Authenticode签名；Mac仅ad-hoc签名，未公证。不要引导用户关闭全局系统保护。
- 本项目许可尚未指定。公开源码前已提示这一状态；公开二进制前需补齐项目与第三方许可／声明。

## 权限和供应链

默认`contents: read`，只有标签触发后的Release任务获得`contents: write`。官方Actions使用已核对的完整提交SHA固定版本。PR不会创建Release，不在仓库保存PAT／账号密码。Release任务校验ZIP哈希，不覆盖已公开Release。

## 本地可做什么

无需本机构建才能发布。推送和打标签后，由GitHub runner完成构建。可在本机运行离线测试并检查源码包内容；不要提交`dist/`、`.venv/`、`.cache/`、`config.json`或`events*.jsonl`。

## Artifact目录处理

Mac上传使用确定的版本目录，不再用通配符保留额外层级。Release下载保留各Artifact独立目录，并由prepare_release_assets.py查找原始manifest和同目录产物，验证后统一目录；原始哈希不匹配直接失败，不重新计算哈希掩盖损坏。操作全部在GitHub runner完成。
