"""Read-only config/status regression cases, including a portal slower than public probes."""
from urllib.parse import urlsplit

from campus_assistant.protocol import PortalError
from campus_assistant.service import CampusService
from test_protocol_regression import FakeHttp, base_config, portal_page, service_for, CONFIG_PATH, LOGIN_PATH


def test_existing_session_is_checked_before_config_and_credentials():
    cfg = base_config(username='', password='')
    service, http = service_for(portal_page(), config=cfg, online_result=1)
    assert service.identify_portal()
    assert service.authenticate().category == 'already_online'
    paths = [urlsplit(url).path for url, _ in http.calls]
    assert paths == ['/', '/drcom/chkstatus']
    assert CONFIG_PATH not in paths
    assert LOGIN_PATH not in paths


def test_config_timeout_is_explicit_and_does_not_submit_login():
    class ConfigTimeout(FakeHttp):
        def get(self, url, **kwargs):
            if urlsplit(url).path == CONFIG_PATH:
                self.calls.append((url, False))
                raise PortalError('请求总超时')
            return super().get(url, **kwargs)
    http = ConfigTimeout(portal_page(globals_="v4ip='10.20.30.40';"))
    service = CampusService(base_config(), http=http)
    assert service.identify_portal()
    result = service.authenticate()
    assert result.category == 'temporary'
    assert '请求总超时' in result.message
    assert '未发送凭据' in result.message
    assert not any(urlsplit(url).path == LOGIN_PATH for url, _ in http.calls)


def test_bad_config_response_is_distinct_from_network_timeout():
    class HtmlConfig(FakeHttp):
        def get(self, url, **kwargs):
            if urlsplit(url).path == CONFIG_PATH:
                return 200, b'<html>not JSONP</html>', 'utf-8', url
            return super().get(url, **kwargs)
    http = HtmlConfig(portal_page(globals_="v4ip='10.20.30.40';"))
    service = CampusService(base_config(), http=http)
    assert service.identify_portal()
    result = service.authenticate()
    assert '门户返回格式无法识别' in result.message
    assert '请求总超时' not in result.message
    assert not any(urlsplit(url).path == LOGIN_PATH for url, _ in http.calls)


def test_unknown_online_state_never_assumes_offline_or_submits():
    class UnknownStatus(FakeHttp):
        def get(self, url, **kwargs):
            if urlsplit(url).path == '/drcom/chkstatus':
                return 200, b'dr0({});', 'utf-8', url
            return super().get(url, **kwargs)
    http = UnknownStatus(portal_page())
    service = CampusService(base_config(), http=http)
    assert service.identify_portal()
    assert service.authenticate().category == 'temporary'
    assert not any(urlsplit(url).path in {CONFIG_PATH, LOGIN_PATH} for url, _ in http.calls)


def test_readonly_config_loader_never_requires_or_sends_credentials():
    service, http = service_for(portal_page(), config=base_config(username='', password=''))
    assert service.identify_portal()
    assert service.load_portal_config().success
    assert not any(urlsplit(url).path == LOGIN_PATH for url, _ in http.calls)


def test_portal_and_public_probe_have_separate_bounded_timeouts():
    service = CampusService(base_config())
    assert service.http.timeout == 10
    assert service.probe_http.timeout == 4
    cancelled = lambda: True
    service.set_cancel_check(cancelled)
    assert service.http.cancel_check is cancelled
    assert service.probe_http.cancel_check is cancelled


def test_arbitrary_error_text_does_not_leak_into_ui():
    assert CampusService._safe_error(PortalError('password=secret https://test/')) == '网络请求失败'
    assert CampusService._safe_error(PortalError('HTTP 503')) == 'HTTP 503'
