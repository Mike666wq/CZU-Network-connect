"""Read-only diagnostics without loading user credentials or GUI libraries."""
from pathlib import Path
from copy import deepcopy
import sys
import time
from . import __version__
from .service import CampusService


def diagnose_network():

    import json
    from campus_assistant.protocol import BoundedHttp, PortalError
    results = []
    for url in ("https://cp.cloudflare.com/generate_204", "https://www.msftconnecttest.com/connecttest.txt"):
        started = time.monotonic()
        try:
            status, body, _, _ = BoundedHttp().get(url)
            entry = {"host": __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).hostname,
                     "status": status, "bytes": len(body)}
        except PortalError as exc:
            entry = {"error": str(exc)}
        entry["seconds"] = round(time.monotonic() - started, 2)
        results.append(entry)
    Path(sys.argv[sys.argv.index("--diagnose-network") + 1]).write_text(json.dumps(results), encoding="utf-8")
    return 0



def diagnose_portal():

    import json
    from campus_assistant.config import DEFAULT_CONFIG
    config = deepcopy(DEFAULT_CONFIG)
    selection = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--profile=")), "public")
    if selection not in {"public", "dorm", "auto"}:
        return 2
    config["active_profile"] = selection
    service = CampusService(config)
    report = {"version": __version__}
    started = time.monotonic()
    found = service.identify_portal()
    report["identity"] = {"success": found, "profile": service.profile_name if found else "unknown", "seconds": round(time.monotonic() - started, 2)}
    if found:
        for label, action in (("status", service.check_portal_status), ("config", service.load_portal_config)):
            started = time.monotonic()
            result = action()
            report[label] = {"success": result.success, "category": result.category,
                             "message": result.message, "seconds": round(time.monotonic() - started, 2)}
    # Never load the user's credentials, call authenticate(), or export server response bodies.
    Path(sys.argv[sys.argv.index("--diagnose-portal") + 1]).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return 0
