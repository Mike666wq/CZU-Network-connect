import gzip
import io
import json
from email.message import Message

from campus_assistant.audit import record_event
from campus_assistant.protocol import DirectHttp, PortalError
import pytest


def test_gzip_portal_response_is_decoded_before_jsonp_parser():
    headers = Message()
    headers['Content-Encoding'] = 'gzip'
    response = io.BytesIO(gzip.compress(b'dr0({"result":1});'))
    response.headers = headers
    assert DirectHttp._read_body(response) == b'dr0({"result":1});'


def test_decompressed_response_size_is_bounded():
    response = io.BytesIO(gzip.compress(b'x' * 1_000_001))
    response.headers = Message()
    with pytest.raises(PortalError, match='响应过大'):
        DirectHttp._read_body(response)


def test_audit_records_schedule_and_attempt_without_credential_fields(tmp_path):
    path = tmp_path / 'events.jsonl'
    assert record_event(path, state='校园网已认证', scene='dorm', next_seconds=60,
                        auth_attempted=True, reason='midnight')
    event = json.loads(path.read_text())
    assert set(event) == {'version', 'time', 'state', 'scene', 'next_seconds', 'auth_attempted', 'reason'}
    assert event['reason'] == 'midnight'
    assert event['auth_attempted'] is True
    assert event['time'].endswith('+08:00')
