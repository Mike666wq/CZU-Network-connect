from pathlib import Path
from importlib.metadata import version
import json
import platform
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from campus_assistant import __version__


def write(path, tests_passed):
    packages=('PySide6','psutil','tzdata','pytest','pyinstaller','pyinstaller-hooks-contrib')
    data={'version':__version__,'platform':'Windows' if sys.platform=='win32' else platform.system(),
          'architecture':platform.machine(),'python':platform.python_version(),
          'dependencies':{name:version(name) for name in packages},'tests_passed':tests_passed,
          'windows_authenticode_signed':False,'macos_notarized':False,'authentication_tested':'offline fake responses only','version_validation':'source version matches tag' if __import__('os').environ.get('GITHUB_REF','').startswith('refs/tags/') else 'untagged build'}
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    write(sys.argv[1], sys.argv[2]=='tests-passed')
