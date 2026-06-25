# VMP Care Navigator — Phase 1 Prototype

A deterministic, structured-form web navigator for the Virginia Memory Project. It
asks short questions one at a time (no free text), routes people to Virginia
clinical / community / research resources — with the **NIH Memory & Aging Clinic**
as a priority connection — flags urgent cases for human follow-up, and logs
de-identified activity for a coordinator dashboard.

> **Prototype, synthetic data only.** There is **no LLM at runtime** and the
> "PHI" callback queue is a local mock. In production, identifiable data goes to
> REDCap (HIPAA-compliant), never to a local file or any external API.

## Run it

```bash
cd VMP_navigator
python -m venv .venv && source .venv/bin/activate      # optional
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually http://localhost:8501).

## Run the tests

```bash
python tests/test_engine.py        # or:  python -m pytest tests/ -v
```

The persona suite runs synthetic users through the trees and asserts path,
escalation flags, and matched resources. Because the logic is deterministic,
**this suite is the clinical regression guard** — an edit that changes a
vulnerable persona's route fails here.

## Sample data & user stories

```bash
python seed_data.py        # clears, then loads 11 synthetic personas
```

This runs a representative set of users (low-acuity, urgent, anonymous, caregiver,
out-of-state, drop-offs) through the **real engine** and writes their de-identified
analytics and flagged callback cases — so the **Coordinator (staff)** view is
populated the moment you open it. The seeded data ships with the project, so the
dashboard works on first launch even before you run the script.

**[`USER_STORY.md`](USER_STORY.md)** documents every persona, walks the
highest-urgency journey screen by screen, and shows exactly what each data stream
captures. Add `--md` (`python seed_data.py --md`) to regenerate that report from
live output.

## Try it (demo script)

In the **Navigator** view (sidebar):
- **Anonymous, low-acuity:** "I want brain-health info" → community → skip contact.
  You get resources with no flags and no data captured.
- **No provider (HIGH, 48h):** PLWD → worsening **Yes** → mild severity → at "talked
  with a provider?" answer **No**. The flow interrupts and offers a callback.
- **Unmet need (HIGH, 8h):** PLWD → worsening **Yes** → needs help **Usually** → gets
  help **Never**. Immediate interrupt + callback.
- **Talk to a person:** click the sidebar button at any point → HIGH callback (24h).
- **Out of state:** answer **No** to "live in Virginia?" → national resources only.

Then switch to the **Coordinator (staff)** view to see the human-review queue
(with the mock-PHI banner) and the de-identified activity counts. Use **Clear demo
data** to reset between demos.

## The "Learn more" assistant (live Claude call, key via Streamlit secrets)

The app ships **LLM-free** and stays that way until you provide a key. To turn on the
live, grounded "Learn more" follow-up box inside the "More about this" expanders:

```bash
pip install -r requirements-ai.txt
mkdir -p .streamlit && cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and paste your ANTHROPIC_API_KEY
streamlit run app.py
```

That's the only setup — the app reads the key from Streamlit secrets. No key = the
feature is simply off and the curated text is shown.

**No free-text entry.** Under "More about this," users tap from a small set of **vetted
common questions** (buttons) — the model can only ever be asked an approved question,
grounded in the reviewed explainer text. This removes the free-text channel entirely, so
there is no way for a user to type personal information into the assistant.

**Tailored, but not identifiable.** Answers use only *coarse perspective* — whether the
reader is a person with memory concerns or a caregiver, which track interests them, and the
**first three ZIP digits** (a HIPAA Safe Harbor element, the same region granularity used in
the analytics stream) — passed through an allowlist that strips everything else. The user's
specific answers, flags, full ZIP, and contact never reach the model, and a full ZIP is
rejected even if mistakenly supplied. The assistant is also **domain-locked** to memory,
brain health, aging, and dementia/Alzheimer's.

> **A note for reviewers.** The assistant is deliberately *under*-personalized right now —
> by design, for a conservative IRB path. It tailors only on non-identifying signals
> (audience, track, 3-digit ZIP region) and never on the individual's clinical answers.
> Richer personalization is straightforward to enable later (the context allowlist in
> `learn_more.py` is the single switch) if the advisory board and IRB approve it with the
> appropriate data-handling controls.

**Prove it works** two ways:
- `python verify_ai.py` makes one real call on a benign question, prints the answer and
  latency, then shows the crisis/personal-info gates firing and that telemetry stores no
  transcript.
- In the app, open **Coordinator (staff) → AI assistant (diagnostics)** for a live status
  line, a **Test the assistant** button, and de-identified usage counts (calls, answered
  live, average latency).

It's built so the unsafe things are hard to do: the function takes **no session data** (PHI
can't be passed in), it blocks crisis and personal-detail inputs *before* any call, it
answers only from approved text, any failure falls back to curated content, and the usage
log records metadata only — never the question or answer. See **[`AI_FEATURES.md`](AI_FEATURES.md)**
and `tests/test_learn_more_guardrails.py`.

> Synthetic-data testing only. Before real users, decide the data-handling path (1P API +
> BAA, or Bedrock/Vertex) with your privacy office — see AI_FEATURES.md.

## Developing with Claude Code

This repo is set up for [Claude Code](https://code.claude.com). Install it
(`npm install -g @anthropic-ai/claude-code`, or `curl -fsSL https://claude.ai/install.sh | sh`),
then from the project root run `claude`. It auto-loads `CLAUDE.md` (project brief + the hard
safety rules), and `.claude/` ships project permissions and a few slash commands:

- `/test` — run both test suites and report results
- `/seed` — reload the synthetic personas into the dashboard
- `/run` — start the Streamlit app

`.claude/settings.json` pre-approves the project's test/seed/run commands and denies reading
`secrets.toml` and the mock PHI queue. Personal overrides go in `.claude/settings.local.json`
(git-ignored). Start a change with `/plan`, and before shipping use `/diff` and `/code-review`.

## Current local clinical trials (live ClinicalTrials.gov)

On the results screen, Virginia users can tap **Find current studies** to pull *current,
recruiting* Alzheimer's/dementia studies with a Virginia site **or at the NIH Clinical Center in Bethesda, MD** (NIH studies highlighted), live from the
[ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api) (public, no key). The
real studies are shown with their status, site, and a link to the registry; if an Anthropic
key is configured, Claude adds a short plain-language summary **grounded only in those
retrieved results** — it is instructed never to invent studies, NCT numbers, eligibility, or
sites. Currency comes from the live registry, not the model. Needs internet; if the registry
is unreachable, the app shows a link to search it directly. (`trials.py`, 6-hour cache.)

## What's here

| File | Role |
|---|---|
| `config/questions.yaml` | The decision-tree graph — **clinical content lives here, not in code** |
| `config/flags.yaml` | Tree 5 escalation rules (HIGH interrupts + MEDIUM/WATCH) |
| `config/resources.yaml` | Curated VA + national resources (**stub URLs — verify before real use**) |
| `config/explainers.yaml` | Curated "More about this" content, by question and resource type |
| `engine.py` | Pure interpreter: flow + flags + resource matching (no Streamlit) |
| `persistence.py` | Two separate streams: de-identified analytics vs mock PHI queue |
| `app.py` | Streamlit UI (navigator + coordinator) |
| `seed_data.py` | Loads synthetic personas into the dashboard; `--md` prints the journey report |
| `learn_more.py` | Live, grounded "Learn more" Claude call (enabled by a key in secrets) |
| `trials.py` | Live ClinicalTrials.gov lookup for current local dementia studies |
| `verify_ai.py` | One-command proof: makes a real call and shows the guardrails holding |
| `tests/test_engine.py` | Persona-driven regression tests |
| `tests/test_learn_more_guardrails.py` | Offline safety tests for the AI feature |
| `USER_STORY.md` | Persona walkthroughs + sample-data documentation |
| `AI_FEATURES.md` | Where an LLM call is useful/safe vs. risky vs. off-limits (for management/IRB) |
| `CLAUDE.md` | Guardrails for continuing the build in Claude Code |

## Scope

**Implemented end-to-end:** Tree 1 entry, Tree 2 PLWD path, Tree 4 Clinical Track,
Tree 5 HIGH flags + queue, de-identified logging, VA clinical dataset incl. the
NIH clinic, coordinator dashboard, accessibility-minded UI, persona tests.
**Lighter / stubbed:** caregiver path (Tree 3), community & research tracks,
REDCap write-back (mock). The research track links out to a **placeholder clock-drawing
collector** (a separate VMP app) as a Phase 2 hand-off.
**Out of scope (later):** live CMS/DARS lookups, ML triage, in-navigator
neurocognitive/biomarker collection, voice/cognitive screening.

## Before any real-user pilot (governance gates)

- IRB review for real-user/research-adjacent data collection
- Advisory-board sign-off on the trees, thresholds, microcopy, and SLAs
- **HIPAA-compliant hosting + executed BAAs** for any environment touching real PHI
- A defined human + SLA capacity for the callback queue
- Reconcile `config/*.yaml` field names against the live REDCap data dictionary
- Replace the mock PHI sink with a real REDCap write-back; add an accessibility
  audit (WCAG 2.1 AA)
- The **clock-drawing collector is a separate app** and must carry its own IRB approval,
  consent flow, and PHI handling; the navigator only links to it and sends no user data in
  the URL (verify the placeholder URL before launch)
