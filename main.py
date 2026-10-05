"""Lightweight entry point: HTTP workers must never import Qt or create a GUI."""
from __future__ import annotations

import sys


def main() -> int:
    if "--http-worker" in sys.argv:
        from campus_assistant.protocol import http_worker_entry
        return http_worker_entry()
    if "--diagnose-network" in sys.argv:
        from campus_assistant.diagnostics import diagnose_network
        return diagnose_network()
    if "--diagnose-portal" in sys.argv:
        from campus_assistant.diagnostics import diagnose_portal
        return diagnose_portal()
    if "--profile-resources" in sys.argv:
        from pathlib import Path
        from campus_assistant import gui
        from campus_assistant.resource_profile import run_session
        target = Path(sys.argv[sys.argv.index("--profile-resources") + 1])
        cycles = next((int(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--soak-cycles=")), 0)
        return run_session(gui.Window, gui.__dict__, target, cycles)
    from campus_assistant.gui import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
