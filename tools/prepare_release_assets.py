"""Flatten existing CI assets and verify ORIGINAL checksums. Never builds or publishes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def locate(root, name):
    matches=[path for path in root.rglob(name) if path.is_file()]
    if len(matches)!=1:
        raise ValueError(f'Expected exactly one {name}, found {len(matches)} under {root}')
    return matches[0]


def prepare(artifacts, output, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise ValueError('Version must be X.Y.Z')
    artifacts=Path(artifacts).resolve();output=Path(output).resolve()
    if output==artifacts or output.is_relative_to(artifacts):
        raise ValueError('Output must be outside downloaded artifacts to avoid duplicate searches')
    expected=[f'campus-network-assistant-v{version}-windows-x64.zip',
              f'campus-network-assistant-v{version}-source.zip','build-info.json',
              f'campus-network-assistant-v{version}-macos-arm64.zip','macos-build-info.json']
    verified={}
    for manifest_name in ('SHA256SUMS.txt','SHA256SUMS-macos.txt'):
        manifest=locate(artifacts,manifest_name)
        for line in manifest.read_text(encoding='utf-8-sig').splitlines():
            match=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?([^/\\]+)',line)
            if not match:raise ValueError(f'Invalid checksum line in {manifest_name}')
            checksum,name=match.groups()
            if name not in expected or name in verified:
                raise ValueError(f'Unexpected or duplicate asset: {name}')
            asset=manifest.parent/name
            if not asset.is_file():raise ValueError(f'Missing original asset beside manifest: {name}')
            if digest(asset)!=checksum.lower():raise ValueError(f'Checksum mismatch: {name}')
            verified[name]=(asset,checksum.lower())
    if set(verified)!=set(expected):raise ValueError('Both platforms and source must be verified')
    for name, platform in [('build-info.json','Windows'),('macos-build-info.json','macOS')]:
        metadata=json.loads(verified[name][0].read_text(encoding='utf-8-sig'))
        if not (metadata.get('version')==version and metadata.get('platform')==platform and metadata.get('tests_passed') is True):
            raise ValueError(f'Invalid tested metadata: {name}')
        smoke=metadata.get('smoke_test',{})
        if not (smoke.get('ok') is True and smoke.get('frozen') is True and smoke.get('version')==version and smoke.get('platform')==platform):
            raise ValueError(f'Packaged smoke verification missing in {name}')
    notes=locate(artifacts,'release-notes.md')
    output.mkdir(parents=True,exist_ok=True)
    for name,(asset,_) in verified.items():
        destination=output/name
        if destination.exists() and digest(destination)!=verified[name][1]:
            raise ValueError(f'Refusing to overwrite different existing asset: {name}')
        shutil.copy2(asset,destination)
    combined=output/'SHA256SUMS-all.txt'
    combined.write_text(''.join(verified[name][1]+'  '+name+'\n' for name in expected),encoding='ascii')
    shutil.copy2(notes,output/'release-notes.md')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    target=prepare(args.artifacts,args.output,args.version)
    print('Original SHA-256 and both native packaged smoke reports verified.')
    print('Release files:',target)
