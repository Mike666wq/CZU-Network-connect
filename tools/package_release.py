"""Allowlisted source and verified Windows portable assets for local builds / GitHub Release."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import plistlib
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from campus_assistant import __version__

APP_NAME='校园网助手'
SOURCE_TOP=('main.py','http_worker.py','build.ps1','build.sh','pyproject.toml','requirements.txt',
            'requirements-dev.txt','requirements-windows.txt','requirements-release.txt','README.md','MAC_UI_PREVIEW.md',
            '.gitignore','.gitattributes')
SOURCE_DIRS=('campus_assistant','tests','tools','docs','.github')
PRIVATE_NAMES={'config.json','.env','.DS_Store','events.jsonl','events.previous.jsonl'}


def verify_tag(tag):
    expected='v'+__version__
    if tag != expected:
        raise ValueError(f'Tag {tag!r} must match project version {expected!r}')
    return expected


def allowed_source_files(root=ROOT):
    files=[]
    for name in SOURCE_TOP:
        path=root/name
        if path.is_file():files.append(path)
    for directory in SOURCE_DIRS:
        folder=root/directory
        if not folder.exists():continue
        for path in folder.rglob('*'):
            if not path.is_file() or path.is_symlink():continue
            relative=path.relative_to(root)
            if any(p.startswith('.') and p!='.github' or p in {'__pycache__','.cache'} for p in relative.parts):continue
            if path.name in PRIVATE_NAMES or path.name.startswith(('events.','.env','config.')) or path.suffix in {'.log','.pyc','.png','.key','.pem','.p12','.pfx'}:continue
            if path.suffix not in {'.py','.md','.txt','.json','.csv','.yml','.yaml','.spec'}:continue
            files.append(path)
    return sorted(set(files))


def source_zip(output: Path, root=ROOT):
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path in allowed_source_files(root):
            archive.write(path,'Networkconnect/'+path.relative_to(root).as_posix())
    verify_zip(output)
    return output


def verify_zip(path):
    with ZipFile(path) as archive:
        if archive.testzip() is not None:raise ValueError('Corrupt ZIP')
        for name in archive.namelist():
            parts=Path(name).parts
            if '..' in parts or name.startswith('/') or any(part in {'__pycache__','.venv','.cache','.git'} for part in parts):
                raise ValueError('Unexpected private/generated archive entry')
            if Path(name).name in PRIVATE_NAMES or name.endswith('.log') or Path(name).name.startswith('events.'):
                raise ValueError('Private runtime data found in archive')


def verify_x64_pe(path):
    with path.open('rb') as handle:
        if handle.read(2)!=b'MZ':raise ValueError(f'{path.name} is not a Windows PE binary')
        handle.seek(0x3c);offset=struct.unpack('<I',handle.read(4))[0]
        handle.seek(offset)
        if handle.read(4)!=b'PE\0\0':raise ValueError('Missing PE signature')
        if struct.unpack('<H',handle.read(2))[0]!=0x8664:raise ValueError('Windows release must be x64')


def release_notes():
    return f'''# 校园网助手 v{__version__} · Mac M系列 / Windows x64

- 公共网／宿舍网自动识别，宿舍服务商独立保存，共用或独立账号密码。
- Scheduler 2.0：稳定在线约 10 分钟心跳；普通断网 30/60/120/300 秒退避；23:58–00:15 进入午夜恢复窗口。
- 系统网络变化可立即触发检查；主调度使用 single-shot deadline timer，60 秒接口签名轮询仅作为事件漏报兜底。
- UI 重构为“状态 / 设置 / 记录”三页结构：状态页聚焦连接结果、当前场景、五步流程、状态 Chip、最近活动与真实调度期限；技术 Portal 参数收进高级设置。
- 连接流程区分“已完成 / 未确认 / 无需执行 / 待处理 / 失败”，互联网已可用但校园场景未识别时不会误报为待处理；认证拒绝使用明确红色失败语义。
- 异常状态使用上下文操作：只有点击“完善配置 / 修改账号”时才跳到对应设置项；密码支持本地显示／隐藏，Mac Command+1/2/3、Windows Ctrl+1/2/3 可切换三页。
- 午夜 23:58–00:15 会在 Hero 和顶部状态直接显示恢复模式与当前 60/30 秒检查节奏。
- Mac 构建裁掉当前 Widgets UI 不使用的 QML/Quick/Pdf/VirtualKeyboard/Svg/OpenGL 功能链；独立 HTTP helper 仍保留请求超时、取消和隔离边界。
- 请求工作程序保留总超时、取消、TLS 校验、代理绕过和私有 stdin 凭据传输。

## 使用

Mac：下载macOS-arm64 ZIP，解压后将“校园网助手.app”移到Applications。仅支持M系列芯片，不提供Intel版。此版为本地ad-hoc签名，未做Apple公证；如系统提示来源问题，请在确认来源和校验值后按系统安全设置处理，不关闭全局安全防护。

下载Windows便携ZIP并完整解压，运行“校园网助手.exe”。请保留`http-worker`和`_internal`目录，不要只复制exe。无需安装Python。升级前先退出旧应用；用户配置在用户目录的“校园网助手”文件夹，默认不随应用包分发。

## 验证边界

构建流程执行离线回归和打包后的本机回环HTTP／GUI冒烟测试，不向校园门户提交认证。两端真实网络、托盘交互、登录系统后启动、睡眠唤醒和午夜恢复仍需现场验证。Mac性能数据不能代替Windows性能数据。本版未使用Windows代码签名证书，可能显示来源提示；请核对校验值，不建议关闭系统安全防护。

源码ZIP面向开发者，不是可执行应用。项目前尚未指定自己的开源许可证；正式公开前请确认项目及第三方依赖的分发许可。
'''


def windows_assets(app_dir: Path, output: Path, smoke: Path, build_metadata: Path):
    output.mkdir(parents=True,exist_ok=True)
    executable=app_dir/(APP_NAME+'.exe')
    worker=app_dir/'http-worker'/'campus-http-worker.exe'
    for path in (executable,worker):verify_x64_pe(path)
    if not (app_dir/'_internal').is_dir() or not (app_dir/'http-worker'/'_internal').is_dir():
        raise ValueError('Incomplete PyInstaller folder')
    smoke_data=json.loads(smoke.read_text(encoding='utf-8-sig'))
    if smoke_data.get('ok') is not True or smoke_data.get('version')!=__version__ or smoke_data.get('frozen') is not True or smoke_data.get('platform')!='Windows':
        raise ValueError('Native packaged Windows smoke test must pass before release packaging')
    report=json.loads(build_metadata.read_text(encoding='utf-8-sig'))
    if report.get('tests_passed') is not True or report.get('version')!=__version__ or report.get('platform')!='Windows':
        raise ValueError('Windows tests / build metadata missing')
    portable=output/f'campus-network-assistant-v{__version__}-windows-x64.zip'
    with ZipFile(portable,'w',ZIP_DEFLATED) as archive:
        for path in sorted(app_dir.rglob('*')):
            if path.is_file():
                if path.is_symlink():raise ValueError('Unexpected symlink in Windows app')
                archive.write(path,APP_NAME+'/'+path.relative_to(app_dir).as_posix())
        archive.writestr(APP_NAME+'/README-Windows.md',release_notes())
        archive.writestr(APP_NAME+'/BUILD-INFO.json',json.dumps(report,ensure_ascii=False,indent=2))
    verify_zip(portable)
    source=source_zip(output/f'campus-network-assistant-v{__version__}-source.zip')
    summary=output/'build-info.json'
    # Never copy raw smoke paths/process identifiers/credentials; only curated safe flags.
    report['smoke_test']={key:smoke_data.get(key) for key in ('ok','version','platform','frozen','loopback_requests','auth_requests','probe_verified','form_follow_verified','background_timer_verified','worker_name')}
    summary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    artifacts=[portable,source,summary]
    checksums=output/'SHA256SUMS.txt'
    checksums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts),encoding='ascii')
    (output/'release-notes.md').write_text(release_notes(),encoding='utf-8')
    return artifacts+[checksums]


def mac_assets(app: Path, output: Path, smoke: Path, build_metadata: Path):
    if sys.platform != 'darwin':
        raise ValueError('Mac assets must be produced on a native macOS runner')
    executable = app / 'Contents' / 'MacOS' / APP_NAME
    worker = app / 'Contents' / 'Helpers' / 'campus-http-worker.app' / 'Contents' / 'MacOS' / 'campus-http-worker'
    for binary in (executable, worker):
        architectures = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
        if architectures != ['arm64']:
            raise ValueError('Mac app and request helper must be Apple Silicon arm64 only')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    with (app/'Contents/Info.plist').open('rb') as handle:
        plist = plistlib.load(handle)
    if plist.get('CFBundleShortVersionString') != __version__:
        raise ValueError('Mac bundle version must match project version')
    smoke_data=json.loads(smoke.read_text(encoding='utf-8-sig'))
    report=json.loads(build_metadata.read_text(encoding='utf-8-sig'))
    if not (smoke_data.get('ok') is True and smoke_data.get('frozen') is True
            and smoke_data.get('version') == __version__ and smoke_data.get('platform') == 'macOS'):
        raise ValueError('Native packaged Mac smoke test must pass')
    if not (report.get('tests_passed') is True and report.get('platform') == 'macOS'
            and report.get('version') == __version__ and report.get('architecture') == 'arm64'):
        raise ValueError('Missing tested Mac arm64 build metadata')
    output.mkdir(parents=True, exist_ok=True)
    archive=output/f'campus-network-assistant-v{__version__}-macos-arm64.zip'
    # ditto preserves executable modes and bundle symlinks; ZIP format is Release-friendly.
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
    verify_zip(archive)
    summary=output/'macos-build-info.json'
    report['smoke_test']={key:smoke_data.get(key) for key in ('ok','version','platform','frozen','loopback_requests','auth_requests','probe_verified','form_follow_verified','background_timer_verified','worker_name')}
    summary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    checksum=output/'SHA256SUMS-macos.txt'
    checksum.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n' for path in (archive,summary)),encoding='ascii')
    return [archive,summary,checksum]


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    source=sub.add_parser('source');source.add_argument('--output',type=Path,required=True)
    tag=sub.add_parser('verify-tag');tag.add_argument('tag')
    win=sub.add_parser('windows');win.add_argument('--app-dir',type=Path,required=True)
    win.add_argument('--output',type=Path,required=True);win.add_argument('--smoke-report',type=Path,required=True)
    win.add_argument('--build-metadata',type=Path,required=True)
    mac=sub.add_parser('macos');mac.add_argument('--app',type=Path,required=True)
    mac.add_argument('--output',type=Path,required=True);mac.add_argument('--smoke-report',type=Path,required=True)
    mac.add_argument('--build-metadata',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='source':print(source_zip(args.output))
    elif args.command=='verify-tag':print(verify_tag(args.tag))
    elif args.command=='macos':
        for path in mac_assets(args.app,args.output,args.smoke_report,args.build_metadata):print(path)
    else:
        for path in windows_assets(args.app_dir,args.output,args.smoke_report,args.build_metadata):print(path)
