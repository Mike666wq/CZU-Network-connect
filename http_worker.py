"""Windows console-subsystem entry, launched with CREATE_NO_WINDOW.

Kept outside the Qt/windowed executable so stdin/stdout IPC works in the frozen
Windows bundle. Do not launch this helper manually: requests arrive on private stdin.
"""
from campus_assistant.protocol import http_worker_entry

if __name__ == '__main__':
    raise SystemExit(http_worker_entry())
