"""Native presentation-only widgets; this module never probes or authenticates a network."""
from __future__ import annotations

import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient, QPolygonF
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout,
    QPushButton, QComboBox, QLineEdit, QCheckBox, QFormLayout, QScrollArea,
    QPlainTextEdit, QSizePolicy, QStyle, QStyleOptionButton)

from .engine import State
from .config import DORM_PROVIDERS
from . import __version__
from .platform_ui import platform_name, ui_font, startup_text, background_text

STYLE = """
QMainWindow, QWidget#workspace { background: #141a1d; color: #edf2f0; }
QWidget { color: #edf2f0; font-family: '.AppleSystemUIFont', 'PingFang SC', sans-serif; font-size: 13px; }
QFrame#hero, QFrame#configCard, QFrame#logCard { background: #1b2226; border: 1px solid #303a3f; border-radius: 16px; }
QFrame#metaCard { background: #182023; border: 1px solid #2b373b; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 21px; font-weight: 600; letter-spacing: 1px; }
QLabel#muted, QLabel#eyebrow { color: #91a1a6; font-size: 12px; }
QLabel#headline { font-size: 29px; font-weight: 600; }
QLabel#detail { color: #acb9bc; font-size: 13px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#badge { color: #7de1b8; background: #1e3831; border: 1px solid #335449; border-radius: 12px; padding: 5px 12px; font-size: 12px; }
QLabel#configWarning { color: #93a1a7; font-size: 11px; }
QLabel#schedule { color: #91a1a6; font-size: 11px; }
QLabel#countdownValue { color: #8ae6bf; font-size: 23px; font-weight: 600; }
QPushButton { color: #dce5e6; background: #293237; border: 1px solid #3a474d; border-radius: 9px; padding: 9px 15px; font-weight: 500; }
QPushButton:hover { background: #354147; border-color: #64747b; }
QPushButton:pressed { background: #1f292d; }
QPushButton#primary { background: #8ae6bf; color: #10241b; border-color: #8ae6bf; font-weight: 600; }
QPushButton#primary:hover { background: #acf4d5; }
QPushButton#primary:pressed { background: #64caa1; }
QPushButton#quiet { background: transparent; color: #a4b3b8; border: none; padding: 5px 8px; font-size: 12px; }
QPushButton#quiet:hover { color: #edf2f0; background: #293237; }
QLineEdit, QComboBox { background: #12191d; border: 1px solid #39454b; border-radius: 8px; padding: 8px 10px; min-height: 20px; color: #e5eeee; selection-background-color: #386e5e; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #8ae6bf; }
QLineEdit:read-only { color: #9bb0b6; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #202a2f; color: #e5eeee; selection-background-color: #345348; border: 1px solid #46565d; padding: 5px; }
QCheckBox { spacing: 8px; color: #b9c7ca; font-size: 12px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #56676e; border-radius: 4px; background: #131c21; }
QCheckBox::indicator:checked { background: #8ae6bf; border-color: #8ae6bf; image: none; }
QScrollArea { border: none; background: transparent; }
QWidget#configBody { background: transparent; }
QPlainTextEdit { background: transparent; color: #a7b8bf; border: none; font-size: 12px; selection-background-color: #345348; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: #445159; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QMenuBar { background: #141a1d; color: #bdccd0; }
QMenuBar::item:selected, QMenu::item:selected { background: #345348; }
QMenu { background: #202a2f; color: #edf2f0; border: 1px solid #445159; padding: 5px; }
"""



def countdown_remaining(scheduler, now_monotonic: float, now_wall: datetime) -> int:
    """Read-only view of the actual heartbeat/recovery deadline."""
    return scheduler.seconds_until_due(now_monotonic, now_wall)


def label(text, object_name="muted", wrap=False):
    item = QLabel(text)
    item.setObjectName(object_name)
    item.setWordWrap(wrap)
    return item


def card(name):
    item = QFrame()
    item.setObjectName(name)
    return item


def button(text, callback, style="", tooltip=""):
    item = QPushButton(text)
    if style:
        item.setObjectName(style)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    item.clicked.connect(callback)
    if tooltip:
        item.setToolTip(tooltip)
    return item


class SelectBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#a3b8be"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x = self.width() - 16; y = self.height() / 2
        p.drawPolyline(QPolygonF([QPointF(x-4, y-2), QPointF(x, y+2), QPointF(x+4, y-2)]))
        p.end()


class CheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            option = QStyleOptionButton(); self.initStyleOption(option)
            rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
            p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#163b2b"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x = rect.x(); y = rect.y()
            p.drawPolyline(QPolygonF([QPointF(x+3, y+7), QPointF(x+6, y+10), QPointF(x+12, y+4)]))
            p.end()


class NetworkOrb(QWidget):
    """Small vector animation, driven only by UI state, not real network traffic."""
    def __init__(self):
        super().__init__()
        self.mode = "idle"
        self.started = time.monotonic()
        self.setFixedSize(164, 154)
        self.clock = QTimer(self)
        self.clock.setInterval(40)
        self.clock.timeout.connect(self.update)

    def set_mode(self, mode):
        self.mode = mode
        if mode == "working" and self.isVisible():
            self.clock.start()
        else:
            self.clock.stop()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.mode == "working":
            self.clock.start()

    def hideEvent(self, event):
        self.clock.stop()
        super().hideEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#8ae6bf" if self.mode in {"success", "working"} else
                       "#efc27d" if self.mode == "warning" else "#74878f")
        center = QPointF(82, 73)
        gradient = QRadialGradient(center, 76)
        glow = QColor(color); glow.setAlpha(38)
        gradient.setColorAt(0, glow)
        gradient.setColorAt(1, QColor(27, 34, 38, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(gradient)
        p.drawEllipse(center, 76, 76)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#314249"), 1))
        p.drawEllipse(center, 56, 56)
        p.drawEllipse(center, 39, 39)
        if self.mode == "working":
            angle = (time.monotonic() - self.started) * 105
            p.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(26, 17, 112, 112), int(-angle * 16), 88 * 16)
        for angle in (-90, 30, 150):
            rad = math.radians(angle)
            point = center + QPointF(math.cos(rad) * 56, math.sin(rad) * 56)
            p.setPen(QPen(QColor("#40595f"), 1))
            p.drawLine(center, point)
            p.setPen(QPen(color, 1)); p.setBrush(QColor("#1b2226"))
            p.drawEllipse(point, 4, 4)
        p.setPen(QPen(color, 1.5)); p.setBrush(QColor("#223a33") if self.mode == "success" else QColor("#202f34"))
        p.drawEllipse(center, 25, 25)
        p.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self.mode == "success":
            p.drawLine(QPointF(70, 73), QPointF(78, 81)); p.drawLine(QPointF(78, 81), QPointF(94, 65))
        elif self.mode == "warning":
            p.drawLine(QPointF(82, 60), QPointF(82, 76)); p.drawPoint(QPointF(82, 85))
        else:
            for radius in (7, 14):
                p.drawArc(QRectF(82-radius, 76-radius, radius*2, radius*2), 38*16, 104*16)
            p.drawPoint(QPointF(82, 79))
        p.end()


class ProcessTrack(QWidget):
    titles = ("网络探测", "识别场景", "读取配置", "提交认证", "联网验证")
    def __init__(self):
        super().__init__()
        self.states = ["pending"] * 5
        self.setMinimumHeight(91)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(94)

    def set_states(self, states):
        self.states = list(states)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = self.width() / 5
        y = 24
        points = [QPointF(step * (i + 0.5), y) for i in range(5)]
        for i in range(4):
            done = self.states[i] == "done" and self.states[i+1] in {"done", "active"}
            p.setPen(QPen(QColor("#598a78" if done else "#334149"), 1.5))
            p.drawLine(points[i] + QPointF(15, 0), points[i+1] - QPointF(15, 0))
        colors = {"pending": "#607079", "done": "#8ae6bf", "active": "#8ae6bf",
                  "skipped": "#83939b", "neutral": "#83939b", "warning": "#efc27d"}
        captions = {"pending": "待执行", "done": "已完成", "active": "进行中",
                    "skipped": "无需执行", "neutral": "未确认", "warning": "待处理"}
        for i, state in enumerate(self.states):
            color = QColor(colors[state]); x = points[i].x()
            p.setPen(QPen(color, 1.2)); p.setBrush(QColor("#233d33" if state == "done" else "#1b2429"))
            p.drawEllipse(points[i], 12, 12)
            p.setPen(color)
            if state == "done":
                p.setPen(QPen(color, 1.8)); p.drawLine(QPointF(x-5, y), QPointF(x-1, y+4)); p.drawLine(QPointF(x-1, y+4), QPointF(x+6, y-4))
            else:
                p.setFont(QFont(ui_font(), 11))
                p.drawText(QRectF(x-12, y-12, 24, 24), Qt.AlignmentFlag.AlignCenter,
                           "—" if state in {"skipped", "neutral"} else str(i+1))
            p.setPen(QColor("#e1eaeb" if state in {"done", "active"} else "#9babb2"))
            p.setFont(QFont(ui_font(), 12))
            p.drawText(QRectF(step*i, 45, step, 20), Qt.AlignmentFlag.AlignCenter, self.titles[i])
            p.setPen(color); p.setFont(QFont(ui_font(), 10))
            p.drawText(QRectF(step*i, 69, step, 18), Qt.AlignmentFlag.AlignCenter, captions[state])
        p.end()


class Dashboard(QWidget):
    def __init__(self, window):
        super().__init__()
        self.stage = 0
        self.log_entries = []
        self.last_event = ""
        self.states = ["pending"] * 5
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(16)
        hero = card("hero"); hero.setMinimumHeight(186); hero_box = QHBoxLayout(hero); hero_box.setContentsMargins(24, 16, 10, 16)
        text = QVBoxLayout(); text.setSpacing(10)
        self.kicker = label("连接状态 / CONNECTION", "eyebrow")
        self.headline = label("准备连接", "headline")
        self.headline.setWordWrap(True)
        window.status_label = label("启动后会自动检查当前网络。", "detail", True)
        window.status_label.setMinimumHeight(40)
        self.elapsed = label("后台守护 · 无需保持窗口打开", "muted")
        text.addWidget(self.kicker); text.addWidget(self.headline); text.addWidget(window.status_label); text.addWidget(self.elapsed)
        self.orb = NetworkOrb()
        hero_box.addLayout(text, 1); hero_box.addWidget(self.orb)
        layout.addWidget(hero)
        meta = card("metaCard"); meta_box = QVBoxLayout(meta); meta_box.setContentsMargins(18, 13, 18, 13); meta_box.setSpacing(7)
        window.scene_label = label("当前识别场景：等待检查", wrap=True)
        window.active_entrance_label = label("当前认证入口：等待识别", "muted", True)
        meta_box.addWidget(window.scene_label); meta_box.addWidget(window.active_entrance_label)
        layout.addWidget(meta)
        process_header = QHBoxLayout(); process_header.addWidget(label("连接流程", "sectionTitle")); process_header.addStretch()
        self.flow_note = label("仅展示实际执行的步骤", "muted")
        process_header.addWidget(self.flow_note); layout.addLayout(process_header)
        self.track = ProcessTrack(); layout.addWidget(self.track)
        log_card = card("logCard"); log_card.setMinimumHeight(130); log_box = QVBoxLayout(log_card); log_box.setContentsMargins(18, 14, 18, 10); log_box.setSpacing(9)
        log_header = QHBoxLayout(); log_header.addWidget(label("运行记录", "sectionTitle")); log_header.addStretch(); log_header.addWidget(label("本次会话", "muted")); log_box.addLayout(log_header)
        self.events = QPlainTextEdit(); self.events.setReadOnly(True); self.events.setMaximumBlockCount(160)
        self.events.setMinimumHeight(78); self.events.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.events.setAccessibleName("本次连接过程运行记录")
        log_box.addWidget(self.events, 1)
        layout.addWidget(log_card, 1)
        countdown_row = QHBoxLayout(); countdown_row.setSpacing(12)
        countdown_row.addWidget(label("下次检测", "muted"))
        window.countdown_value = label("—", "countdownValue")
        window.countdown_value.setMinimumWidth(104)
        window.countdown_value.setAccessibleName("下一次网络检查剩余时间")
        countdown_row.addWidget(window.countdown_value)
        countdown_row.addStretch()
        window.schedule_label = label("23:58–00:15 午夜恢复窗口\n北京时间", "schedule", True)
        window.schedule_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        countdown_row.addWidget(window.schedule_label)
        layout.addLayout(countdown_row)
        controls = QHBoxLayout(); controls.setSpacing(10)
        controls.addWidget(button("立即检查", window.start_check, "primary")); controls.addWidget(button("重试", window.retry))
        controls.addWidget(button("暂停 / 恢复", window.toggle_pause)); controls.addStretch()
        layout.addLayout(controls)
        self.add_event("助手已启动，等待本轮网络检查。")

    def add_event(self, message):
        # Only engine/progress descriptions, never form fields, request URLs or credentials.
        if message == self.last_event:
            return
        self.last_event = message
        stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M:%S")
        entry = f"{stamp}   {message}"
        self.log_entries.append(entry)
        self.log_entries = self.log_entries[-160:]
        self.events.appendPlainText(entry)
        self.events.verticalScrollBar().setValue(self.events.verticalScrollBar().maximum())

    def begin(self, reason):
        self.stage = 0; self.states = ["pending"] * 5
        self.track.set_states(self.states)
        self.headline.setText("正在检查网络")
        self.orb.set_mode("working")
        self.flow_note.setText("正在处理本轮连接")
        self.add_event({"startup": "开始启动检查", "heartbeat": "开始周期检查", "network": "网络发生变化，重新检查",
                        "midnight": "午夜恢复窗口开始", "midnight_extra": "午夜恢复进入快速检查阶段", "retry": "开始手动重试",
                        "wake": "设备唤醒，重新检查"}.get(reason, "开始网络检查"))

    def progress(self, message):
        if "验证互联网" in message:
            index = 4
        elif "提交" in message:
            index = 3
        elif "读取" in message and "配置" in message:
            index = 2
        elif "识别" in message or "查询校园" in message:
            index = 1
        else:
            index = 0
        if self.states[self.stage] == "active" and index != self.stage:
            self.states[self.stage] = "done"
        self.stage = index; self.states[index] = "active"
        self.track.set_states(self.states)
        self.headline.setText(("正在探测网络", "正在识别场景", "正在读取配置", "正在进行认证", "正在验证连接")[index])
        self.orb.set_mode("working")
        self.add_event(message)

    def finish(self, state, message, submitted=False):
        titles = {State.ONLINE: "已连接互联网", State.AUTHENTICATED: "认证成功，已连接", State.NEEDS_CONFIG: "还差一步配置",
                  State.AUTH_BLOCKED: "认证未通过", State.WAITING: "等待校园网络", State.ERROR: "暂时无法连接",
                  State.PAUSED: "自动检查已暂停", State.STOPPED: "后台守护已停止", State.PORTAL: "等待互联网恢复"}
        self.headline.setText(titles.get(state, state.value))
        success = state in {State.ONLINE, State.AUTHENTICATED}
        self.orb.set_mode("success" if success else "warning" if state in {State.NEEDS_CONFIG, State.AUTH_BLOCKED, State.ERROR, State.PORTAL} else "idle")
        if state == State.AUTHENTICATED and submitted:
            self.states = ["done"] * 5
        elif success:
            # Internet reachability is the terminal success criterion. If the
            # campus portal cannot be identified while Internet is already
            # reachable, scene identification is informational rather than an
            # outstanding user action.
            scene_state = "neutral" if "未识别" in message or "不在校园网" in message else "done"
            self.states = ["done", scene_state, "skipped", "skipped", "done"]
        elif state == State.NEEDS_CONFIG:
            self.states[self.stage] = "warning"
            if "服务商" in message or "账号和密码" in message:
                self.states = ["done", "done", "warning", "pending", "pending"]
        elif state in {State.ERROR, State.AUTH_BLOCKED, State.PORTAL}:
            self.states[self.stage] = "warning"
        elif state in {State.PAUSED, State.STOPPED}:
            self.states[self.stage] = "pending"
        elif state == State.WAITING:
            self.states[self.stage] = "warning" if "未识别" in message or "不在" in message else "pending"
        self.track.set_states(self.states)
        self.flow_note.setText("本轮已完成" if success else "等待恢复或补充配置")
        self.elapsed.setText("后台守护中 · 将按计划再次检查" if success else "保留当前步骤，方便定位问题")
        self.add_event(message)


def build_workspace(window):
    window.setStyleSheet(STYLE.replace("'.AppleSystemUIFont', 'PingFang SC', sans-serif", "'" + ui_font() + "', sans-serif"))
    window.resize(1160, 850)
    window.setMinimumSize(1020, 810)
    root = QWidget(); root.setObjectName("workspace")
    layout = QVBoxLayout(root); layout.setContentsMargins(26, 19, 26, 16); layout.setSpacing(17)
    header = QHBoxLayout(); brand = QVBoxLayout(); brand.setSpacing(3)
    brand.addWidget(label("校园网助手", "brand")); brand.addWidget(label("让连接自动发生，让过程清晰可见。", "muted"))
    header.addLayout(brand); header.addStretch(); window.ui_badge = label(platform_name() + " · 后台连接助手", "badge"); header.addWidget(window.ui_badge)
    layout.addLayout(header)
    body = QHBoxLayout(); body.setSpacing(22)
    window.dashboard = Dashboard(window); body.addWidget(window.dashboard, 1)
    config_card = card("configCard"); config_card.setFixedWidth(398)
    config_box = QVBoxLayout(config_card); config_box.setContentsMargins(20, 20, 20, 18); config_box.setSpacing(12)
    title_row = QHBoxLayout(); title_row.addWidget(label("连接配置", "sectionTitle")); title_row.addStretch(); title_row.addWidget(label("保存后立即生效", "muted"))
    config_box.addLayout(title_row)
    config_box.addWidget(label("账号保持不变，入口与服务商随场景切换。", "muted", True))
    scroll = QScrollArea(); window.config_scroll = scroll; scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    config_body = QWidget(); config_body.setObjectName("configBody")
    settings = QVBoxLayout(config_body); settings.setContentsMargins(0, 0, 8, 0); settings.setSpacing(10)
    window.profile = SelectBox()
    for title, value in (("自动识别公共网 / 宿舍网", "auto"), ("仅使用公共网", "public"), ("仅使用宿舍网", "dorm")):
        window.profile.addItem(title, value)
    settings.addWidget(label("认证场景", "muted")); settings.addWidget(window.profile)
    window.follow_scene = CheckBox("表单自动跟随识别结果"); window.follow_scene.setChecked(True)
    window.follow_scene.toggled.connect(window.follow_scene_changed); settings.addWidget(window.follow_scene)
    window.edit_profile = SelectBox(); window.edit_profile.addItem("公共网配置", "public"); window.edit_profile.addItem("宿舍网配置", "dorm")
    settings.addWidget(label("当前配置表单", "muted")); settings.addWidget(window.edit_profile)
    window.cred_mode = SelectBox(); window.cred_mode.addItem("两场景共用账号与密码", "shared"); window.cred_mode.addItem("为两个场景分别保存账号", "separate")
    settings.addWidget(window.cred_mode)
    form = QFormLayout(); window.form = form
    form.setHorizontalSpacing(12); form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    def add(key, title, secret=False):
        edit = QLineEdit(); edit.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
        edit.setAccessibleName(title); window.fields[key] = edit; form.addRow(title, edit)
    add("portal_url", "配置入口"); add("username", "共用账号"); add("password", "共用密码", True)
    add("public_username", "公共网账号"); add("public_password", "公共网密码", True); add("public_suffix", "公共网后缀")
    add("dorm_username", "宿舍网账号"); add("dorm_password", "宿舍网密码", True); add("dorm_suffix", "宿舍网后缀")
    window.fields["dorm_suffix"].setReadOnly(True)
    window.dorm_provider = SelectBox()
    for title, value in DORM_PROVIDERS:
        window.dorm_provider.addItem(title, value)
    form.addRow("宿舍服务商", window.dorm_provider)
    window.dorm_provider.currentIndexChanged.connect(window.dorm_provider_changed)
    settings.addLayout(form)
    settings.addSpacing(4)
    window.enabled = CheckBox("自动检查并认证"); window.autostart = CheckBox(startup_text())
    settings.addStretch(1)
    scroll.setWidget(config_body); config_box.addWidget(scroll, 1)
    switches = QHBoxLayout(); switches.setSpacing(18)
    switches.addWidget(window.enabled); switches.addWidget(window.autostart); switches.addStretch()
    config_box.addLayout(switches)
    window.warning = label("密码明文保存在本机，不上传到其他服务器。", "configWarning", True)
    window.warning.setToolTip("配置保存于：" + str(window._ui_config_path))
    config_box.addWidget(window.warning)
    save_row = QHBoxLayout(); save_row.setSpacing(10)
    save_row.addWidget(button("保存配置", window.save, "primary"), 1); save_row.addWidget(button("重载文件", window.reload_config), 1)
    config_box.addLayout(save_row)
    links = QHBoxLayout(); links.addWidget(button("打开登录页", window.open_portal, "quiet")); links.addWidget(button("配置文件夹", window.open_folder, "quiet")); links.addStretch()
    config_box.addLayout(links)
    body.addWidget(config_card); layout.addLayout(body, 1)
    footer = QHBoxLayout(); footer.addWidget(label("●  " + background_text(), "muted")); footer.addStretch()
    footer.addWidget(label(f"v{__version__} · 网络逻辑保持不变", "muted")); footer.addWidget(button("退出助手", window.quit_app, "quiet"))
    layout.addLayout(footer)
    window.setCentralWidget(root)
    window.profile.currentIndexChanged.connect(window.profile_changed)
    window.edit_profile.currentIndexChanged.connect(window.edit_profile_changed)
    window.last_edit_profile = window.edit_profile.currentData() or "public"
    window.cred_mode.currentIndexChanged.connect(window.apply_mode_visibility)
