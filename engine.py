"""
VMP Navigator — deterministic engine.

Pure, side-effect-free interpreter of the YAML config. The Streamlit layer holds
session state and calls these functions; all clinical logic lives in /config.

Design rules (mirror CLAUDE.md):
  - Deterministic. No LLM, no free-text understanding.
  - Contact is always optional; resources are never gated behind identity.
  - Escalate conservatively: HIGH-interrupt flags stop routing and offer a callback.
  - This is a navigator, not a diagnostic: it routes and flags, never scores or interprets.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_DIR = Path(__file__).parent / "config"


# --------------------------------------------------------------------------- #
# Config loading + light validation
# --------------------------------------------------------------------------- #
def _load_yaml(name: str) -> Any:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config() -> dict:
    nodes_list = _load_yaml("questions.yaml")["nodes"]
    nodes = {n["id"]: n for n in nodes_list}
    flags = _load_yaml("flags.yaml")["flags"]
    resources = _load_yaml("resources.yaml")["resources"]
    _validate(nodes, flags)
    cfg = {"nodes": nodes, "flags": flags, "resources": resources}
    # Optional curated "More about this" content (no LLM); absent file is fine.
    explainers_path = CONFIG_DIR / "explainers.yaml"
    cfg["explainers"] = _load_yaml("explainers.yaml") if explainers_path.exists() else {}
    return cfg


def _validate(nodes: dict, flags: list) -> None:
    """Fail loudly if a node points somewhere that doesn't exist."""
    specials = {"__next__", "__done__", "__resume__"}
    for node in nodes.values():
        targets = [node.get("goto")] + [o.get("goto") for o in node.get("options", [])]
        for t in targets:
            if t is None:
                continue
            if t not in specials and t not in nodes:
                raise ValueError(f"Node '{node['id']}' points to unknown node '{t}'")
    for rule in flags:
        if "tier" not in rule or "when" not in rule:
            raise ValueError(f"Flag '{rule.get('id')}' is missing tier/when")


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_session() -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "started_at": _now(),
        "completed_at": None,
        "current": "landing",
        "answers": {},                 # field -> value(s)
        "path": ["landing"],           # node ids visited
        "queue": [],                   # pending nodes to process
        "after_queue": None,           # where to go when the queue empties
        "resume_after_callback": None, # node to resume after a HIGH-interrupt callback
        "flags": [],                   # [{id, tier, label, sla_hours, queue, message}]
        "pending_escalation": None,    # the flag currently being handled at a callback node
        "status": "in_progress",       # in_progress | completed
    }


def current_node(session: dict, cfg: dict) -> dict:
    return cfg["nodes"][session["current"]]


# --------------------------------------------------------------------------- #
# Flag evaluation (Tree 5)
# --------------------------------------------------------------------------- #
def _match_condition(cond: dict, answers: dict) -> bool:
    val = answers.get(cond["field"])
    if val is None:
        return False
    # multi-select answers are lists; treat membership accordingly
    values = val if isinstance(val, list) else [val]
    if "in" in cond:
        return any(v in cond["in"] for v in values)
    if "equals" in cond:
        return cond["equals"] in values
    return False


def _match_rule(rule: dict, answers: dict) -> bool:
    when = rule["when"]
    if "all" in when:
        return all(_match_condition(c, answers) for c in when["all"])
    if "any" in when:
        return any(_match_condition(c, answers) for c in when["any"])
    return False


def _evaluate_flags(session: dict, cfg: dict) -> Optional[dict]:
    """Record any newly-true flags. Return the first new HIGH-interrupt flag, if any."""
    raised_ids = {f["id"] for f in session["flags"]}
    new_interrupt = None
    for rule in cfg["flags"]:
        if rule["id"] in raised_ids:
            continue
        if _match_rule(rule, session["answers"]):
            session["flags"].append({
                "id": rule["id"],
                "tier": rule["tier"],
                "label": rule.get("label", rule["id"]),
                "sla_hours": rule.get("sla_hours"),
                "queue": rule.get("queue"),
                "message": rule.get("message"),
            })
            if rule.get("interrupt") and new_interrupt is None:
                new_interrupt = session["flags"][-1]
    return new_interrupt


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def _resolve(session: dict, target: str) -> str:
    """Resolve special targets (__next__ / __done__ / __resume__) to a concrete node id."""
    if target == "__done__":
        return "__END__"
    if target == "__resume__":
        nxt = session.get("resume_after_callback") or "__next__"
        session["resume_after_callback"] = None
        if nxt == "__next__":
            return _pop_queue(session)
        return nxt
    if target == "__next__":
        return _pop_queue(session)
    return target


def _pop_queue(session: dict) -> str:
    if session["queue"]:
        return session["queue"].pop(0)
    nxt = session["after_queue"]
    session["after_queue"] = None
    return nxt if nxt else "__END__"


def _go(session: dict, target: str) -> dict:
    nxt = _resolve(session, target)
    if nxt == "__END__":
        session["current"] = "__END__"
        session["status"] = "completed"
        session["completed_at"] = _now()
    else:
        session["current"] = nxt
        session["path"].append(nxt)
    session["pending_escalation"] = None
    return session


def submit(session: dict, cfg: dict, value: Any) -> dict:
    """
    Advance the session given the user's answer to the current node.
      - single_select / gate: value is the chosen option's `value`
      - multi_select:         value is a list of chosen `value`s
      - collect:              value is the entered string
      - contact:              value is a dict of provided fields (may be empty / skipped)
      - info:                 value is ignored
    """
    node = current_node(session, cfg)
    ntype = node["type"]

    # 1) Record the answer
    if ntype in ("single_select", "gate"):
        session["answers"][node["field"]] = value
        chosen = next(o for o in node["options"] if o["value"] == value)
        intended_goto = chosen["goto"]
    elif ntype == "multi_select":
        session["answers"][node["field"]] = list(value)
        # Build the queue from selected options, in config order
        selected = set(value)
        queued = [o["goto"] for o in node["options"] if o["value"] in selected]
        session["queue"] = queued + session["queue"]
        session["after_queue"] = node.get("after_queue")
        intended_goto = "__next__"
    elif ntype == "collect":
        session["answers"][node["field"]] = value
        intended_goto = node["goto"]
    elif ntype == "contact":
        if isinstance(value, dict):
            for k, v in value.items():
                if v:
                    session["answers"][k] = v
        intended_goto = node["goto"]
    else:  # info
        intended_goto = node["goto"]

    # 2) Check escalation flags (skip when already handling a callback node)
    if ntype != "contact":
        interrupt = _evaluate_flags(session, cfg)
        if interrupt is not None:
            session["resume_after_callback"] = intended_goto
            session["pending_escalation"] = interrupt
            session["current"] = "callback"
            session["path"].append("callback")
            return session

    # 3) Otherwise advance normally
    return _go(session, intended_goto)


def request_human(session: dict, cfg: dict) -> dict:
    """User clicked 'Talk to a person' at any point — raise the HIGH flag and go to callback."""
    session["answers"]["requested_human"] = "yes"
    interrupt = _evaluate_flags(session, cfg)
    if interrupt is not None:
        session["resume_after_callback"] = session["current"]
        session["pending_escalation"] = interrupt
        session["current"] = "callback"
        session["path"].append("callback")
    return session


# --------------------------------------------------------------------------- #
# Resource matching
# --------------------------------------------------------------------------- #
def match_resources(session: dict, cfg: dict) -> list[dict]:
    answers = session["answers"]
    out_of_state = answers.get("vadr_state") == "no"
    no_transport = answers.get("clinical_transport_access") == "no"

    tags: set[str] = set(answers.get("service_tracks", []) or [])
    if "brain_health" in (answers.get("vadr_wellbeing") or []):
        tags.add("brain_health")
    # A no-provider or unmet-need flag should always surface clinical options
    flag_ids = {f["id"] for f in session["flags"]}
    if flag_ids & {"active_concern_no_provider", "unmet_care_need"}:
        tags.add("clinical")

    results = []
    for r in cfg["resources"]:
        if out_of_state:
            include = r.get("national")          # show the full national list
        else:
            include = r.get("always_include") or (set(r.get("tracks", [])) & tags)
        if not include:
            continue
        if no_transport and r.get("transportation_required"):
            continue  # drop drive-only options; telehealth/AAA remain
        results.append(r)

    # De-dupe, preserve order, priority connections first
    seen, ordered = set(), []
    for r in sorted(results, key=lambda x: (not x.get("always_include"), x["name"])):
        if r["id"] not in seen:
            seen.add(r["id"])
            ordered.append(r)
    return ordered
