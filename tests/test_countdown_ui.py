from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
from types import SimpleNamespace

import pytest

import campus_assistant.gui as main
from campus_assistant.dashboard import countdown_remaining
from campus_assistant.scheduler import PollScheduler
from test_gui_regression import gui  # noqa: F401 - reuse offline GUI fixture

TZ = ZoneInfo('Asia/Shanghai')
WALL = datetime(2026, 10, 5, 19, 0, tzinfo=TZ)


@pytest.mark.parametrize('elapsed,expected', [(0,60), (1,59), (2,58), (59.1,1), (60,0), (65,0)])
def test_countdown_uses_real_deadline_without_negative_seconds(elapsed, expected):
    scheduler = PollScheduler(100, 'fake-network', WALL)
    scheduler.reschedule(100, 60)
    assert countdown_remaining(scheduler, 100+elapsed, WALL) == expected


@pytest.mark.parametrize('wall,expected', [
    (datetime(2026,10,5,23,59,57,tzinfo=TZ),3),
    (datetime(2026,10,6,0,11,58,tzinfo=TZ),2),
    (datetime(2026,10,5,15,59,58,tzinfo=timezone.utc),2),
])
def test_earlier_midnight_extra_is_displayed_instead_of_ordinary_deadline(wall, expected):
    scheduler = PollScheduler(100, 'fake-network', wall)
    scheduler.reschedule(100, 60)
    assert countdown_remaining(scheduler, 100, wall) == expected


def test_special_check_is_not_displayed_as_due_again_after_it_was_handled():
    wall = datetime(2026,10,6,0,12,3,tzinfo=TZ)
    scheduler = PollScheduler(100, 'fake-network', wall)
    scheduler.reschedule(100,60)
    assert countdown_remaining(scheduler,100,wall) == 0
    scheduler.last_minute = wall.strftime('%Y%m%d%H%M')
    assert countdown_remaining(scheduler,101,wall) == 59


def test_countdown_reads_but_does_not_mutate_scheduler():
    scheduler = PollScheduler(100,'fake-network',WALL)
    scheduler.reschedule(100,300)
    before = deepcopy(scheduler.__dict__)
    assert countdown_remaining(scheduler,115,WALL) == 285
    assert scheduler.__dict__ == before


def test_widget_displays_seconds_then_zero_waiting_state(gui):
    w = gui.window
    w.scheduler.reschedule(100,60)
    w.refresh_countdown(101,WALL)
    assert w.countdown_value.text() == '59 秒'
    w.refresh_countdown(102,WALL)
    assert w.countdown_value.text() == '58 秒'
    w.refresh_countdown(165,WALL)
    assert w.countdown_value.text() == '0 秒'
    assert '等待后台调度' in w.schedule_label.text()
    assert gui.starts == []


def test_pause_disabled_checking_and_invalid_config_have_distinct_display(gui):
    w = gui.window
    w.running = True
    w.refresh_countdown(100,WALL)
    assert w.countdown_value.text() == '检查中'
    w.manual_paused = True
    w.refresh_countdown(100,WALL)
    assert w.countdown_value.text() == '已暂停'
    w.manual_paused = False
    w.invalid_config = True
    w.refresh_countdown(100,WALL)
    assert w.countdown_value.text() == '待配置'
    w.config['enabled'] = False
    w.refresh_countdown(100,WALL)
    assert w.countdown_value.text() == '已关闭'
    w.quit_after_check = True
    w.refresh_countdown(100,WALL)
    assert w.countdown_value.text() == '退出中'
    w.running = False


def test_unsaved_checkbox_does_not_change_actual_schedule_display(gui):
    w = gui.window
    w.scheduler.reschedule(100,60)
    w.enabled.setChecked(False)
    w.refresh_countdown(101,WALL)
    assert w.countdown_value.text() == '59 秒'
    assert w.config['enabled'] is True


def test_countdown_resets_after_scheduler_reschedules_not_from_fixed_sixty(gui):
    w = gui.window
    w.scheduler.reschedule(100,60)
    w.refresh_countdown(115,WALL)
    assert w.countdown_value.text() == '45 秒'
    w.scheduler.reschedule(115,30)
    w.refresh_countdown(115,WALL)
    assert w.countdown_value.text() == '30 秒'
    w.scheduler.reschedule(115,300)
    w.supervisor.auth_blocked = True
    w.refresh_countdown(116,WALL)
    assert w.countdown_value.text() == '299 秒'
    assert '仅' not in w.countdown_value.text()
    assert '仍会检查网络' in w.schedule_label.text()


def test_real_qt_display_timer_updates_without_starting_a_network_check(gui,monkeypatch):
    w = gui.window
    calls = []
    def remaining(*args):
        calls.append('render')
        return 60-len(calls)
    monkeypatch.setattr(main,'countdown_remaining',remaining)
    before = w.scheduler.deadline
    w.show(); gui.app.processEvents()
    assert w.countdown_timer.interval() == 1000
    w.countdown_timer.setInterval(20)  # accelerate only this test's presentation timer
    deadline = time.monotonic()+0.5
    while len(calls)<2 and time.monotonic()<deadline:
        gui.app.processEvents()
        time.sleep(0.005)
    assert len(calls)>=2
    assert w.countdown_value.text() == f'{60-len(calls)} 秒'
    assert gui.starts == []
    assert w.scheduler.deadline == before


def test_closing_to_tray_does_not_stop_background_scheduler(gui,monkeypatch):
    w = gui.window
    monkeypatch.setattr(w.tray,'isSystemTrayAvailable',lambda:True)
    ignored,accepted=[],[]
    event=SimpleNamespace(ignore=lambda:ignored.append(True),accept=lambda:accepted.append(True))
    w.show();gui.app.processEvents()
    w.timer.start(5000)
    w.closeEvent(event)
    assert ignored == [True] and accepted == []
    assert w.timer.isActive() and not w.countdown_timer.isActive()
    assert not w.supervisor.paused
