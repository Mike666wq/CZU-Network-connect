"""Presentation-only regression tests; use the fake-network GUI fixture."""
from PySide6.QtCore import QPoint
from campus_assistant.engine import Outcome, State
from test_gui_regression import gui  # noqa: F401 - share offline fixture


def test_status_settings_and_records_are_separate_pages(gui):
    w = gui.window
    w.show(); gui.app.processEvents()
    assert w.page_stack.count() == 3
    assert w.page_stack.currentIndex() == w.page_indices['status']
    assert w.nav_buttons['status'].isChecked()
    assert not w.fields['portal_url'].isVisible()
    assert w.dashboard.events.isReadOnly()

    w.show_page('settings'); gui.app.processEvents()
    assert w.nav_buttons['settings'].isChecked()
    assert w.fields['username'].isVisible()
    assert not w.fields['portal_url'].isVisible()  # advanced settings are collapsed by default
    w.advanced_toggle.setChecked(True); gui.app.processEvents()
    assert w.fields['portal_url'].isVisible()

    w.show_page('records'); gui.app.processEvents()
    assert w.nav_buttons['records'].isChecked()
    assert w.dashboard.events.isVisible()
    assert w.follow_scene.isChecked()


def test_progress_keeps_full_session_history(gui):
    dashboard = gui.window.dashboard
    dashboard.begin('startup')
    for phase, message in [
        ('probe', '正在检测互联网（探测 1/2）'),
        ('scene', '正在识别公共网门户'),
        ('scene', '正在识别宿舍网门户'),
        ('config', '正在查询校园网是否已认证'),
        ('config', '正在读取校园门户登录配置'),
        ('auth', '正在提交校园网认证'),
        ('verify', '正在验证互联网是否连通'),
    ]:
        dashboard.progress(phase, message)
    text = dashboard.events.toPlainText()
    assert '正在识别公共网门户' in text and '正在识别宿舍网门户' in text
    assert '正在读取校园门户登录配置' in text and '正在提交校园网认证' in text
    assert dashboard.track.states == ['done', 'done', 'done', 'done', 'active']


def test_success_after_submission_marks_complete_but_online_check_skips_auth(gui):
    dashboard = gui.window.dashboard
    dashboard.finish(Outcome(State.AUTHENTICATED, '认证成功且互联网已连通', 600,
                             reason='authenticated'), submitted=True)
    assert dashboard.track.states == ['done'] * 5
    assert dashboard.orb.mode == 'success'
    dashboard.begin('heartbeat')
    dashboard.finish(Outcome(State.ONLINE, '互联网可用；当前场景：宿舍网；本轮未提交校园登录',
                             600, reason='online_scene_known'))
    assert dashboard.track.states[2:4] == ['skipped', 'skipped']
    assert '已连接' in dashboard.headline.text()


def test_configuration_error_keeps_auth_pending_not_success(gui):
    dashboard = gui.window.dashboard
    dashboard.begin('startup')
    dashboard.progress('scene', '正在识别宿舍网门户')
    dashboard.finish(Outcome(State.NEEDS_CONFIG, '请先选择宿舍服务商并保存，未发送凭据',
                             600, reason='provider_missing'))
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
    w.dashboard.finish(Outcome(State.PAUSED, '已暂停', 60, reason='paused'))
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
    dashboard.finish(Outcome(State.ONLINE, '互联网可用；公共网和宿舍网入口均未识别，可能不在校园网',
                             600, reason='online_scene_unknown'))
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


def test_dashboard_actions_follow_presentation_state(gui):
    w = gui.window
    dashboard = w.dashboard

    dashboard.finish(Outcome(State.ONLINE, 'ok', 600, reason='online_scene_known'))
    assert dashboard.primary_action_button.text() == '立即检查'
    assert dashboard.secondary_action_button.text() == '暂停守护'
    assert not dashboard.primary_action_button.isHidden()
    assert not dashboard.secondary_action_button.isHidden()

    dashboard.finish(Outcome(State.NEEDS_CONFIG, 'missing provider', 600, reason='provider_missing'))
    assert dashboard.primary_action_button.text() == '完善配置'
    assert dashboard.secondary_action_button.text() == '暂停守护'

    dashboard.finish(Outcome(State.AUTH_BLOCKED, 'bad credentials', 600, reason='account'))
    assert dashboard.primary_action_button.text() == '修改账号'
    assert dashboard.secondary_action_button.text() == '重新尝试'
    assert dashboard.orb.mode == 'error'


def test_status_chips_follow_semantic_outcome(gui):
    w = gui.window
    dashboard = w.dashboard

    dashboard.finish(Outcome(State.ONLINE, 'online', 600, reason='online_scene_unknown'))
    visible = [chip.text() for chip in dashboard.chip_labels if not chip.isHidden()]
    assert visible[:2] == ['稳定在线', '场景未确认']

    dashboard.finish(Outcome(State.AUTH_BLOCKED, 'bad account', 600, reason='account'))
    visible = [chip.text() for chip in dashboard.chip_labels if not chip.isHidden()]
    assert visible[:2] == ['认证失败', '自动认证已暂停']


def test_configuration_cta_navigates_only_when_user_requests_it(gui):
    w = gui.window
    w.show(); gui.app.processEvents()
    w.show_page('status')

    w.set_outcome(Outcome(State.NEEDS_CONFIG, 'missing provider', 600, reason='provider_missing'))
    assert w.page_stack.currentIndex() == w.page_indices['status']
    assert w.dorm_provider.property('attentionTone') == 'attention'

    w.dashboard.trigger_primary_action()
    gui.app.processEvents()
    assert w.page_stack.currentIndex() == w.page_indices['settings']
    assert w.edit_profile.currentData() == 'dorm'
    assert w.dorm_provider.property('attentionTone') == 'attention'


def test_account_cta_marks_credentials_as_error(gui):
    w = gui.window
    w.show_page('status')
    w.set_outcome(Outcome(State.AUTH_BLOCKED, 'bad credentials', 600, reason='account'))
    assert w.page_stack.currentIndex() == w.page_indices['status']
    assert w.fields['username'].property('attentionTone') == 'error'
    assert w.fields['password'].property('attentionTone') == 'error'

    w.dashboard.trigger_primary_action()
    gui.app.processEvents()
    assert w.page_stack.currentIndex() == w.page_indices['settings']
    assert w.fields['username'].property('attentionTone') == 'error'


def test_page_navigation_has_accessible_names_and_shortcuts(gui):
    w = gui.window
    assert w.nav_buttons['status'].accessibleName() == '状态页面'
    assert w.nav_buttons['settings'].accessibleName() == '设置页面'
    assert w.nav_buttons['records'].accessibleName() == '记录页面'
    assert all(not action.shortcut().isEmpty() for action in w.nav_shortcut_actions.values())

    w.nav_shortcut_actions['settings'].trigger()
    assert w.page_stack.currentIndex() == w.page_indices['settings']
    w.nav_shortcut_actions['records'].trigger()
    assert w.page_stack.currentIndex() == w.page_indices['records']
    w.nav_shortcut_actions['status'].trigger()
    assert w.page_stack.currentIndex() == w.page_indices['status']


def test_window_size_is_not_below_platform_minimum(gui):
    w = gui.window
    assert w.width() >= w.minimumWidth()
    assert w.height() >= w.minimumHeight()
    assert w.minimumWidth() >= 820
    assert w.minimumHeight() >= 700
