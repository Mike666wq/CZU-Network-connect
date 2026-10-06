from campus_assistant.engine import Outcome, State
from campus_assistant.presentation import present_outcome


def test_online_scene_unknown_semantics_do_not_depend_on_localized_message():
    first = present_outcome(Outcome(
        State.ONLINE, "互联网可用；公共网和宿舍网入口均未识别", 600,
        reason="online_scene_unknown"))
    second = present_outcome(Outcome(
        State.ONLINE, "这段文案以后可以完全改写", 600,
        reason="online_scene_unknown"))
    assert first.title == second.title == "已连接互联网"
    assert first.steps == second.steps == (
        "done", "neutral", "skipped", "skipped", "done")
    assert first.primary_action == "立即检查"


def test_already_online_marks_config_checked_but_auth_submission_skipped():
    model = present_outcome(Outcome(
        State.ONLINE, "账号此前已认证且互联网已连通", 600,
        reason="already_online"))
    assert model.steps == ("done", "done", "done", "skipped", "done")
    assert model.detail == "校园网已处于认证状态，无需重复登录。"


def test_configuration_and_account_failures_have_distinct_user_actions():
    config = present_outcome(Outcome(
        State.NEEDS_CONFIG, "缺少配置", 600, reason="provider_missing"))
    blocked = present_outcome(Outcome(
        State.AUTH_BLOCKED, "账号不可用", 600, reason="account"))
    assert config.title == "还差一步配置"
    assert config.primary_action == "完善配置"
    assert config.steps == ("done", "done", "warning", "pending", "pending")
    assert blocked.title == "认证未通过"
    assert blocked.primary_action == "修改账号"
    assert blocked.orb_mode == "error"
    assert blocked.steps == ("done", "done", "done", "error", "pending")


def test_portal_unidentified_and_verified_portal_failure_are_not_same_state():
    unidentified = present_outcome(Outcome(
        State.WAITING, "没有识别到校园门户", 60,
        reason="portal_unidentified"), stage=1)
    verified = present_outcome(Outcome(
        State.PORTAL, "认证成功但公网仍不可用", 30,
        reason="authenticated_no_internet"), stage=4)
    assert unidentified.steps == ("done", "warning", "pending", "pending", "pending")
    assert verified.steps == ("done", "done", "done", "done", "warning")
    assert unidentified.title == "等待校园网络"
    assert verified.title == "等待互联网恢复"


def test_configuration_save_and_resume_are_transient_semantic_states():
    saved = present_outcome(Outcome(
        State.WAITING, "配置已保存并生效", 600,
        reason="configuration_saved"))
    resumed = present_outcome(Outcome(
        State.WAITING, "已恢复，即将重新检查", 600,
        reason="resumed"))
    assert saved.title == "配置已保存"
    assert saved.flow_note == "即将重新检查"
    assert resumed.title == "自动守护已恢复"
    assert resumed.orb_mode == "working"


def test_every_major_state_has_complete_user_facing_semantics():
    cases = [
        Outcome(State.AUTHENTICATED, 'ok', 600, reason='authenticated'),
        Outcome(State.ONLINE, 'online', 600, reason='online_scene_known'),
        Outcome(State.NEEDS_CONFIG, 'missing', 600, reason='provider_missing'),
        Outcome(State.AUTH_BLOCKED, 'bad account', 600, reason='account'),
        Outcome(State.PORTAL, 'waiting', 30, reason='authenticated_no_internet'),
        Outcome(State.WAITING, 'waiting', 60, reason='portal_unidentified'),
        Outcome(State.PAUSED, 'paused', 60, reason='paused'),
        Outcome(State.STOPPED, 'stopped', 60, reason='stopped'),
        Outcome(State.ERROR, 'error', 30, reason='worker_exception'),
    ]
    for outcome in cases:
        model = present_outcome(outcome, stage=2)
        assert model.title
        assert model.detail
        assert len(model.steps) == 5
        assert model.flow_note
        assert model.support_text
        assert all(tone in {'success', 'working', 'attention', 'error', 'neutral'}
                   for tone, _text in model.chips)
