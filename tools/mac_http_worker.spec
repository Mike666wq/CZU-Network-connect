# The console-enabled helper must use a real Mac bundle layout, not a copied
# onedir tree (whose Python framework layout is rejected by codesign --deep).
from pathlib import Path
import sys
root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(root))
from campus_assistant import __version__

a = Analysis([str(root / 'http_worker.py')], pathex=[str(root)],
             binaries=[], datas=[], hiddenimports=[], hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='campus-http-worker',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, argv_emulation=False, target_arch='arm64',
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='campus-http-worker')
app = BUNDLE(coll, name='campus-http-worker.app',
             bundle_identifier='io.github.Mike666wq.czu-network-connect.http-worker',
             version=__version__)
