"""Presentation-only regression tests; use the fake-network GUI fixture."""
from PySide6.QtCore import QPoint
from campus_assistant.engine import State
from test_gui_regression import gui  # noqa: F401 - share offline fixture


def test_left_process_panel_and_right_form_are_separate(gui):
    w = gui.window
    w.show(); gui.app.processEvents()
    assert w.dashboard.mapTo(w, QPoint()).x() < w.fields['portal_url'].mapTo(w, QPoint()).x()
    assert w.dashboard.events.isReadOnly()
    assert w.follow_scene.isChecked()


def test_progress_keeps_full_session_history(gui):
    dashboard = gui.window.dashboard
    dashboard.begin('startup')
    for phase in ['正在检测互联网（探测 1/2）', '正在识别公共网门户', '正在识别宿舍网门户',
                  '正在查询校园网是否已认证', '正在读取校园门户登录配置',
                  '正在提交校园网认证', '正在验证互联网是否连通']:
        dashboard.progress(phase)
    text = dashboard.events.toPlainText()
    assert '正在识别公共网门户' in text and '正在识别宿舍网门户' in text
    assert '正在读取校园门户登录配置' in text and '正在提交校园网认证' in text
    assert dashboard.track.states == ['done', 'done', 'done', 'done', 'active']


def test_success_after_submission_marks_complete_but_online_check_skips_auth(gui):
    dashboard = gui.window.dashboard
    dashboard.finish(State.AUTHENTICATED, '认证成功且互联网已连通', submitted=True)
    assert dashboard.track.states == ['done'] * 5
    assert dashboard.orb.mode == 'success'
    dashboard.begin('heartbeat')
    dashboard.finish(State.ONLINE, '互联网可用；当前场景：宿舍网；本轮未提交校园登录')
    assert dashboard.track.states[2:4] == ['skipped', 'skipped']
    assert '已连接' in dashboard.headline.text()


def test_configuration_error_keeps_auth_pending_not_success(gui):
    dashboard = gui.window.dashboard
    dashboard.begin('startup')
    dashboard.progress('正在识别宿舍网门户')
    dashboard.finish(State.NEEDS_CONFIG, '请先选择宿舍服务商并保存，未发送凭据')
    assert dashboard.track.states == ['done', 'done', 'warning', 'pending', 'pending']
    assert dashboard.orb.mode == 'warning'
    assert dashboard.headline.text() == '还差一步配置'


def test_animation_stops_when_result_arrives_and_when_window_hides(gui):
    w = gui.window
    w.show(); gui.app.processEvents()
    w.dashboard.begin('startup')
    assert w.dashboard.orb.clock.isActive()
    w.hide(); gui.app.processEvents()
    assert not w.dashboard.orb.clock.isActive()
    w.show(); gui.app.processEvents()
    assert w.dashboard.orb.clock.isActive()
    w.dashboard.finish(State.PAUSED, '已暂停')
    assert not w.dashboard.orb.clock.isActive()


def test_session_history_is_bounded_and_does_not_read_credentials(gui):
    w = gui.window
    w.fields['password'].setText('never-log-this-secret')
    w.fields['username'].setText('never-log-this-account')
    for index in range(190):
        w.dashboard.add_event(f'网络步骤 {index}')
    assert len(w.dashboard.log_entries) == 160
    assert w.dashboard.events.document().blockCount() == 160
    assert 'never-log' not in w.dashboard.events.toPlainText()


def test_unknown_scene_is_neutral_when_internet_is_already_available(gui):
    dashboard = gui.window.dashboard
    dashboard.finish(State.ONLINE, '互联网可用；公共网和宿舍网入口均未识别，可能不在校园网')
    assert dashboard.track.states == ['done', 'neutral', 'skipped', 'skipped', 'done']
    assert dashboard.orb.mode == 'success'
    assert dashboard.flow_note.text() == '本轮已完成'


def test_repeat_scene_result_does_not_duplicate_log_after_success(gui):
    w = gui.window
    w.scene_identified('dorm', 'http://dorm.test/', w.supervisor)
    w.dashboard.add_event('认证成功且互联网已连通')
    before = len(w.dashboard.log_entries)
    w.scene_identified('dorm', 'http://dorm.test/', w.supervisor)
    assert len(w.dashboard.log_entries) == before
