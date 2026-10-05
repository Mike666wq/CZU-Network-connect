"""Platform text and typography. Does not alter network or configuration behavior."""
import sys


def platform_name(platform=None):
    platform = sys.platform if platform is None else platform
    return 'Windows' if platform == 'win32' else 'macOS' if platform == 'darwin' else 'Linux'


def ui_font(platform=None):
    platform = sys.platform if platform is None else platform
    return 'Microsoft YaHei UI' if platform == 'win32' else '.AppleSystemUIFont' if platform == 'darwin' else 'Sans Serif'


def startup_text(platform=None):
    return '登录 Windows 后启动' if platform_name(platform) == 'Windows' else '登录 Mac 后启动' if platform_name(platform) == 'macOS' else '登录系统后启动'


def background_text(platform=None):
    place = '系统托盘' if platform_name(platform) == 'Windows' else '菜单栏' if platform_name(platform) == 'macOS' else '系统托盘'
    return f'关闭窗口后继续在{place}运行'
