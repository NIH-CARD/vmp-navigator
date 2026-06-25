"""
Persona-driven tests for the VMP Navigator engine.

These run synthetic users through the trees and assert the path, flags, and
matched resources. Because Phase 1 is deterministic, this suite IS the clinical
regression guard: a config edit that changes a vulnerable persona's path fails here.

Run:  python -m pytest tests/ -v      (or)      python tests/test_engine.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

CFG = engine.load_config()


def run(steps: list) -> dict:
    """Feed answers to engine.submit in order. Info screens (landing, education,
    national redirect) auto-advance so step lists express only real choices."""
    s = engine.start_session()
    i = 0
    while s["current"] != "__END__":
        node = engine.current_node(s, CFG)
        if node["type"] == "info":
            s = engine.submit(s, CFG, None)
            continue
        if i >= len(steps):
            break
        s = engine.submit(s, CFG, steps[i])
        i += 1
    return s


def resource_ids(s):
    return {r["id"] for r in engine.match_resources(s, CFG)}


# --------------------------------------------------------------------------- #
def test_config_loads_and_validates():
    assert "landing" in CFG["nodes"]
    assert any(f["id"] == "unmet_care_need" for f in CFG["flags"])


def test_explainer_questions_are_curated_strings():
    # The "Learn more" feature uses fixed buttons, not free text. Every configured
    # question must be a non-empty string so the model is only ever asked vetted prompts.
    ex = CFG.get("explainers", {})
    groups = list(ex.get("nodes", {}).values()) + list(ex.get("resource_types", {}).values())
    found = 0
    for item in groups:
        for q in item.get("questions", []):
            assert isinstance(q, str) and q.strip(), f"bad question button: {q!r}"
            found += 1
    assert found > 0, "expected curated question buttons"


def test_anonymous_brain_health_no_flags():
    # VA yes -> entry[brain_health] -> (education) -> service_menu[community] -> loopback done -> contact skip
    s = run(["yes", ["brain_health"], ["community"], "done", {}])
    assert s["status"] == "completed"
    assert s["flags"] == []
    assert "brain_health_cdc" in resource_ids(s)
    # no contact captured -> stays anonymous
    assert "vadr_name" not in s["answers"]


def test_plwd_no_provider_raises_high_and_routes_clinical():
    # PLWD, worsening=yes, mild severity so we reach q6, provider=no
    s = run([
        "yes",           # VA resident
        ["plwd"],        # entry
        "yes",           # q1 worsening
        "sometimes",     # q2
        "sometimes",     # q3
        "always",        # q4 (gets help) -> no unmet-need flag
        "no",            # q6 provider -> HIGH no-provider
        {},              # callback: skip contact
        ["clinical"],    # service menu
        "23220",         # zip
        "memory_clinic", # complaint
        "yes",           # transport
        "done",          # loopback
        {},              # final contact skip
    ])
    ids = {f["id"] for f in s["flags"]}
    assert "active_concern_no_provider" in ids
    assert "unmet_care_need" not in ids
    assert "callback" in s["path"]
    assert "nih_memory_aging_clinic" in resource_ids(s)   # priority connection always present
    assert "dars_memory_assessment" in resource_ids(s)


def test_plwd_unmet_need_raises_high_8h():
    # severe: q3 usually + q4 never -> unmet-need flag (8h SLA)
    s = run(["yes", ["plwd"], "yes", "usually", "usually", "never"])
    flag = next(f for f in s["flags"] if f["id"] == "unmet_care_need")
    assert flag["tier"] == "HIGH"
    assert flag["sla_hours"] == 8
    assert s["current"] == "callback"   # interrupt happened, session still open


def test_talk_to_a_person_anytime():
    s = engine.start_session()
    s = engine.submit(s, CFG, None)     # at va_check now
    s = engine.request_human(s, CFG)
    assert s["current"] == "callback"
    assert any(f["id"] == "user_requested_human" for f in s["flags"])


def test_out_of_state_redirects_national_only():
    s = run(["no", {}])                 # VA = no -> national_only -> contact skip
    ids = resource_ids(s)
    assert "clinicaltrials_gov" in ids                 # national, allowed
    assert "nih_memory_aging_clinic" in ids             # national priority connection
    assert "dars_memory_assessment" not in ids          # VA-only, excluded
    assert any(f["id"] == "out_of_virginia" for f in s["flags"])


def test_no_transport_drops_drive_only_primary_care():
    s = run([
        "yes", ["plwd"], "no",          # q1 no -> education -> service_menu
        ["clinical"], "23220", "primary_care", "no",   # no car
        "done", {},
    ])
    ids = resource_ids(s)
    assert "cms_care_compare" not in ids                # drive-required, dropped
    assert "dars_aaa" in ids                            # transport help remains


def test_caregiver_health_impact_medium_flag():
    s = run(["yes", ["caregiver"], "yes", "06", ["community"], "done", {}])
    assert any(f["id"] == "caregiver_health_impact" and f["tier"] == "MEDIUM" for f in s["flags"])


def test_contact_is_optional_but_captured_when_given():
    s = run([
        "yes", ["plwd"], "yes", "usually", "usually", "never",       # -> callback
        {"vadr_name": "Test Persona", "vadr_phone": "555-0100"},      # provide contact
        "yes",                                                        # resume at q6 (provider)
        ["clinical"], "23220", "memory_clinic", "yes", "done", {},
    ])
    assert s["answers"].get("vadr_name") == "Test Persona"
    assert s["status"] == "completed"


def test_clock_collector_surfaces_for_research():
    # The data-collection hand-off appears for research-track users...
    s = run(["yes", ["brain_health"], ["research"], "yes", "done", {}])
    assert "vmp_clock_collector" in resource_ids(s)
    # ...but not for out-of-state users (it's a Virginia research activity, not national).
    s2 = run(["no", {}])
    assert "vmp_clock_collector" not in resource_ids(s2)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
