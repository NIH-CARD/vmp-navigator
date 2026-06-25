"""
VMP Navigator — persistence (prototype).

Two strictly separated streams, mirroring the build plan:

  Stream A  analytics.jsonl   De-identified. NO name/email/phone, NO free text,
                              ZIP truncated to 3 digits. Safe for the dashboard.
  Stream B  phi_queue.json    MOCK PHI store for human-callback cases. In production
                              this is REDCap (HIPAA), NOT a local file.

Nothing crosses between the two. The session_id in Stream A is not linkable to identity.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ANALYTICS = DATA_DIR / "analytics.jsonl"
PHI_QUEUE = DATA_DIR / "phi_queue.json"

PHI_FIELDS = {"vadr_name", "vadr_email", "vadr_phone"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zip3(answers: dict) -> str | None:
    z = answers.get("vadr_2009_s12_16a")
    return z[:3] if isinstance(z, str) and len(z) >= 3 else None


# --------------------------------------------------------------------------- #
# Stream A — de-identified analytics
# --------------------------------------------------------------------------- #
def log_session(session: dict) -> None:
    """Write one de-identified row. Identifiers and free text are never included."""
    a = session["answers"]
    row = {
        "session_id": session["session_id"],
        "started_at": session["started_at"],
        "completed_at": session.get("completed_at"),
        "status": session["status"],
        "last_node": session["current"],
        "entry_categories": a.get("vadr_wellbeing"),
        "service_tracks": a.get("service_tracks"),
        "region_zip3": _zip3(a),
        "flags": [{"id": f["id"], "tier": f["tier"]} for f in session["flags"]],
        "n_nodes": len(session["path"]),
    }
    with open(ANALYTICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def read_analytics() -> list[dict]:
    if not ANALYTICS.exists():
        return []
    with open(ANALYTICS, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --------------------------------------------------------------------------- #
# Stream B — MOCK PHI escalation queue (REDCap in production)
# --------------------------------------------------------------------------- #
def _read_queue() -> list[dict]:
    if not PHI_QUEUE.exists():
        return []
    with open(PHI_QUEUE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_queue(items: list[dict]) -> None:
    with open(PHI_QUEUE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def enqueue_escalation(session: dict, flag: dict) -> None:
    """Upsert a flagged case in the callback queue (MOCK PHI).

    The case is captured the moment a flag fires (so it's never lost), and contact
    details are filled in if the person provides them later in the flow.
    """
    a = session["answers"]
    items = _read_queue()
    for i in items:
        if i["session_id"] == session["session_id"] and i["flag_id"] == flag["id"]:
            i["name"] = a.get("vadr_name") or i.get("name")
            i["email"] = a.get("vadr_email") or i.get("email")
            i["phone"] = a.get("vadr_phone") or i.get("phone")
            i["zip"] = a.get("vadr_2009_s12_16a") or i.get("zip")
            _write_queue(items)
            return
    items.append({
        "created_at": _now(),
        "session_id": session["session_id"],
        "flag_id": flag["id"],
        "tier": flag["tier"],
        "label": flag.get("label"),
        "sla_hours": flag.get("sla_hours"),
        "queue": flag.get("queue"),
        "status": "open",
        # contact is optional — may be absent if the user chose to stay anonymous
        "name": a.get("vadr_name"),
        "email": a.get("vadr_email"),
        "phone": a.get("vadr_phone"),
        "zip": a.get("vadr_2009_s12_16a"),
    })
    _write_queue(items)


def read_queue() -> list[dict]:
    return _read_queue()


def update_status(session_id: str, flag_id: str, status: str) -> None:
    items = _read_queue()
    for i in items:
        if i["session_id"] == session_id and i["flag_id"] == flag_id:
            i["status"] = status
    _write_queue(items)
