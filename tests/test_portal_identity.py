"""Portal recognition regressions; all requests are fake and never reach the network."""
import pytest

from campus_assistant.protocol import PortalError
from campus_assistant.service import CampusService
from test_protocol_regression import FakeHttp, base_config, service_for


@pytest.mark.parametrize('marker', [
    '<!--Dr.COMWebLoginID_1.htm-->',
    "authsuccess='Dr.COMWebLoginID_3.htm';",
    '<!--Dr.COM1.0WebLoginID_1.htm-->',
])
def test_online_page_without_drcom_route_is_recognized(marker):
    page = f'<html><title>注销页</title>{marker}<script src="a41.js?version=1748398885004"></script></html>'
    service, http = service_for(page, online_result=1)
    assert '/drcom/' not in page
    assert service.identify_portal()
    assert service.portal_known
    assert service.portal_error == ''
    assert len(http.calls) == 1  # identification is read-only
    assert service.authenticate().category == 'already_online'
    assert not any('/portal/login?' in url for url, _ in http.calls)


@pytest.mark.parametrize('source', [
    'https://untrusted.test/a41.js', '//untrusted.test/a41.js',
    'not-a41.js', 'a41.js.fake', '/unrelated?file=a41.js',
])
def test_untrusted_or_substring_only_script_is_rejected(source):
    service, http = service_for(f'<!--Dr.COMWebLoginID_1.htm--><script src="{source}"></script>')
    assert not service.identify_portal()
    assert '入口可访问' in service.portal_error
    assert not service.portal_known
    assert len(http.calls) == 1


def test_script_name_alone_is_not_sufficient():
    service, _ = service_for('<script src="a41.js"></script><p>unrelated page</p>')
    assert not service.identify_portal()


def test_access_failure_is_distinct_from_unrecognized_page():
    class Unreachable(FakeHttp):
        def get(self, *args, **kwargs):
            raise PortalError('TimeoutError')
    service = CampusService(base_config(), http=Unreachable(''))
    assert not service.identify_portal()
    assert '无法访问校园门户' in service.portal_error
    assert 'TimeoutError' in service.portal_error
    assert not service.portal_known


def test_auto_mode_keeps_public_page_when_dorm_is_unreachable():
    class PublicOnly(FakeHttp):
        def get(self, url, **kwargs):
            if 'dorm.test' in url:
                raise PortalError('URLError')
            return super().get(url, **kwargs)
    http = PublicOnly('<!--Dr.COMWebLoginID_1.htm--><script src="a41.js"></script>')
    service = CampusService(base_config(active_profile='auto'), http=http)
    assert service.identify_portal()
    assert service.profile_name == 'public'
    assert service.portal_error == ''
