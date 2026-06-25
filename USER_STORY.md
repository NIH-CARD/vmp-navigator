# VMP Care Navigator — User Stories & Sample Data

This document walks the navigator's user story with concrete synthetic data. The
same personas described here are what `seed_data.py` loads, so you can read a
journey below and then see it in the running app.

> All data is synthetic. Names and phone numbers are fictional. The "PHI" callback
> queue is a local mock — production writes to REDCap.

## Load the data

```bash
cd VMP_navigator
pip install -r requirements.txt
python seed_data.py        # clears, then seeds 11 personas (use --md to print this report)
streamlit run app.py       # open the Coordinator (staff) view to see the result
```

`seed_data.py` runs each persona through the **real engine**, so the analytics and
callback queue you see are exactly what those journeys produce — nothing is faked.

## What the coordinator sees after seeding

- **11 sessions** · 9 completed · 2 drop-offs
- **Callback queue: 5 cases** — 4 HIGH, 1 MEDIUM
- **6 regions** represented (ZIP3: 232 Richmond, 235 Norfolk, 240 Roanoke, 245 Lynchburg, 229 Charlottesville, 228 Harrisonburg)
- One HIGH case is **anonymous** (no contact shared) — it's still queued so a coordinator knows the volume of unmet need, even when there's no one to call back

---

## The core user story, screen by screen

**Della (Norfolk) usually needs help with daily activities but can almost never get it.**
This is the highest-urgency path, and it shows the full arc: guided questions →
urgent flag → interrupt → human callback → resources, with the two data streams
filling correctly.

| # | Screen | Della's answer |
|---|---|---|
| 1 | Welcome + "not medical advice / call 911" disclaimer | Continue |
| 2 | "Do you live in Virginia?" | Yes |
| 3 | "What brings you here today?" | I notice changes in my own thinking or memory |
| 4 | "Worsening confusion or memory loss in the past 12 months?" | Yes |
| 5 | "How often has memory loss caused you to give up daily activities?" | Usually |
| 6 | "How often do you need help with day-to-day activities?" | Usually |
| 7 | "When you need help, how often are you able to get it?" | **Never** |
| — | 🚩 **Flag fires:** `unmet_care_need` (HIGH, 8-hour SLA). Routing **interrupts.** | |
| 8 | "Let's get you connected — would it be OK if someone reached out?" | Shares name + phone, taps **Share my info** |
| — | Case is written to the callback queue *with contact*. Flow resumes. | |
| 9 | "Have you talked with a healthcare provider?" | Yes |
| 10 | "What would you like help with today?" | Finding clinical care |
| 11 | "What's your ZIP code?" | 23510 |
| 12 | "What kind of care are you looking for?" | Memory or thinking concerns |
| 13 | "Can you drive, or have access to a car?" | Yes |
| 14 | "Anything else?" | No, I'm all set |
| 15 | "Would you like someone to follow up? (Optional)" | Skip — already shared |
| 16 | **Results** | See below |

**Results screen:** a green confirmation — *"Someone from the VMP team will reach
out to you within 8 hours"* — followed by resources, with the **NIH Memory & Aging
Clinic** carrying a "Priority connection" pill, plus Virginia DARS Memory Assessment
Centers, Medicare Care Compare, the local Area Agency on Aging, and the 24/7 Helpline.

**What the two streams captured:**

- *Stream A — analytics (de-identified):* `entry_categories: [plwd]`,
  `service_tracks: [clinical]`, `region_zip3: 235`, `flags: [unmet_care_need/HIGH]`.
  **No name, no phone, ZIP truncated to 3 digits.**
- *Stream B — callback queue (mock PHI):* `HIGH · Needs help but rarely/never
  receives it · SLA 8h · Della Pierce · 757-555-0173 · status: open`.

The coordinator can act on the queue; the analytics can be shared for reporting
without exposing anyone.

---

## All 11 personas

| Persona | Outcome | Region | Contact | Flag |
|---|---|---|---|---|
| Maria — brain health | completed | — | anonymous | — |
| Anita — caregiver burnout | completed | — | shared | caregiver_health_impact (MEDIUM) |
| Robert — no provider | completed | 232 | shared | active_concern_no_provider (HIGH, 48h) |
| Della — unmet need | completed | 235 | shared | unmet_care_need (HIGH, 8h) |
| Anonymous — unmet need | completed | 240 | anonymous | unmet_care_need (HIGH, 8h) |
| Grace — talk to a person | completed | — | shared | user_requested_human (HIGH, 24h) |
| Out-of-state visitor | drop-off | — | anonymous | out_of_virginia (WATCH) |
| Elaine — no transport | completed | 245 | anonymous | — |
| Tomás — caregiver + clinic | completed | 229 | anonymous | — |
| June — research interest | completed | 228 | anonymous | — |
| Mid-flow drop-off | drop-off | — | anonymous | — |

### What each persona is here to prove

- **Maria** — a low-acuity user gets useful resources, raises no flags, and leaves
  no identifying trace. The anonymous-by-default promise in action.
- **Anita** — caregiving is harming her health (a MEDIUM flag). She enters the
  review queue for follow-up at the next opportunity, not an urgent interrupt.
- **Robert** — an active concern with **no provider** is the gap. HIGH (48h), routed
  to clinical care, contact captured. Shows the no-provider branch.
- **Della** — the highest-urgency unmet-need path (8h), walked above.
- **Anonymous unmet need** — *same urgency as Della, no contact shared.* Proves a
  HIGH case is still counted and queued (flagged "anonymous"), and resources are
  delivered regardless. Identity is never a gate.
- **Grace** — taps "Talk to a person" immediately. A user can reach a human at any
  point without finishing the questions (HIGH, 24h).
- **Out-of-state visitor** — answers "No" to living in Virginia, is redirected to
  **national-only** resources (Virginia-specific ones are withheld), and drops off.
  Shows the WATCH flag and a drop-off.
- **Elaine** — early concerns, **no car**: the drive-only primary-care option is
  filtered out while transportation help (Area Agency on Aging) stays. Shows
  resource filtering by transportation.
- **Tomás** — a clean multi-track routing case (community + clinic), no urgent flags.
- **June** — routed to **research/trials** plus the NIH clinic. Shows the research track.
- **Mid-flow drop-off** — leaves after the first question with nothing captured.
  Shows how incomplete sessions surface in the drop-off chart.

### Coverage at a glance

| What's exercised | Personas |
|---|---|
| All escalation tiers (HIGH / MEDIUM / WATCH) | Robert, Della, Anon, Grace / Anita / Out-of-state |
| Every HIGH flag rule | Della & Anon (unmet need), Robert (no provider), Grace (requested human) |
| Anonymous vs. shared contact | Maria, Anon, Elaine, Tomás, June / Anita, Robert, Della, Grace |
| Completed vs. drop-off | 9 completed / Out-of-state, Mid-flow |
| Resource filtering (transport, out-of-state, tracks) | Elaine, Out-of-state, Tomás, June |
| Priority NIH connection always present | all personas |
| Regional spread for the dashboard | Robert, Della, Anon, Elaine, Tomás, June |

To reset between demos, use **Clear demo data** in the sidebar, then re-run
`python seed_data.py` (or start fresh sessions in the Navigator).
