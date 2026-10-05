"""Generate Windows VERSIONINFO using the project's version, without user data."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from campus_assistant import __version__


def generate(path: Path):
    parts=tuple(int(p) for p in __version__.split('.'))+(0,)
    text=f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f,
                   flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Campus Network Assistant'),
    StringStruct('FileDescription', 'Campus Network Assistant'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', 'campus-network-assistant'),
    StringStruct('OriginalFilename', '校园网助手.exe'),
    StringStruct('ProductName', '校园网助手'),
    StringStruct('ProductVersion', '{__version__}')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
'''
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding='utf-8')
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path',type=Path)
    generate(parser.parse_args().path)
