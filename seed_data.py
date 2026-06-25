"""
Seed the VMP Navigator with synthetic personas.

Runs a representative set of users through the REAL engine and writes their
de-identified analytics (Stream A) and flagged callback cases (Stream B, mock PHI),
so the coordinator dashboard has something to show and the user story is reproducible.

  python seed_data.py          # clear data, seed personas, print a summary
  python seed_data.py --md     # also print the markdown journey report (for USER_STORY.md)

All data is synthetic. Names/phones are fictional.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import persistence as db

CFG = engine.load_config()
HUMAN = "__HUMAN__"  # marker: user clicks "Talk to a person" at the current screen


# --------------------------------------------------------------------------- #
# Personas: (id, story, steps). Steps are decisions; info screens auto-advance.
# A persona "drops off" simply by running out of steps before the end.
# --------------------------------------------------------------------------- #
PERSONAS = [
    {
        "id": "maria_brain_health",
        "story": "Maria, 58, is healthy but her mother had Alzheimer's. She wants "
                 "prevention information, nothing more. Stays anonymous.",
        "steps": ["yes", ["brain_health"], ["community"], "done", {}],
    },
    {
        "id": "anita_caregiver_burnout",
        "story": "Anita cares for her husband and says caregiving is hurting her own "
                 "health. Not an emergency, but she needs support — and shares her contact.",
        "steps": ["yes", ["caregiver"], "yes", "06", ["community"], "done",
                  {"vadr_name": "Anita Bell", "vadr_phone": "434-555-0118"}],
    },
    {
        "id": "robert_no_provider",
        "story": "Robert, 71 (Richmond), has noticed worsening memory for a year but has "
                 "never talked to a doctor. He gets help at home, so the gap is the missing "
                 "provider. Shares contact for follow-up.",
        "steps": ["yes", ["plwd"], "yes", "sometimes", "sometimes", "always", "no",
                  {"vadr_name": "Robert Ellis", "vadr_phone": "804-555-0142"},
                  ["clinical"], "23220", "memory_clinic", "yes", "done", {}],
    },
    {
        "id": "della_unmet_need",
        "story": "Della (Norfolk) usually needs help with daily activities but can almost "
                 "never get it. Highest urgency. The flow interrupts to offer a callback; "
                 "she shares contact.",
        "steps": ["yes", ["plwd"], "yes", "usually", "usually", "never",
                  {"vadr_name": "Della Pierce", "vadr_phone": "757-555-0173"},
                  "yes", ["clinical"], "23510", "memory_clinic", "yes", "done", {}],
    },
    {
        "id": "anon_unmet_need",
        "story": "An anonymous user (Roanoke) in the same high-urgency situation as Della, "
                 "but chooses NOT to share contact. Shows how a HIGH case is still queued, "
                 "flagged as anonymous, with resources still delivered.",
        "steps": ["yes", ["plwd"], "yes", "usually", "usually", "never",
                  {}, "yes", ["clinical"], "24011", "memory_clinic", "yes", "done", {}],
    },
    {
        "id": "grace_talk_to_person",
        "story": "Grace (Fairfax) feels overwhelmed and taps 'Talk to a person' right away "
                 "instead of answering questions. Routed straight to a human callback.",
        "steps": [HUMAN, {"vadr_name": "Grace Okoro", "vadr_phone": "703-555-0190"},
                  "yes", ["brain_health"], ["community"], "done", {}],
    },
    {
        "id": "out_of_state_dropoff",
        "story": "A user from Maryland answers 'No' to living in Virginia, sees national "
                 "resources, and leaves without finishing. Shows the out-of-state redirect "
                 "and a drop-off.",
        "steps": ["no"],   # leaves at the contact screen → incomplete
    },
    {
        "id": "elaine_no_transport",
        "story": "Elaine (Lynchburg) has early concerns that aren't yet affecting daily life "
                 "and has no car. Wants primary care. The drive-only option is filtered out; "
                 "transportation help stays.",
        "steps": ["yes", ["plwd"], "no", ["clinical"], "24501", "primary_care", "no",
                  "done", {}],
    },
    {
        "id": "tomas_caregiver_community",
        "story": "Tomás (Charlottesville) helps his father and wants community help plus a "
                 "clinic referral. No urgent flags — a smooth routing case.",
        "steps": ["yes", ["caregiver"], "yes", "02", ["community", "clinical"], "22903",
                  "not_sure", "yes", "done", {}],
    },
    {
        "id": "june_research_interest",
        "story": "June (Harrisonburg) has mild changes and is curious about research and a "
                 "clinic. Routed to trials plus the NIH clinic.",
        "steps": ["yes", ["plwd"], "yes", "sometimes", "rarely", ["research", "clinical"],
                  "22801", "memory_clinic", "yes", "yes", "done", {}],
    },
    {
        "id": "midflow_dropoff",
        "story": "A user (Richmond) starts the memory path but leaves after the first "
                 "question. Shows a mid-flow drop-off with no data captured.",
        "steps": ["yes", ["plwd"], "yes"],   # leaves at severity question
    },
]


def run_persona(steps: list) -> dict:
    s = engine.start_session()
    i = 0
    while s["current"] != "__END__":
        node = engine.current_node(s, CFG)
        if node["type"] == "info":
            s = engine.submit(s, CFG, None)
            continue
        if i >= len(steps):
            break  # ran out of steps -> drop-off (status stays in_progress)
        step = steps[i]
        i += 1
        if step == HUMAN:
            s = engine.request_human(s, CFG)
        else:
            s = engine.submit(s, CFG, step)
        for f in s["flags"]:
            if f.get("queue"):
                db.enqueue_escalation(s, f)
    return s


def seed() -> list:
    # Start clean
    for p in (db.ANALYTICS, db.PHI_QUEUE):
        if p.exists():
            p.unlink()
    sessions = []
    for persona in PERSONAS:
        s = run_persona(persona["steps"])
        db.log_session(s)
        for f in s["flags"]:
            if f.get("queue"):
                db.enqueue_escalation(s, f)
        sessions.append((persona, s))
    return sessions


def fmt_flags(s):
    if not s["flags"]:
        return "—"
    return ", ".join(
        f"{f['id']} ({f['tier']}{', ' + str(f['sla_hours']) + 'h' if f.get('sla_hours') else ''})"
        for f in s["flags"]
    )


def print_summary(sessions):
    print(f"Seeded {len(sessions)} sessions.\n")
    print(f"{'persona':28} {'status':12} {'region':7} {'contact':8} flags")
    print("-" * 92)
    for p, s in sessions:
        region = s["answers"].get("vadr_2009_s12_16a")
        region = region[:3] if region else "—"
        contact = "yes" if s["answers"].get("vadr_name") else "no"
        print(f"{p['id']:28} {s['status']:12} {region:7} {contact:8} {fmt_flags(s)}")
    q = db.read_queue()
    print(f"\nCallback queue: {len(q)} case(s) "
          f"({sum(1 for x in q if x['tier']=='HIGH')} HIGH, "
          f"{sum(1 for x in q if x['tier']=='MEDIUM')} MEDIUM).")
    a = db.read_analytics()
    print(f"Analytics: {len(a)} rows, "
          f"{sum(1 for x in a if x['status']=='completed')} completed, "
          f"{sum(1 for x in a if x['status']!='completed')} drop-off(s).")


def print_markdown(sessions):
    print("\n\n===== MARKDOWN REPORT =====\n")
    for p, s in sessions:
        region = s["answers"].get("vadr_2009_s12_16a")
        region = f"ZIP3 {region[:3]}" if region else "no ZIP"
        contact = "shared contact" if s["answers"].get("vadr_name") else "anonymous"
        print(f"### {p['id'].replace('_',' ').title()}")
        print(f"\n{p['story']}\n")
        print(f"- **Outcome:** {s['status']} · {region} · {contact}")
        print(f"- **Flags:** {fmt_flags(s)}")
        if s["status"] == "completed":
            names = [r["name"] for r in engine.match_resources(s, CFG)]
            print(f"- **Resources surfaced:** {', '.join(names) if names else '—'}")
        else:
            print(f"- **Resources surfaced:** left before reaching results")
        # queue view
        qrows = [x for x in db.read_queue() if x["session_id"] == s["session_id"]]
        if qrows:
            for x in qrows:
                who = " · ".join(filter(None, [x.get("name"), x.get("phone")])) or "anonymous (no contact)"
                sla = f"{x['sla_hours']}h" if x.get("sla_hours") else "next-review"
                print(f"- **Coordinator sees:** {x['tier']} · {x['label']} · SLA {sla} · {who}")
        print()


if __name__ == "__main__":
    sessions = seed()
    print_summary(sessions)
    if "--md" in sys.argv:
        print_markdown(sessions)
