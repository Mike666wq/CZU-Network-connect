# Android Python API

Production entry point: campus_android.Bridge(data_dir, transport_factory=None,
service_factory=None). Supply an absolute app-private directory. Initialization
loads private config and constructs transports without Java lookup or network
I/O. Python starts no thread, subprocess, timer, or background loop.

| Method | Return | Behavior |
| --- | --- | --- |
| get_config() | JSON string | Cached {username, password, isp, scene}. |
| save_config(payload) | None | Validate JSON, persist through core config with an explicit private path, and reconfigure only if values changed. |
| tick(network_id, force=False) | int | Seconds until due; both arguments accept positional calls. Reuses core PollScheduler, CampusService, and Supervisor. |
| stop() | None | Mark paused and invalidate/cancel the active generation immediately. |
| resume() | None | Serial worker operation; unpause and make the next tick due without resetting cooldown. |
| network_changed(network_id) | None | Invalidate active bridge/supervisor generation immediately if ID changed. |
| snapshot() | JSON string | Cached safe status and current countdown; no file I/O. |

Native code queues resume/tick/save serially. Bridge also serializes these
defensively. stop/network_changed may run on main/callback threads: they use
only a short lock for memory updates, never the worker/config lock or file I/O.
Call network_changed before cancelling old native HTTP. Canceled ticks publish
no result or diagnostic entry. Paused and invalidated generations return 0;
native code must not schedule checks while paused.

Defaults: username="", password="", isp="-1", scene="auto". Missing fields use
defaults rather than patching existing values; unknown fields are rejected.
Scenes: auto/public/dorm. ISP values: "-1" (unselected), "" (campus service),
"@cmcc", "@unicom", "@telecom". ISP maps to the dorm suffix and confirmation;
public credentials have no provider suffix. Credentials are shared across
scenes. Empty credentials can be saved; core validation prevents authentication.
Credential fields allow at most 1,024 characters without control characters;
payloads allow at most 16,384 characters. Invalid config raises sanitized
campus_assistant.config.ConfigError.

Snapshot fields: status (Chinese core state label), state (lowercase core enum
name), message (fixed Chinese text selected from safe states/reason codes),
online (bool), coreVersion (campus_assistant.__version__), nextSeconds (int),
logs (list of safe Chinese strings, newest last, at most 100). Credential and
provider errors have specific fixed guidance. No raw server text, URLs,
credentials, protocol warning values, or exception text enters snapshots/logs.
Files remain under data_dir: config.json, android_logs.json, events.jsonl.
Audit calls always pass the private events path explicitly. Preference migration
belongs to Dart; bridge never reads desktop config or SharedPreferences.

Android caps blocked scheduling to the remaining core authentication cooldown
(300 seconds in 0.4.2), using supervisor.now().timestamp(). An ordinary due tick
retries at expiry; no force or manual rescheduling is required. Online outcomes
retain normal scheduling even if the core retains a previous blocked flag.
Unchanged saves and network changes retain cooldown history. Canceled checks
roll back speculative core state and invalidate connected-scene inspection.

## Injection

    transport_factory(timeout: float) -> transport
    service_factory(config: dict, http=portal_transport) -> service

Transport factories receive keyword timeout=10.0 for portal requests and
timeout=4.0 for public probes. Service factories receive a deep copy of core
config and keyword http. Return CampusService or a compatible subclass:
probe_http is assigned; set_cancel_check is installed; probe_internet,
identify_portal, authenticate connect to Supervisor. Constructors perform no I/O.

    AndroidHttp(timeout=4.0, *, ticket_factory=None)
    ticket_factory(url, headers_json, timeout_ms) -> ticket
    get(url, *, headers=None, same_host_redirects=False)
      -> (status: int, body: bytes, encoding: str, final: str)

android_http.AndroidHttp exposes timeout, last_headers, and cancel_check.
Without injection, it lazily resolves static
io.github.Mike666wq.czuconnect.AndroidHttp.start through java.jclass.
Ticket methods: awaitDone(ms), cancel(), result(). Result JSON fields:
status, body (strict base64), encoding, final, headers (string-to-string dict).
Native must disable automatic redirects and return the original requested URL
in final, preserving its spelling across OkHttp normalization.

Waits poll at most 50 ms and share one monotonic deadline across redirects.
Cancellation is checked before accepting results; tickets are always released
with cancel(). Errors become PortalError with fixed safe messages. Native
returns inflated bytes, including explicit gzip; Python does not inflate again
and enforces its own 1,000,000-byte limit. Optional manual redirects allow at
most four hops, validate HTTP(S) URLs, and enforce the original hostname.
Authentication requests leave redirects disabled.

## Staging and tests

    python3 android_flutter/tools/stage_core.py
    python3 -m unittest discover -s android_flutter/tests

Default staging output:
android_flutter/android/app/build/generated/python/campus_assistant.
Optional --output-dir PATH changes the generated Python source root for tests.
The package contains only unchanged current core modules __init__, audit,
config, engine, presentation, protocol, scheduler, service. Stale generated
files are removed each run. Bridge modules remain in python source. No core
copies belong in source control.

Runtime dependency requirements.txt pins tzdata==2025.2 for Gradle/CI to install.
No local installation is needed. Tests use temporary private configs and
in-memory tickets, without campus network access.

core_test_fixtures exports FixtureNetwork,
make_bridge(data_dir, scene="public", scenario="success") -> Bridge, and
run(data_dir) -> JSON {ok, coreVersion, checks}. This helper is distinct from
the native debug-only device_tests/device_checks.py module.
