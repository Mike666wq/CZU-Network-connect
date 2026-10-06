"""Native presentation-only widgets; this module never probes or authenticates a network."""
from __future__ import annotations

import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QRadialGradient, QPolygonF
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QHBoxLayout, QVBoxLayout,
    QPushButton, QComboBox, QLineEdit, QCheckBox, QFormLayout, QScrollArea,
    QPlainTextEdit, QSizePolicy, QStyle, QStyleOptionButton, QStackedWidget)

from .engine import Outcome, State
from .presentation import present_outcome
from .config import DORM_PROVIDERS
from . import __version__
from .platform_ui import (platform_name, ui_font, ui_font_stack, window_metrics,
                          navigation_shortcuts, startup_text, background_text)

STYLE = """
QMainWindow, QWidget#workspace { background: #141a1d; color: #edf2f0; }
QWidget { color: #edf2f0; font-family: '.AppleSystemUIFont', 'PingFang SC', sans-serif; font-size: 13px; }
QFrame#hero, QFrame#configCard, QFrame#logCard, QFrame#recentCard, QFrame#recordCard { background: #1b2226; border: 1px solid #303a3f; border-radius: 16px; }
QFrame#metaCard { background: #182023; border: 1px solid #2b373b; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 21px; font-weight: 600; letter-spacing: 1px; }
QLabel#muted, QLabel#eyebrow { color: #91a1a6; font-size: 12px; }
QLabel#headline { font-size: 29px; font-weight: 600; }
QLabel#detail { color: #acb9bc; font-size: 13px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#badge { color: #7de1b8; background: #1e3831; border: 1px solid #335449; border-radius: 12px; padding: 5px 12px; font-size: 12px; }
QLabel#badge[tone="attention"] { color: #efc27d; background: #32291d; border-color: #5a4932; }
QLabel#badge[tone="neutral"] { color: #b1c0c5; background: #222c31; border-color: #3b474d; }
QLabel#statusChip { border-radius: 9px; padding: 3px 8px; font-size: 11px; font-weight: 500; }
QLabel#statusChip[tone="success"] { color: #8ae6bf; background: #1d342d; border: 1px solid #345348; }
QLabel#statusChip[tone="working"] { color: #8ed9e6; background: #1b3035; border: 1px solid #31505a; }
QLabel#statusChip[tone="attention"] { color: #efc27d; background: #32291d; border: 1px solid #5a4932; }
QLabel#statusChip[tone="error"] { color: #f08a8a; background: #352326; border: 1px solid #61383e; }
QLabel#statusChip[tone="neutral"] { color: #a9b8bd; background: #222b30; border: 1px solid #39464c; }
QLabel#configWarning { color: #93a1a7; font-size: 11px; }
QLabel#schedule { color: #91a1a6; font-size: 11px; }
QLabel#countdownValue { color: #8ae6bf; font-size: 23px; font-weight: 600; }
QLabel#recentActivity { color: #a7b8bf; font-size: 12px; }
QLabel#saveStatus { color: #91a1a6; font-size: 11px; }
QPushButton { color: #dce5e6; background: #293237; border: 1px solid #3a474d; border-radius: 9px; padding: 9px 15px; font-weight: 500; }
QPushButton:hover { background: #354147; border-color: #64747b; }
QPushButton:focus { border: 1px solid #8ae6bf; }
QPushButton:pressed { background: #1f292d; }
QPushButton:disabled { color: #718087; background: #20282c; border-color: #303a3f; }
QPushButton#primary { background: #8ae6bf; color: #10241b; border-color: #8ae6bf; font-weight: 600; }
QPushButton#primary:hover { background: #acf4d5; }
QPushButton#primary:pressed { background: #64caa1; }
QPushButton#primary:disabled { background: #2d3b36; color: #6f8179; border-color: #394b44; }
QPushButton#quiet { background: transparent; color: #a4b3b8; border: none; padding: 5px 8px; font-size: 12px; }
QPushButton#quiet:hover { color: #edf2f0; background: #293237; }
QPushButton#quiet:focus { color: #edf2f0; background: #202a2e; border: 1px solid #50665d; }
QPushButton#nav { background: transparent; color: #91a1a6; border: 1px solid transparent; border-radius: 9px; padding: 7px 13px; font-weight: 500; }
QPushButton#nav:hover { color: #edf2f0; background: #202a2e; }
QPushButton#nav:focus { color: #edf2f0; border-color: #50665d; }
QPushButton#nav:checked { color: #8ae6bf; background: #20342e; border-color: #335449; }
QLineEdit, QComboBox { background: #12191d; border: 1px solid #39454b; border-radius: 8px; padding: 8px 10px; min-height: 20px; color: #e5eeee; selection-background-color: #386e5e; }
QLineEdit:hover, QComboBox:hover { border-color: #53636a; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #8ae6bf; }
QLineEdit:disabled, QComboBox:disabled { color: #718087; background: #171e22; border-color: #2b353a; }
QLineEdit[attentionTone="attention"], QComboBox[attentionTone="attention"] { border: 1px solid #efc27d; background: #1d1a16; }
QLineEdit[attentionTone="error"], QComboBox[attentionTone="error"] { border: 1px solid #f08a8a; background: #211719; }
QLineEdit:read-only { color: #9bb0b6; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #202a2f; color: #e5eeee; selection-background-color: #345348; border: 1px solid #46565d; padding: 5px; }
QCheckBox { spacing: 8px; color: #b9c7ca; font-size: 12px; }
QCheckBox:hover, QCheckBox:focus { color: #e4ecee; }
QCheckBox:disabled { color: #6f7c81; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #56676e; border-radius: 4px; background: #131c21; }
QCheckBox:focus::indicator { border-color: #8ae6bf; }
QCheckBox::indicator:checked { background: #8ae6bf; border-color: #8ae6bf; image: none; }
QScrollArea { border: none; background: transparent; }
QWidget#configBody { background: transparent; }
QPlainTextEdit { background: transparent; color: #a7b8bf; border: 1px solid transparent; border-radius: 8px; font-size: 12px; selection-background-color: #345348; }
QPlainTextEdit:focus { border-color: #41544c; }
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


def password_icon(visible: bool) -> QIcon:
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#9fb0b6"), 1.4, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(3, 5, 12, 8))
    painter.setBrush(QColor("#9fb0b6"))
    painter.drawEllipse(QPointF(9, 9), 1.8, 1.8)
    if not visible:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(3, 15), QPointF(15, 3))
    painter.end()
    return QIcon(pixmap)


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
                       "#efc27d" if self.mode == "warning" else
                       "#f08a8a" if self.mode == "error" else "#74878f")
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
        elif self.mode == "error":
            p.drawLine(QPointF(73, 64), QPointF(91, 82))
            p.drawLine(QPointF(91, 64), QPointF(73, 82))
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
                  "skipped": "#83939b", "neutral": "#83939b", "warning": "#efc27d",
                  "error": "#f08a8a"}
        captions = {"pending": "待执行", "done": "已完成", "active": "进行中",
                    "skipped": "无需执行", "neutral": "未确认", "warning": "待处理",
                    "error": "失败"}
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
        self.window = window
        self.stage = 0
        self.log_entries = []
        self.last_event = ""
        self.states = ["pending"] * 5
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(12)
        hero = card("hero"); hero.setMinimumHeight(200); hero_box = QHBoxLayout(hero); hero_box.setContentsMargins(24, 16, 10, 16)
        text = QVBoxLayout(); text.setSpacing(10)
        self.kicker = label("连接状态 / CONNECTION", "eyebrow")
        self.headline = label("准备连接", "headline")
        self.headline.setWordWrap(True)
        window.status_label = label("启动后会自动检查当前网络。", "detail", True)
        window.status_label.setMinimumHeight(40)
        self.chip_layout = QHBoxLayout(); self.chip_layout.setSpacing(6)
        self.chip_labels = []
        for _ in range(4):
            chip = label("", "statusChip")
            chip.hide()
            self.chip_labels.append(chip)
            self.chip_layout.addWidget(chip)
        self.chip_layout.addStretch()
        self.base_chips: tuple[tuple[str, str], ...] = (("neutral", "准备中"),)
        self.runtime_chip: tuple[str, str] | None = None
        window.scene_label = label("当前场景：等待检查", "muted", True)
        self.elapsed = label("后台守护 · 无需保持窗口打开", "muted")
        context_row = QHBoxLayout(); context_row.setSpacing(10)
        context_row.addWidget(window.scene_label)
        context_row.addStretch()
        context_row.addWidget(self.elapsed)
        text.addWidget(self.kicker)
        text.addWidget(self.headline)
        text.addWidget(window.status_label)
        text.addLayout(self.chip_layout)
        text.addLayout(context_row)
        self._render_chips()
        self.orb = NetworkOrb()
        hero_box.addLayout(text, 1); hero_box.addWidget(self.orb)
        layout.addWidget(hero)

        # The exact portal/entrance state remains available to diagnostics and
        # tests but is intentionally not shown on the status page. Technical
        # endpoint details belong to Settings > Advanced.
        window.active_entrance_label = label("当前认证入口：等待识别", "muted", True)
        window.active_entrance_label.setParent(self)
        window.active_entrance_label.hide()
        process_header = QHBoxLayout(); process_header.addWidget(label("连接流程", "sectionTitle")); process_header.addStretch()
        self.flow_note = label("仅展示实际执行的步骤", "muted")
        process_header.addWidget(self.flow_note); layout.addLayout(process_header)
        self.track = ProcessTrack(); layout.addWidget(self.track)
        recent_card = card("recentCard")
        recent_box = QVBoxLayout(recent_card); recent_box.setContentsMargins(18, 13, 18, 13); recent_box.setSpacing(8)
        recent_header = QHBoxLayout(); recent_header.addWidget(label("最近活动", "sectionTitle")); recent_header.addStretch()
        recent_header.addWidget(button("查看全部 ›", lambda: window.show_page("records"), "quiet"))
        recent_box.addLayout(recent_header)
        self.recent = label("暂无活动", "recentActivity", True)
        self.recent.setMinimumHeight(40)
        recent_box.addWidget(self.recent)
        layout.addWidget(recent_card)

        # Full session log belongs to the dedicated Records page. Keep the
        # widget owned by Dashboard so one event stream feeds both surfaces.
        self.events = QPlainTextEdit(); self.events.setReadOnly(True); self.events.setMaximumBlockCount(160)
        self.events.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.events.setAccessibleName("本次连接过程运行记录")
        countdown_row = QHBoxLayout(); countdown_row.setSpacing(12)
        countdown_row.addWidget(label("下次检查", "muted"))
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
        self.primary_action_name = "立即检查"
        self.secondary_action_name = "暂停守护"
        self.primary_action_button = button("立即检查", self.trigger_primary_action, "primary")
        self.secondary_action_button = button("暂停守护", self.trigger_secondary_action)
        controls.addWidget(self.primary_action_button)
        controls.addWidget(self.secondary_action_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.add_event("助手已启动，等待本轮网络检查。")

    def _render_chips(self):
        specs = list(self.base_chips)
        if self.runtime_chip and self.runtime_chip not in specs:
            specs.append(self.runtime_chip)
        for index, chip in enumerate(self.chip_labels):
            if index >= len(specs):
                chip.hide()
                continue
            tone, text = specs[index]
            chip.setText(text)
            chip.setProperty("tone", tone)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            chip.show()

    def set_base_chips(self, chips: tuple[tuple[str, str], ...]):
        self.base_chips = chips
        self._render_chips()

    def set_runtime_chip(self, chip: tuple[str, str] | None):
        self.runtime_chip = chip
        self._render_chips()

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
        if hasattr(self, "recent"):
            self.recent.setText("\n".join(self.log_entries[-3:]))

    def begin(self, reason):
        self.stage = 0; self.states = ["pending"] * 5
        self.track.set_states(self.states)
        self.headline.setText("正在检查网络")
        self.orb.set_mode("working")
        self.set_base_chips((("working", "正在检查"),))
        self.flow_note.setText("正在处理本轮连接")
        self.set_actions(None, "暂停守护")
        self.add_event({"startup": "开始启动检查", "heartbeat": "开始周期检查", "network": "网络发生变化，重新检查",
                        "midnight": "午夜恢复窗口开始", "midnight_extra": "午夜恢复进入快速检查阶段", "retry": "开始手动重试",
                        "wake": "设备唤醒，重新检查"}.get(reason, "开始网络检查"))

    def progress(self, phase, message):
        index = {"probe": 0, "scene": 1, "config": 2, "auth": 3, "verify": 4}.get(phase, 0)
        if self.states[self.stage] == "active" and index != self.stage:
            self.states[self.stage] = "done"
        self.stage = index
        self.states[index] = "active"
        self.track.set_states(self.states)
        self.headline.setText(("正在探测网络", "正在识别场景", "正在读取配置", "正在进行认证", "正在验证连接")[index])
        self.orb.set_mode("working")
        self.set_base_chips((("working", "正在检查"),))
        self.add_event(message)

    def finish(self, outcome: Outcome, submitted=False):
        presentation = present_outcome(outcome, stage=self.stage, submitted=submitted)
        self.last_presentation = presentation
        self.headline.setText(presentation.title)
        self.orb.set_mode(presentation.orb_mode)
        self.states = list(presentation.steps)
        self.track.set_states(self.states)
        self.flow_note.setText(presentation.flow_note)
        self.elapsed.setText(presentation.support_text)
        self.set_base_chips(presentation.chips)
        self.action_reason = outcome.reason
        self.set_actions(presentation.primary_action, presentation.secondary_action)
        self.add_event(outcome.message)
        return presentation

    def set_actions(self, primary: str | None, secondary: str | None):
        self.primary_action_name = primary
        self.secondary_action_name = secondary
        self.primary_action_button.setVisible(bool(primary))
        self.secondary_action_button.setVisible(bool(secondary))
        if primary:
            self.primary_action_button.setText(primary)
        if secondary:
            self.secondary_action_button.setText(secondary)

    def _run_action(self, name: str | None):
        if not name:
            return
        if name in {"立即检查", "重新检查"}:
            self.window.start_check()
        elif name == "重新尝试":
            self.window.retry()
        elif name in {"暂停守护", "恢复守护"}:
            self.window.toggle_pause()
        elif name in {"完善配置", "修改账号"}:
            self.window.open_settings_for_reason(getattr(self, "action_reason", ""))

    def trigger_primary_action(self):
        self._run_action(self.primary_action_name)

    def trigger_secondary_action(self):
        self._run_action(self.secondary_action_name)


def build_workspace(window):
    window.setStyleSheet(STYLE.replace("'.AppleSystemUIFont', 'PingFang SC', sans-serif", ui_font_stack()))
    metrics = window_metrics()
    window.resize(*metrics["default"])
    window.setMinimumSize(*metrics["minimum"])
    root = QWidget(); root.setObjectName("workspace")
    layout = QVBoxLayout(root); layout.setContentsMargins(24, 18, 24, 15); layout.setSpacing(15)

    header = QHBoxLayout(); header.setSpacing(10)
    brand = QVBoxLayout(); brand.setSpacing(2)
    brand.addWidget(label("校园网助手", "brand"))
    brand.addWidget(label("让连接自动发生，让状态一眼可知。", "muted"))
    header.addLayout(brand)
    header.addStretch()

    window.nav_buttons = {}
    window.nav_shortcut_actions = {}
    shortcuts = navigation_shortcuts()
    nav = QHBoxLayout(); nav.setSpacing(3)
    for title, key in (("状态", "status"), ("设置", "settings"), ("记录", "records")):
        item = button(title, lambda checked=False, page=key: window.show_page(page), "nav")
        item.setCheckable(True)
        item.setAccessibleName(title + "页面")
        item.setToolTip(f"{title}（{shortcuts[key]}）")
        window.nav_buttons[key] = item
        nav.addWidget(item)

        shortcut_action = QAction(window)
        shortcut_action.setShortcut(QKeySequence(shortcuts[key]))
        shortcut_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        shortcut_action.triggered.connect(lambda checked=False, page=key: window.show_page(page))
        window.addAction(shortcut_action)
        window.nav_shortcut_actions[key] = shortcut_action
    header.addLayout(nav)
    header.addSpacing(6)
    window.ui_badge = label(platform_name() + " · 后台守护", "badge")
    header.addWidget(window.ui_badge)
    layout.addLayout(header)

    stack = QStackedWidget(); window.page_stack = stack; window.page_indices = {}

    status_page = QWidget()
    status_layout = QVBoxLayout(status_page); status_layout.setContentsMargins(0, 0, 0, 0)
    window.dashboard = Dashboard(window)
    status_layout.addWidget(window.dashboard)
    window.page_indices["status"] = stack.addWidget(status_page)

    settings_page = QWidget()
    settings_outer = QHBoxLayout(settings_page); settings_outer.setContentsMargins(0, 0, 0, 0)
    settings_outer.addStretch()
    config_card = card("configCard"); config_card.setMaximumWidth(720); config_card.setMinimumWidth(600)
    config_box = QVBoxLayout(config_card); config_box.setContentsMargins(22, 18, 22, 18); config_box.setSpacing(10)
    title_row = QHBoxLayout()
    title_row.addWidget(label("连接设置", "sectionTitle")); title_row.addStretch()
    title_row.addWidget(label("保存后立即生效", "muted"))
    config_box.addLayout(title_row)
    config_box.addWidget(label("通常只需首次配置；运行状态请在“状态”页查看。", "muted", True))

    scroll = QScrollArea(); window.config_scroll = scroll
    scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    config_body = QWidget(); config_body.setObjectName("configBody")
    settings = QVBoxLayout(config_body); settings.setContentsMargins(0, 0, 8, 0); settings.setSpacing(8)

    settings.addWidget(label("常用设置", "sectionTitle"))
    settings.addWidget(label("推荐保持自动识别；助手会根据网络环境自行决定是否认证。", "muted", True))
    window.profile = SelectBox()
    for title, value in (("自动识别公共网 / 宿舍网", "auto"), ("仅使用公共网", "public"), ("仅使用宿舍网", "dorm")):
        window.profile.addItem(title, value)
    settings.addWidget(label("认证场景", "muted")); settings.addWidget(window.profile)
    window.enabled = CheckBox("自动检查并认证")
    window.autostart = CheckBox(startup_text())
    common_switches = QHBoxLayout(); common_switches.setSpacing(18)
    common_switches.addWidget(window.enabled); common_switches.addWidget(window.autostart); common_switches.addStretch()
    settings.addLayout(common_switches)

    settings.addSpacing(6)
    settings.addWidget(label("登录信息", "sectionTitle"))
    settings.addWidget(label("账号和服务商只在校园网需要认证时使用。", "muted", True))

    window.edit_profile = SelectBox()
    window.edit_profile.addItem("公共网配置", "public"); window.edit_profile.addItem("宿舍网配置", "dorm")
    window.cred_mode = SelectBox()
    window.cred_mode.addItem("两场景共用账号与密码", "shared")
    window.cred_mode.addItem("为两个场景分别保存账号", "separate")
    selector_form = QFormLayout()
    selector_form.setHorizontalSpacing(14); selector_form.setVerticalSpacing(8)
    selector_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    selector_form.addRow("配置", window.edit_profile)
    selector_form.addRow("账号方式", window.cred_mode)
    settings.addLayout(selector_form)

    login_form = QFormLayout(); window.form = login_form; window.login_form = login_form
    login_form.setHorizontalSpacing(14); login_form.setVerticalSpacing(8)
    login_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    window.password_actions = {}

    def add_to(form, key, title, secret=False):
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
        edit.setAccessibleName(title)
        if secret:
            action = QAction(password_icon(False), "显示密码", edit)
            action.setToolTip("显示密码")
            edit.addAction(action, QLineEdit.ActionPosition.TrailingPosition)
            def toggle_password(_checked=False, field=edit, control=action):
                show = field.echoMode() == QLineEdit.EchoMode.Password
                field.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
                control.setIcon(password_icon(show))
                control.setText("隐藏密码" if show else "显示密码")
                control.setToolTip(control.text())
            action.triggered.connect(toggle_password)
            window.password_actions[key] = action
        window.fields[key] = edit
        form.addRow(title, edit)

    add_to(login_form, "username", "共用账号")
    add_to(login_form, "password", "共用密码", True)
    add_to(login_form, "public_username", "公共网账号")
    add_to(login_form, "public_password", "公共网密码", True)
    add_to(login_form, "dorm_username", "宿舍网账号")
    add_to(login_form, "dorm_password", "宿舍网密码", True)

    window.dorm_provider = SelectBox()
    for title, value in DORM_PROVIDERS:
        window.dorm_provider.addItem(title, value)
    login_form.addRow("宿舍服务商", window.dorm_provider)
    window.dorm_provider.currentIndexChanged.connect(window.dorm_provider_changed)
    settings.addLayout(login_form)

    settings.addSpacing(4)
    window.advanced_toggle = button("高级设置  ▸", lambda: None, "quiet")
    window.advanced_toggle.setCheckable(True)
    settings.addWidget(window.advanced_toggle)

    advanced_form = QFormLayout(); window.advanced_form = advanced_form
    advanced_form.setHorizontalSpacing(14); advanced_form.setVerticalSpacing(10)
    advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    add_to(advanced_form, "portal_url", "认证入口")
    add_to(advanced_form, "public_suffix", "公共网后缀")
    add_to(advanced_form, "dorm_suffix", "宿舍网后缀")
    window.fields["dorm_suffix"].setReadOnly(True)
    window.follow_scene = CheckBox("自动显示当前网络对应的配置")
    window.follow_scene.setChecked(True)
    window.follow_scene.toggled.connect(window.follow_scene_changed)
    advanced_form.addRow("界面联动", window.follow_scene)
    settings.addLayout(advanced_form)

    def advanced_changed(opened):
        window.advanced_toggle.setText("高级设置  ▾" if opened else "高级设置  ▸")
        window.apply_mode_visibility()
    window.advanced_toggle.toggled.connect(advanced_changed)

    settings.addStretch(1)
    scroll.setWidget(config_body); config_box.addWidget(scroll, 1)

    window.warning = label("密码仅保存在本机配置文件中，不上传到其他服务器。", "configWarning", True)
    window.warning.setToolTip("配置保存于：" + str(window._ui_config_path))
    config_box.addWidget(window.warning)

    save_meta = QHBoxLayout()
    window.save_state_label = label("已保存", "saveStatus")
    save_meta.addWidget(window.save_state_label); save_meta.addStretch()
    config_box.addLayout(save_meta)

    save_row = QHBoxLayout(); save_row.setSpacing(10)
    window.save_button = button("保存修改", window.save, "primary")
    window.discard_button = button("放弃修改", window.discard_changes)
    save_row.addWidget(window.save_button, 1)
    save_row.addWidget(window.discard_button, 1)
    config_box.addLayout(save_row)

    links = QHBoxLayout()
    links.addWidget(button("重载配置文件", window.reload_config, "quiet"))
    links.addWidget(button("打开登录页", window.open_portal, "quiet"))
    links.addWidget(button("配置文件夹", window.open_folder, "quiet"))
    links.addStretch()
    config_box.addLayout(links)

    for item in (window.profile, window.edit_profile, window.cred_mode, window.dorm_provider):
        item.currentIndexChanged.connect(window.mark_config_dirty)
    for item in (window.enabled, window.autostart, window.follow_scene):
        item.toggled.connect(window.mark_config_dirty)
    for item in window.fields.values():
        item.textEdited.connect(window.mark_config_dirty)

    settings_outer.addWidget(config_card, 1)
    settings_outer.addStretch()
    window.page_indices["settings"] = stack.addWidget(settings_page)

    records_page = QWidget()
    records_outer = QHBoxLayout(records_page); records_outer.setContentsMargins(0, 0, 0, 0)
    records_outer.addStretch()
    record_card = card("recordCard"); record_card.setMaximumWidth(760); record_card.setMinimumWidth(620)
    record_box = QVBoxLayout(record_card); record_box.setContentsMargins(22, 20, 22, 18); record_box.setSpacing(12)
    record_header = QHBoxLayout()
    record_header.addWidget(label("运行记录", "sectionTitle")); record_header.addStretch()
    record_header.addWidget(label("本次会话 · 最多保留 160 条", "muted"))
    record_box.addLayout(record_header)
    window.dashboard.events.setMinimumHeight(420)
    record_box.addWidget(window.dashboard.events, 1)
    record_actions = QHBoxLayout()
    record_actions.addWidget(button("立即检查", window.start_check))
    record_actions.addWidget(button("打开配置文件夹", window.open_folder, "quiet"))
    record_actions.addStretch()
    record_box.addLayout(record_actions)
    records_outer.addWidget(record_card, 1)
    records_outer.addStretch()
    window.page_indices["records"] = stack.addWidget(records_page)

    QWidget.setTabOrder(window.nav_buttons["status"], window.nav_buttons["settings"])
    QWidget.setTabOrder(window.nav_buttons["settings"], window.nav_buttons["records"])
    QWidget.setTabOrder(window.profile, window.enabled)
    QWidget.setTabOrder(window.enabled, window.autostart)
    QWidget.setTabOrder(window.autostart, window.edit_profile)
    QWidget.setTabOrder(window.edit_profile, window.cred_mode)
    QWidget.setTabOrder(window.cred_mode, window.fields["username"])
    QWidget.setTabOrder(window.fields["username"], window.fields["password"])
    QWidget.setTabOrder(window.fields["password"], window.advanced_toggle)
    QWidget.setTabOrder(window.advanced_toggle, window.save_button)
    QWidget.setTabOrder(window.save_button, window.discard_button)

    layout.addWidget(stack, 1)

    footer = QHBoxLayout()
    footer.addWidget(label("●  " + background_text(), "muted")); footer.addStretch()
    footer.addWidget(label(f"v{__version__} · 自动守护中", "muted"))
    footer.addWidget(button("退出助手", window.quit_app, "quiet"))
    layout.addLayout(footer)

    window.setCentralWidget(root)
    window.profile.currentIndexChanged.connect(window.profile_changed)
    window.edit_profile.currentIndexChanged.connect(window.edit_profile_changed)
    window.last_edit_profile = window.edit_profile.currentData() or "public"
    window.cred_mode.currentIndexChanged.connect(window.apply_mode_visibility)
    window.show_page("status")
