"""User-scope Windows login startup. No administrator/system-wide settings."""
from pathlib import Path
import subprocess
import sys


def startup_command(executable=None, source=None, frozen=None):
    executable = sys.executable if executable is None else executable
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    args = [str(executable)]
    if not frozen:
        script = Path(source) if source is not None else Path(__file__).resolve().parents[1] / 'main.py'
        args.append(str(script))
    return subprocess.list2cmdline(args)


def set_startup(enabled, registry=None, executable=None, source=None, frozen=None):
    if registry is None:
        import winreg as registry
    # Only create the user key when enabling. Disabling an absent key is a no-op.
    location = r'Software\Microsoft\Windows\CurrentVersion\Run'
    if enabled:
        key = registry.CreateKey(registry.HKEY_CURRENT_USER, location)
    else:
        try:
            key = registry.OpenKey(registry.HKEY_CURRENT_USER, location, 0, registry.KEY_SET_VALUE)
        except FileNotFoundError:
            return
    try:
        if enabled:
            registry.SetValueEx(key, 'CampusNetworkAssistant', 0, registry.REG_SZ,
                                startup_command(executable, source, frozen))
        else:
            try:
                registry.DeleteValue(key, 'CampusNetworkAssistant')
            except FileNotFoundError:
                pass
    finally:
        registry.CloseKey(key)
