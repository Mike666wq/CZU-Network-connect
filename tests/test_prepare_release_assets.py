from pathlib import Path
import importlib.util
import json
import hashlib
import pytest


def tool():
    spec=importlib.util.spec_from_file_location('prepare_release_assets',Path('tools/prepare_release_assets.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def assets(root):
    windows=root/'windows';mac=root/'macos'/'release-v0.3.4-macos'
    windows.mkdir(parents=True);mac.mkdir(parents=True)
    for directory,platform,entries,manifest in [
        (windows,'Windows',['campus-network-assistant-v0.3.4-windows-x64.zip','campus-network-assistant-v0.3.4-source.zip','build-info.json'],'SHA256SUMS.txt'),
        (mac,'macOS',['campus-network-assistant-v0.3.4-macos-arm64.zip','macos-build-info.json'],'SHA256SUMS-macos.txt')]:
        lines=[]
        for name in entries:
            path=directory/name
            if name.endswith('.json'):
                path.write_text(json.dumps({'version':'0.3.4','platform':platform,'tests_passed':True,
                                           'smoke_test':{'ok':True,'frozen':True,'platform':platform,'version':'0.3.4'}}))
            else:path.write_bytes(b'tested build fixture')
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name+'\n')
        (directory/manifest).write_text(''.join(lines))
    (windows/'release-notes.md').write_text('Release notes')
    return windows,mac


def test_nested_mac_artifact_is_verified_and_flattened(tmp_path):
    root=tmp_path/'artifacts';assets(root)
    result=tool().prepare(root,tmp_path/'prepared','0.3.4')
    assert (result/'campus-network-assistant-v0.3.4-macos-arm64.zip').is_file()
    assert len((result/'SHA256SUMS-all.txt').read_text().splitlines())==5
    assert (result/'release-notes.md').is_file()


def test_tampered_artifact_is_not_rehashed_as_valid(tmp_path):
    root=tmp_path/'artifacts';_,mac=assets(root)
    (mac/'campus-network-assistant-v0.3.4-macos-arm64.zip').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Checksum mismatch'):
        tool().prepare(root,tmp_path/'prepared','0.3.4')


def test_same_output_and_artifact_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError,match='outside'):
        tool().prepare(tmp_path,tmp_path,'0.3.4')


def test_mac_upload_uses_exact_version_directory_not_a_wildcard():
    text=Path('.github/workflows/release.yml').read_text()
    assert 'path: dist/release-v*-macos/' not in text
    assert 'path: dist/release-v${{ steps.version.outputs.version }}-macos/' in text


def test_release_normalizes_original_artifacts_on_cloud_runner():
    text=Path('.github/workflows/release.yml').read_text()
    assert 'merge-multiple: false' in text
    assert 'python3 tools/prepare_release_assets.py --artifacts artifacts --output release' in text
    assert 'sha256sum --check SHA256SUMS-all.txt' in text
    assert 'sha256sum --check SHA256SUMS-macos.txt' not in text


def test_cloud_workflow_supports_one_command_rebuild_and_publish():
    text=Path('.github/workflows/release.yml').read_text()
    assert "github.event_name == 'workflow_dispatch' && inputs.publish" in text
    assert 'type: boolean' in text and 'default: false' in text
    assert 'gh release edit "$TAG" --draft=false --latest' in text
    assert 'sha="$BUILD_SHA"' in text
    assert 'git -C .. rev-parse "$TAG^{commit}"' in text
