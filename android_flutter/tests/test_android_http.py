import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from android_http import AndroidHttp
from campus_assistant.protocol import PortalError
from core_test_fixtures import CompletedTicket


URL = "http://portal.test/?user_password=private-secret"


def reply(url=URL, body=b"ok", status=200, headers=None):
    return {"status": status, "body": base64.b64encode(body).decode(),
            "encoding": "utf-8", "final": url, "headers": headers or {}}


class TicketTests(unittest.TestCase):
    def test_native_lookup_is_lazy_and_uses_exact_class(self):
        http = AndroidHttp()
        self.assertIsNone(http._ticket_factory)
        native = type("Native", (), {"start": lambda *args: CompletedTicket(reply())})
        with patch.dict(sys.modules, {"java": type("Java", (), {"jclass": lambda name: native})}):
            self.assertEqual(http.get(URL)[1], b"ok")
        self.assertEqual(http.NATIVE_CLASS, "io.github.Mike666wq.czuconnect.AndroidHttp")

    def test_native_bytes_are_not_inflated_again(self):
        body = b"\x1f\x8bnot-a-gzip-stream"
        ticket = CompletedTicket(reply(body=body, headers={"Content-Encoding": "gzip"}))
        http = AndroidHttp(ticket_factory=lambda *args: ticket)
        self.assertEqual(http.get(URL)[1], body)
        self.assertTrue(ticket.cancelled)
        self.assertEqual(http.last_headers, {"Content-Encoding": "gzip"})

    def test_exact_body_bound_and_oversized_body(self):
        for size in (1_000_000, 1_000_001, 1_100_000):
            with self.subTest(size=size):
                ticket = CompletedTicket(reply(body=b"x" * size))
                http = AndroidHttp(ticket_factory=lambda *args: ticket)
                if size == 1_000_000:
                    self.assertEqual(len(http.get(URL)[1]), size)
                else:
                    with self.assertRaisesRegex(PortalError, "门户响应过大"):
                        http.get(URL)
                self.assertTrue(ticket.cancelled)

    def test_timeout_uses_50ms_polling_and_cancels(self):
        clock = [0.0]
        waits, starts = [], []

        class Pending(CompletedTicket):
            def awaitDone(self, ms):
                waits.append(ms)
                clock[0] += ms / 1000
                return False

        ticket = Pending(reply())
        def start(*args):
            starts.append(args)
            return ticket
        http = AndroidHttp(timeout=0.125, ticket_factory=start)
        with patch("android_http.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(PortalError, "请求总超时"):
                http.get(URL)
        self.assertEqual(waits, [50, 50, 25])
        self.assertEqual(starts[0][2], 125)
        self.assertTrue(ticket.cancelled)

    def test_cancel_before_start_during_wait_and_after_result(self):
        for phase in ("before", "wait", "result"):
            with self.subTest(phase=phase):
                cancelled, starts = [phase == "before"], []

                class Cancelling(CompletedTicket):
                    def awaitDone(self, ms):
                        if phase == "wait":
                            cancelled[0] = True
                        return True

                    def result(self):
                        if phase == "result":
                            cancelled[0] = True
                        return super().result()

                ticket = Cancelling(reply())
                def start(*args):
                    starts.append(args)
                    return ticket
                http = AndroidHttp(ticket_factory=start)
                http.cancel_check = lambda: cancelled[0]
                with self.assertRaisesRegex(PortalError, "检查已取消"):
                    http.get(URL)
                self.assertEqual(len(starts), 0 if phase == "before" else 1)
                self.assertEqual(http.last_headers, {})
                if starts:
                    self.assertTrue(ticket.cancelled)

    def test_sanitizes_native_start_wait_result_and_cancel_failures(self):
        for phase in ("start", "wait", "result", "cancel"):
            with self.subTest(phase=phase):
                class Failure(CompletedTicket):
                    def awaitDone(self, ms):
                        if phase == "wait":
                            raise RuntimeError(URL)
                        return True

                    def result(self):
                        if phase == "result":
                            raise RuntimeError(URL)
                        return super().result()

                    def cancel(self):
                        if phase == "cancel":
                            raise RuntimeError(URL)
                        super().cancel()

                def start(*args):
                    if phase == "start":
                        raise RuntimeError(URL)
                    return Failure(reply())
                http = AndroidHttp(ticket_factory=start)
                if phase == "cancel":
                    self.assertEqual(http.get(URL)[1], b"ok")
                else:
                    with self.assertRaisesRegex(PortalError, "^网络请求失败$") as raised:
                        http.get(URL)
                    self.assertNotIn("private-secret", str(raised.exception))

    def test_bad_ticket_shapes_and_automatic_native_redirect_are_rejected(self):
        malformed = ["not-json", "[]", json.dumps(reply(body=b"" ) | {"body": "!!!"})]
        malformed += [json.dumps(reply() | fields) for fields in (
            {"status": True}, {"headers": {"X": ["bad"]}}, {"encoding": ""},
            {"final": "http://other.test/"}, {"body": None}, {"status": 999})]
        for raw in malformed:
            with self.subTest(raw=raw[:50]):
                ticket = CompletedTicket({})
                ticket.reply = raw
                http = AndroidHttp(ticket_factory=lambda *args: ticket)
                with self.assertRaises(PortalError):
                    http.get(URL)
                self.assertTrue(ticket.cancelled)

    def test_injected_portal_errors_are_sanitized_too(self):
        def start(*args):
            raise PortalError(URL)
        with self.assertRaisesRegex(PortalError, "^网络请求失败$"):
            AndroidHttp(ticket_factory=start).get(URL)

    def test_redirects_are_opt_in_and_original_host_is_enforced(self):
        calls = []
        def start(url, headers, timeout):
            calls.append(url)
            return CompletedTicket(reply(url, status=302, headers={"location": "http://evil.test/"}))
        http = AndroidHttp(ticket_factory=start)
        self.assertEqual(http.get(URL)[0], 302)
        self.assertEqual(http.last_headers["location"], "http://evil.test/")
        with self.assertRaisesRegex(PortalError, "其他主机"):
            http.get(URL, same_host_redirects=True)
        self.assertEqual(calls, [URL, URL])
        self.assertEqual(http.last_headers, {})

    def test_four_redirects_allowed_fifth_rejected_and_shared_deadline(self):
        for redirects in (4, 5):
            calls, clock = [], [0.0]
            def start(url, headers, timeout):
                calls.append((url, timeout, json.loads(headers)))
                clock[0] += 0.1
                is_redirect = len(calls) <= redirects
                return CompletedTicket(reply(url, status=302 if is_redirect else 200,
                                             headers={"Location": "/hop" + str(len(calls))} if is_redirect else {}))
            http = AndroidHttp(timeout=1, ticket_factory=start)
            with patch("android_http.time.monotonic", side_effect=lambda: clock[0]):
                if redirects == 4:
                    self.assertEqual(http.get(URL, headers={"X": "v"}, same_host_redirects=True)[0], 200)
                else:
                    with self.assertRaisesRegex(PortalError, "跳转次数过多"):
                        http.get(URL, same_host_redirects=True)
            self.assertEqual(len(calls), 5)
            self.assertLess(calls[-1][1], calls[0][1])

    def test_redirect_chain_has_one_total_deadline(self):
        clock, calls = [0.0], []
        def start(url, headers, timeout):
            calls.append(url)
            clock[0] += 0.3
            return CompletedTicket(reply(url, status=302, headers={"Location": "/next"}))
        with patch("android_http.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(PortalError, "请求总超时"):
                AndroidHttp(timeout=0.5, ticket_factory=start).get(URL, same_host_redirects=True)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
