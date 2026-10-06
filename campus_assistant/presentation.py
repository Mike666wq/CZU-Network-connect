"""Pure presentation semantics for the desktop UI.

This module translates explicit engine result codes into user-facing UI state.
It contains no Qt imports and performs no network or configuration work.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import Outcome, State


StepState = str


@dataclass(frozen=True)
class UiPresentation:
    title: str
    detail: str
    severity: str
    orb_mode: str
    steps: tuple[StepState, StepState, StepState, StepState, StepState]
    flow_note: str
    support_text: str
    primary_action: str | None
    secondary_action: str | None
    chips: tuple[tuple[str, str], ...] = ()


def _warning_at(stage: int) -> tuple[StepState, StepState, StepState, StepState, StepState]:
    states = ["pending"] * 5
    states[max(0, min(4, stage))] = "warning"
    return tuple(states)  # type: ignore[return-value]


def _error_at(stage: int) -> tuple[StepState, StepState, StepState, StepState, StepState]:
    states = ["pending"] * 5
    states[max(0, min(4, stage))] = "error"
    return tuple(states)  # type: ignore[return-value]


def present_outcome(outcome: Outcome, *, stage: int = 0, submitted: bool = False) -> UiPresentation:
    """Map one explicit engine outcome to stable UI semantics.

    The mapping intentionally uses outcome.reason/state rather than matching
    localized message text. The message remains safe detail text for
    server/configuration specifics, but never controls the UI state machine.
    """
    state, reason = outcome.state, outcome.reason

    if state == State.AUTHENTICATED:
        return UiPresentation(
            "认证成功，已连接",
            "校园网认证完成，互联网连接已恢复。",
            "success", "success",
            ("done", "done", "done", "done", "done"),
            "本轮已完成",
            "后台守护中 · 将按计划再次检查",
            "立即检查", "暂停守护",
            chips=(("success", "已认证"), ("success", "网络已恢复")),
        )

    if state == State.ONLINE:
        if reason == "online_scene_unknown":
            steps = ("done", "neutral", "skipped", "skipped", "done")
            detail = "当前互联网可用；校园场景未确认，但无需处理。"
        elif reason == "already_online":
            steps = ("done", "done", "done", "skipped", "done")
            detail = "校园网已处于认证状态，无需重复登录。"
        else:
            steps = ("done", "done", "skipped", "skipped", "done")
            detail = "网络状态正常，本轮无需重新认证。"
        chips = (
            (("success", "稳定在线"), ("neutral", "场景未确认"))
            if reason == "online_scene_unknown"
            else (("success", "稳定在线"), ("neutral", "自动守护"))
        )
        return UiPresentation(
            "已连接互联网", detail, "success", "success", steps,
            "本轮已完成", "后台守护中 · 将按计划再次检查",
            "立即检查", "暂停守护", chips=chips,
        )

    if state == State.NEEDS_CONFIG:
        return UiPresentation(
            "还差一步配置", outcome.message,
            "attention", "warning",
            ("done", "done", "warning", "pending", "pending"),
            "需要补充配置", "补充配置后即可继续自动认证",
            "完善配置", "暂停守护",
            chips=(("attention", "需要配置"), ("neutral", "认证未提交")),
        )

    if state == State.AUTH_BLOCKED:
        return UiPresentation(
            "认证未通过", outcome.message,
            "error", "error",
            ("done", "done", "done", "error", "pending"),
            "认证已停止", "修正账号或状态后再重新尝试",
            "修改账号", "重新尝试",
            chips=(("error", "认证失败"), ("attention", "自动认证已暂停")),
        )

    if state == State.PORTAL:
        steps = (
            ("done", "done", "done", "skipped", "warning")
            if reason == "already_online_no_internet"
            else ("done", "done", "done", "done", "warning")
        )
        return UiPresentation(
            "等待互联网恢复", outcome.message,
            "attention", "warning", steps,
            "等待网络恢复", "校园门户可用，但互联网验证尚未通过",
            "重新检查", "暂停守护",
            chips=(("attention", "等待网络恢复"),),
        )

    if state == State.WAITING:
        if reason in {"configuration_saved", "configuration_reloaded"}:
            title = "配置已保存" if reason == "configuration_saved" else "配置已重载"
            return UiPresentation(
                title, outcome.message,
                "neutral", "idle",
                ("pending", "pending", "pending", "pending", "pending"),
                "即将重新检查", "新的配置会在下一轮检查中生效",
                "立即检查", "暂停守护",
                chips=(("neutral", "配置已更新"),),
            )
        if reason == "resumed":
            return UiPresentation(
                "自动守护已恢复", outcome.message,
                "working", "working",
                ("pending", "pending", "pending", "pending", "pending"),
                "即将重新检查", "正在恢复后台守护",
                None, "暂停守护",
                chips=(("working", "正在恢复"),),
            )
        steps = (
            ("done", "warning", "pending", "pending", "pending")
            if reason == "portal_unidentified"
            else _warning_at(stage)
        )
        return UiPresentation(
            "等待校园网络", outcome.message,
            "neutral", "idle", steps,
            "等待网络变化", "助手会按计划继续检查",
            "重新检查", "暂停守护",
            chips=(("neutral", "等待校园网"),),
        )

    if state == State.PAUSED:
        return UiPresentation(
            "自动检查已暂停", outcome.message,
            "neutral", "idle", _warning_at(stage),
            "守护已暂停", "恢复后将立即重新检查",
            "恢复守护", "立即检查",
            chips=(("neutral", "守护已暂停"),),
        )

    if state == State.STOPPED:
        return UiPresentation(
            "后台守护已停止", outcome.message,
            "neutral", "idle", _warning_at(stage),
            "已停止", "重新启动应用后恢复自动守护",
            None, None,
            chips=(("neutral", "后台已停止"),),
        )

    if state == State.ERROR:
        return UiPresentation(
            "暂时无法连接", outcome.message,
            "error", "error", _error_at(stage),
            "本轮检查未完成", "助手会按退避策略再次检查",
            "重新检查", "暂停守护",
            chips=(("error", "检查失败"), ("neutral", "将自动重试")),
        )

    return UiPresentation(
        "正在检查网络", outcome.message,
        "working", "working", _warning_at(stage),
        "正在处理本轮连接", "请稍候",
        None, "暂停守护",
        chips=(("working", "正在检查"),),
    )
