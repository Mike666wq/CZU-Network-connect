from pathlib import Path
import importlib.util
import json
import struct
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from campus_assistant.platform_ui import platform_name, ui_font, background_text, startup_text
from campus_assistant.windows_startup import startup_command, set_startup
from campus_assistant.protocol import BoundedHttp, PortalError
from campus_assistant import __version__


def tool_module():
    spec=importlib.util.spec_from_file_location('package_release',Path('tools/package_release.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_windows_text_and_fonts_are_not_mac_labels():
    assert platform_name('win32')=='Windows'
    assert ui_font('win32')=='Microsoft YaHei UI'
    assert '系统托盘' in background_text('win32')
    assert startup_text('win32')=='登录 Windows 后启动'
    assert platform_name('darwin')=='macOS'
    assert '菜单栏' in background_text('darwin')


def test_windows_startup_command_is_quoted_without_redundant_script_in_frozen_app():
    command=startup_command(r'C:\Users\test\My App\校园网助手.exe',frozen=True)
    assert command==r'"C:\Users\test\My App\校园网助手.exe"'
    command=startup_command(r'C:\Python 312\python.exe',r'C:\Source Project\main.py',False)
    assert command==r'"C:\Python 312\python.exe" "C:\Source Project\main.py"'


def test_windows_startup_uses_user_scope_and_remove_is_idempotent():
    stored={};closed=[]
    class Registry:
        HKEY_CURRENT_USER='current-user';REG_SZ=1;KEY_SET_VALUE=2
        def CreateKey(self,hive,path):
            assert hive=='current-user';return path
        def OpenKey(self,hive,path,reserved,access):return path
        def SetValueEx(self,key,name,reserved,kind,value):stored[name]=value
        def DeleteValue(self,key,name):
            if name not in stored:raise FileNotFoundError
            del stored[name]
        def CloseKey(self,key):closed.append(key)
    reg=Registry()
    set_startup(True,reg,'C:\\app folder\\app.exe',frozen=True)
    assert stored['CampusNetworkAssistant']=='"C:\\app folder\\app.exe"'
    set_startup(False,reg);set_startup(False,reg)
    assert stored=={} and len(closed)==3


def test_windows_frozen_transport_uses_console_helper_not_windowed_gui(monkeypatch,tmp_path):
    app=tmp_path/'app.exe';app.touch()
    folder=tmp_path/'http-worker';folder.mkdir()
    helper=folder/'campus-http-worker.exe';helper.touch()
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'platform','win32')
    monkeypatch.setattr(sys,'executable',str(app))
    assert BoundedHttp._worker_command()==[str(helper)]
    helper.unlink()
    with pytest.raises(PortalError,match='工作程序缺失'):
        BoundedHttp._worker_command()


def test_source_zip_excludes_local_runtime_files(tmp_path):
    tool=tool_module()
    (tmp_path/'main.py').write_text('# entry')
    for dirname in ['campus_assistant','tests','docs','.github/workflows','.cache','.venv']:
        (tmp_path/dirname).mkdir(parents=True,exist_ok=True)
    (tmp_path/'campus_assistant/core.py').write_text('')
    (tmp_path/'campus_assistant/config.json').write_text('{"password":"private"}')
    (tmp_path/'docs/events.jsonl').write_text('private')
    (tmp_path/'.github/workflows/release.yml').write_text('name: test')
    (tmp_path/'.cache/private.json').write_text('private')
    target=tmp_path/'out.zip';tool.source_zip(target,tmp_path)
    with ZipFile(target) as archive:
        names=archive.namelist()
        assert 'Networkconnect/.github/workflows/release.yml' in names
        assert 'Networkconnect/campus_assistant/core.py' in names
        assert not any('config.json' in name or 'events.jsonl' in name or '.cache' in name for name in names)


def test_tag_must_match_current_version():
    tool=tool_module()
    assert tool.verify_tag('v'+__version__)=='v'+__version__
    with pytest.raises(ValueError):tool.verify_tag('v0.0.0')


def pe(path,architecture=0x8664):
    body=bytearray(128);body[:2]=b'MZ';struct.pack_into('<I',body,0x3c,64)
    body[64:68]=b'PE\0\0';struct.pack_into('<H',body,68,architecture)
    path.write_bytes(body)


def test_release_verifies_pe_and_rejects_unvalidated_windows_build(tmp_path):
    tool=tool_module()
    app=tmp_path/'app';app.mkdir()
    (app/'http-worker/_internal').mkdir(parents=True)
    (app/'_internal').mkdir()
    pe(app/'校园网助手.exe');pe(app/'http-worker/campus-http-worker.exe')
    smoke=tmp_path/'smoke.json';smoke.write_text(json.dumps({'ok':True,'version':__version__,'frozen':False,'platform':'Windows'}))
    metadata=tmp_path/'metadata.json';metadata.write_text('{}')
    with pytest.raises(ValueError,match='smoke test'):
        tool.windows_assets(app,tmp_path/'release',smoke,metadata)
    pe(app/'http-worker/campus-http-worker.exe',0x14c)
    with pytest.raises(ValueError,match='x64'):
        tool.verify_x64_pe(app/'http-worker/campus-http-worker.exe')


def test_powershell_build_script_remains_ascii_and_does_not_disable_tls():
    data=Path('build.ps1').read_bytes()
    assert data.isascii()
    script=data.decode('ascii')
    assert '--trusted-host' not in script and 'http://' not in script
    assert 'http_worker.py' in script and '--console' in script
    assert '--smoke-test' in script and 'SkipTests' in script
    assert 'requirements-windows.txt' in script


def test_release_workflow_pins_action_revisions_and_publishes_only_drafts():
    text=Path('.github/workflows/release.yml').read_text()
    import re
    revisions=re.findall(r'uses: actions/[\w-]+@([^\s]+)',text)
    assert revisions and all(re.fullmatch('[0-9a-f]{40}',ref) for ref in revisions)
    assert '--verify-tag --draft' in text
    assert "startsWith(github.ref, 'refs/tags/') && github.event_name == 'push'" in text
    assert 'Refusing to overwrite a published Release' in text
    assert 'sha256sum --check' in text


def test_workflow_only_builds_mac_m_series_and_windows():
    text=Path('.github/workflows/release.yml').read_text()
    assert 'runs-on: macos-15' in text
    assert 'architecture: arm64' in text
    assert 'macos-15-intel' not in text
    assert 'needs: [windows, macos]' in text
    assert 'runs-on: windows-2022' in text
    assert 'SHA256SUMS-all.txt' in text


def test_release_versions_match():
    import tomllib
    metadata=tomllib.loads(Path('pyproject.toml').read_text())
    assert metadata['project']['version']==__version__


def test_mac_frozen_transport_uses_dedicated_helper(monkeypatch,tmp_path):
    app_dir=tmp_path/'Campus.app'/'Contents'/'MacOS';app_dir.mkdir(parents=True)
    executable=app_dir/'Campus';executable.touch()
    helper_dir=app_dir.parent/'Helpers'/'campus-http-worker.app'/'Contents'/'MacOS';helper_dir.mkdir(parents=True)
    helper=helper_dir/'campus-http-worker';helper.touch()
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'platform','darwin')
    monkeypatch.setattr(sys,'executable',str(executable))
    assert BoundedHttp._worker_command()==[str(helper)]


def test_mac_helper_is_a_proper_nested_bundle():
    build=Path('build.sh').read_text()
    spec=Path('tools/mac_http_worker.spec').read_text()
    assert 'tools/mac_http_worker.spec' in build and 'Contents/Helpers' in build
    assert 'console=True' in spec and 'app = BUNDLE' in spec


def test_build_info_uses_same_platform_names_as_smoke_test(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('build_info',Path('tools/windows_build_info.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(sys,'platform','darwin')
    monkeypatch.setattr(module,'version',lambda name:'test-version')
    output=tmp_path/'build-info.json'
    module.write(output,True)
    assert json.loads(output.read_text())['platform']=='macOS'


def test_mac_prune_removes_unused_qt_chains_but_preserves_required_runtime(tmp_path):
    spec=importlib.util.spec_from_file_location('prune_macos_bundle',Path('tools/prune_macos_bundle.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    app=tmp_path/'Campus.app'
    required=[
        'Contents/Frameworks/PySide6/Qt/lib/QtCore.framework',
        'Contents/Frameworks/PySide6/Qt/lib/QtGui.framework',
        'Contents/Frameworks/PySide6/Qt/lib/QtWidgets.framework',
        'Contents/Frameworks/PySide6/Qt/lib/QtNetwork.framework',
        'Contents/Frameworks/PySide6/Qt/plugins/platforms/libqcocoa.dylib',
        'Contents/Frameworks/PySide6/Qt/plugins/networkinformation/libqapplenetworkinformation.dylib',
        'Contents/Helpers/campus-http-worker.app',
    ]
    for relative in required:
        path=app/relative
        if path.suffix:
            path.parent.mkdir(parents=True,exist_ok=True);path.touch()
        else:path.mkdir(parents=True,exist_ok=True)
    for name in module.UNUSED_PLUGIN_DIRS:
        path=app/'Contents/Frameworks/PySide6/Qt/plugins'/name
        path.mkdir(parents=True,exist_ok=True);(path/'unused.dylib').touch()
    for name in module.UNUSED_QT_FRAMEWORKS:
        (app/'Contents/Frameworks/PySide6/Qt/lib'/f'{name}.framework').mkdir(parents=True,exist_ok=True)

    result=module.prune(app)
    assert result['plugin_dirs']==len(module.UNUSED_PLUGIN_DIRS)
    assert result['qt_frameworks']==len(module.UNUSED_QT_FRAMEWORKS)
    assert all((app/relative).exists() for relative in required)
    assert not any((app/'Contents/Frameworks/PySide6/Qt/plugins'/name).exists()
                   for name in module.UNUSED_PLUGIN_DIRS)


def test_mac_build_runs_qt_pruning_before_final_codesign():
    build=Path('build.sh').read_text()
    prune=build.index("tools/prune_macos_bundle.py 'dist/校园网助手.app'")
    sign=build.index("codesign --force --deep --sign - 'dist/校园网助手.app'")
    assert prune < sign


def test_release_notes_match_scheduler_2_and_current_flow_semantics():
    notes=tool_module().release_notes()
    assert '10 分钟心跳' in notes
    assert '30/60/120/300 秒退避' in notes
    assert '23:58–00:15' in notes
    assert '未确认 / 无需执行 / 待处理' in notes


def test_current_source_package_includes_macos_pruning_tool(tmp_path):
    tool=tool_module()
    target=tmp_path/'source.zip'
    tool.source_zip(target)
    with ZipFile(target) as archive:
        assert 'Networkconnect/tools/prune_macos_bundle.py' in archive.namelist()
