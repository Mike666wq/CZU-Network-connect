"""Platform text and typography. Does not alter network or configuration behavior."""
import sys


def platform_name(platform=None):
    platform = sys.platform if platform is None else platform
    return 'Windows' if platform == 'win32' else 'macOS' if platform == 'darwin' else 'Linux'


def ui_font(platform=None):
    platform = sys.platform if platform is None else platform
    return 'Microsoft YaHei UI' if platform == 'win32' else '.AppleSystemUIFont' if platform == 'darwin' else 'Sans Serif'


def ui_font_stack(platform=None):
    platform = sys.platform if platform is None else platform
    if platform == 'win32':
        return "'Microsoft YaHei UI', 'Segoe UI', sans-serif"
    if platform == 'darwin':
        return "'.AppleSystemUIFont', 'PingFang SC', sans-serif"
    return "'Noto Sans CJK SC', 'Noto Sans', sans-serif"


def window_metrics(platform=None):
    platform = sys.platform if platform is None else platform
    if platform == 'win32':
        return {'default': (960, 740), 'minimum': (840, 700)}
    if platform == 'darwin':
        return {'default': (940, 720), 'minimum': (820, 700)}
    return {'default': (940, 720), 'minimum': (820, 700)}


def navigation_shortcuts(platform=None):
    platform = sys.platform if platform is None else platform
    modifier = 'Meta' if platform == 'darwin' else 'Ctrl'
    return {name: f'{modifier}+{index}' for index, name in enumerate(('status', 'settings', 'records'), 1)}


def startup_text(platform=None):
    return '登录 Windows 后启动' if platform_name(platform) == 'Windows' else '登录 Mac 后启动' if platform_name(platform) == 'macOS' else '登录系统后启动'


def background_text(platform=None):
    place = '系统托盘' if platform_name(platform) == 'Windows' else '菜单栏' if platform_name(platform) == 'macOS' else '系统托盘'
    return f'关闭窗口后继续在{place}运行'
