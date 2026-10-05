from copy import deepcopy
from datetime import datetime, timedelta
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

import pytest

from campus_assistant.protocol import PortalError, PortalResult
from campus_assistant.service import CampusService
from campus_assistant.engine import Supervisor, State
from campus_assistant.scheduler import PollScheduler
from test_protocol_regression import FakeHttp, base_config, portal_page, LOGIN_PATH


class TwoScenes:
    def __init__(self, available=('dorm',), online=0):
        self.available = set(available)
        self.last_headers = {}
        self.calls = []
        self.responses = {}
        for name, host, prefix in [('public', 'portal.test', 1), ('dorm', 'dorm.test', 0)]:
            fake = FakeHttp(portal_page(globals_="v4ip='10.20.30.40';"), online_result=online)
            fake.settings['account_prefix'] = prefix
            self.responses[host] = fake

    def get(self, url, **kwargs):
        self.calls.append(url)
        host = urlsplit(url).hostname
        scene = 'public' if host == 'portal.test' else 'dorm'
        if scene not in self.available:
            raise PortalError('TimeoutError')
        result = self.responses[host].get(url, **kwargs)
        self.last_headers = self.responses[host].last_headers
        return result


def dorm_config(suffix='', confirmed=True, active='dorm'):
    cfg = base_config(active_profile=active)
    cfg['profiles']['dorm'].update(provider_suffix=suffix, provider_confirmed=confirmed)
    return cfg


@pytest.mark.parametrize('suffix', ['', '@cmcc', '@unicom', '@telecom'])
def test_dorm_account_uses_verified_prefix_zero_and_selected_provider(suffix):
    http = TwoScenes()
    svc = CampusService(dorm_config(suffix), http=http)
    assert svc.identify_portal()
    assert svc.authenticate().success
    calls = [u for u in http.calls if urlsplit(u).path == LOGIN_PATH]
    assert len(calls) == 1
    query = parse_qs(urlsplit(calls[0]).query)
    assert query['user_account'] == ['shared-user' + suffix]
    assert query['user_password'] == ['shared-secret']
    assert svc.auth_submitted


def test_unselected_provider_cannot_submit_credentials():
    http = TwoScenes()
    svc = CampusService(dorm_config(confirmed=False), http=http)
    assert svc.identify_portal()
    result = svc.authenticate()
    assert result.category == 'configuration'
    assert '选择宿舍服务商' in result.message
    assert not any(urlsplit(u).path == LOGIN_PATH for u in http.calls)


def test_dorm_already_online_does_not_require_provider_or_submit():
    http = TwoScenes(online=1)
    svc = CampusService(dorm_config(confirmed=False), http=http)
    assert svc.identify_portal()
    assert svc.authenticate().category == 'already_online'
    assert not any(urlsplit(u).path == LOGIN_PATH for u in http.calls)


def test_dorm_unknown_prefix_is_rejected_not_guessed():
    http = TwoScenes()
    http.responses['dorm.test'].settings['account_prefix'] = 1
    svc = CampusService(dorm_config('@cmcc'), http=http)
    assert svc.identify_portal()
    assert svc.authenticate().category == 'configuration'
    assert not any(urlsplit(u).path == LOGIN_PATH for u in http.calls)


def test_dorm_suffix_is_not_duplicated():
    cfg = dorm_config('@cmcc')
    cfg['username'] = 'student@cmcc'
    http = TwoScenes()
    svc = CampusService(cfg, http=http)
    assert svc.identify_portal() and svc.authenticate().success
    url = next(u for u in http.calls if urlsplit(u).path == LOGIN_PATH)
    assert parse_qs(urlsplit(url).query)['user_account'] == ['student@cmcc']


@pytest.mark.parametrize('available,expected', [(('dorm',), 'dorm'), (('public',), 'public')])
def test_auto_picks_the_only_verified_portal(available, expected):
    http = TwoScenes(available)
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    assert svc.identify_portal()
    assert svc.profile_name == expected
    hosts = [urlsplit(u).hostname for u in http.calls]
    if expected == 'dorm':
        assert hosts[0:2] == ['portal.test', 'dorm.test']
    else:
        assert hosts == ['portal.test']


def test_auto_tries_public_first_and_stops_at_first_verified_portal():
    http = TwoScenes(('public', 'dorm'))
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    assert svc.identify_portal()
    assert svc.profile_name == 'public'
    assert [urlsplit(u).hostname for u in http.calls] == ['portal.test']


def test_auto_public_success_submits_only_to_public_not_dorm():
    http = TwoScenes(('public', 'dorm'))
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    sup = Supervisor(lambda: (False, 'offline'), svc.identify_portal, svc.authenticate)
    assert sup.check().state == State.PORTAL
    assert svc.profile_name == 'public'
    assert all(urlsplit(u).hostname == 'portal.test' for u in http.calls)
    assert not any(urlsplit(u).hostname == 'dorm.test' for u in http.calls)


def test_connected_scene_is_detected_without_authentication_and_refreshed_on_switch():
    http = TwoScenes(('public',))
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    sup = Supervisor(lambda: (True, 'online'), svc.identify_portal, svc.authenticate)
    assert sup.check().state == State.ONLINE
    assert svc.profile_name == 'public'
    previous = len(http.calls)
    sup.check()
    assert len(http.calls) == previous  # no repeated scene scan on every healthy heartbeat
    http.available = {'dorm'}
    sup.network_changed('dorm-interface')
    assert sup.check().state == State.ONLINE
    assert svc.profile_name == 'dorm'
    assert not any(urlsplit(u).path == LOGIN_PATH for u in http.calls)


@pytest.mark.parametrize('recover_minute', [6, 10, 12])
def test_full_midnight_blackout_retries_and_recovers_without_manual_action(recover_minute):
    tz = ZoneInfo('Asia/Shanghai')
    begin = datetime(2026, 10, 5, 23, 59, 55, tzinfo=tz)
    midnight = begin.replace(day=6, hour=0, minute=0, second=0)
    recovery = midnight + timedelta(minutes=recover_minute)
    current = [begin]
    reauthenticated = [False]
    attempts = []
    checks = []
    outcomes = []

    def probe():
        return (current[0] < midnight or reauthenticated[0], 'simulated')

    def authenticate():
        attempts.append(current[0])
        if current[0] < recovery:
            return PortalResult(False, 'temporary', '学校暂时未恢复')
        reauthenticated[0] = True
        return PortalResult(True, 'success', '认证成功')

    sup = Supervisor(probe, lambda: True, authenticate, now=lambda: current[0])
    scheduler = PollScheduler(0, 'same-network', begin)
    for seconds in range(0, 15 * 60, 5):
        current[0] = begin + timedelta(seconds=seconds)
        tick = scheduler.tick(seconds, current[0], 'same-network', sup.outcome.next_seconds)
        if tick.due:
            checks.append(current[0])
            outcome = sup.check()
            outcomes.append((current[0], outcome))
            scheduler.reschedule(seconds, outcome.next_seconds)

    assert midnight in checks and midnight in attempts
    assert midnight + timedelta(minutes=12) in checks
    successes = [stamp for stamp, outcome in outcomes if outcome.state == State.AUTHENTICATED]
    assert successes and successes[0] == recovery
    assert attempts[-1] == recovery  # no login after successful connectivity verification
    assert all(outcome.next_seconds == 60 for stamp, outcome in outcomes if midnight <= stamp < midnight + timedelta(minutes=10))


def test_auto_reports_not_campus_when_public_and_dorm_both_fail():
    http = TwoScenes(())
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    assert not svc.identify_portal()
    assert svc.portal_error == '当前不在可识别的校园网环境（公共网和宿舍网均未识别）'
    assert [urlsplit(u).hostname for u in http.calls] == ['portal.test', 'dorm.test']


def test_online_check_reports_unrecognized_scene_instead_of_claiming_campus():
    http = TwoScenes(())
    svc = CampusService(dorm_config('@cmcc', active='auto'), http=http)
    sup = Supervisor(lambda: (True, 'internet'), svc.identify_portal, svc.authenticate)
    outcome = sup.check()
    assert outcome.state == State.ONLINE
    assert '可能不在校园网' in outcome.message


def test_missing_provider_is_configuration_needed_not_server_auth_rejection():
    http = TwoScenes()
    svc = CampusService(dorm_config(confirmed=False, active='auto'), http=http)
    sup = Supervisor(lambda: (False, 'offline'), svc.identify_portal, svc.authenticate)
    scenes = []
    sup.scene_changed = lambda name, url: scenes.append((name, url))
    result = sup.check()
    assert scenes == [('dorm', 'http://dorm.test/')]
    assert result.state == State.NEEDS_CONFIG
    assert '未发送凭据' in result.message
    assert not svc.auth_submitted
    assert not any(urlsplit(u).path == LOGIN_PATH for u in http.calls)
    assert sup.check().state == State.NEEDS_CONFIG
    assert '请选择' not in scenes[0][0]


def test_provider_saved_then_shared_credentials_submit_only_to_selected_dorm():
    cfg = dorm_config(confirmed=False, active='auto')
    http = TwoScenes()
    svc = CampusService(cfg, http=http)
    sup = Supervisor(lambda: (False, 'offline'), svc.identify_portal, svc.authenticate)
    assert sup.check().state == State.NEEDS_CONFIG
    # Model save/reload constructing a fresh service, exactly as the GUI does.
    cfg['profiles']['dorm'].update(provider_suffix='@telecom', provider_confirmed=True)
    svc = CampusService(cfg, http=http)
    probes = iter([(False, 'offline'), (True, 'online')])
    sup = Supervisor(lambda: next(probes), svc.identify_portal, svc.authenticate)
    assert sup.check().state == State.AUTHENTICATED
    calls = [u for u in http.calls if urlsplit(u).path == LOGIN_PATH]
    assert len(calls) == 1
    assert urlsplit(calls[0]).hostname == 'dorm.test'
    query = parse_qs(urlsplit(calls[0]).query)
    assert query['user_account'] == ['shared-user@telecom']
    assert query['user_password'] == ['shared-secret']
    assert not any(urlsplit(u).path == LOGIN_PATH and urlsplit(u).hostname == 'portal.test' for u in http.calls)


def test_dorm_config_block_does_not_prevent_public_auth_after_network_switch():
    cfg = dorm_config(confirmed=False, active='auto')
    http = TwoScenes()
    svc = CampusService(cfg, http=http)
    sup = Supervisor(lambda: (False, 'offline'), svc.identify_portal, svc.authenticate)
    assert sup.check().state == State.NEEDS_CONFIG
    http.available = {'public'}
    sup.network_changed('public-interface')
    assert sup.check().state == State.PORTAL
    login = [u for u in http.calls if urlsplit(u).path == LOGIN_PATH]
    assert len(login) == 1 and urlsplit(login[0]).hostname == 'portal.test'
