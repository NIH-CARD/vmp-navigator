# VMP Care Navigator — Claude Code project brief

Read this first; it is loaded every session. Keep it short and current.

## What this is
A Phase 1 prototype for the Virginia Memory Project: a **deterministic, structured-form**
web navigator (Streamlit, Python) that routes people — people living with dementia,
caregivers, the brain-health-curious — to Virginia clinical/community/research resources
(priority: the NIH Memory & Aging Clinic), flags urgent cases for human callback, logs
de-identified activity, and offers an optional live "Learn more" Claude assistant. Users
are often cognitively impaired or stressed older caregivers. **Synthetic data only.**

## Hard rules — do not break these
- **Routing/flagging is DETERMINISTIC.** No LLM in the decision path. Tree 5 escalation and
  resource matching must stay rule-based and testable.
- **No PHI to any LLM.** The "Learn more" assistant takes no session/answers/flags/contact.
  The only context allowed is the non-identifying allowlist in `learn_more._safe_context`
  (audience, tracks, 3-digit ZIP). A full ZIP or any answer must never reach a prompt.
- **No free-text entry to the assistant.** Users tap vetted question buttons only.
- **Assistant is domain-locked** to memory/cognition/brain-health/aging/dementia, and is
  additive — any failure falls back to curated text. It is OFF unless an API key is present.
- **Contact is always optional;** resources are never gated behind identity.
- **Navigator, not diagnostic.** Never show a risk score or clinical interpretation.
- The **clock-drawing collector is a separate app**; we only link out, sending no user data
  in the URL. It owns its own consent/IRB/PHI handling.
- **Trial/“current” facts come from retrieval, not the model.** Live data (e.g.
  ClinicalTrials.gov in `trials.py`) is the source of truth; the LLM may only summarize
  retrieved results and must never invent studies, NCT numbers, eligibility, or sites.
- Clinical logic and content live in `config/*.yaml`, never hardcoded in Python.

## Architecture
- `config/questions.yaml` — decision-tree graph (nodes + gotos). Clinical content lives here.
- `config/flags.yaml` — Tree 5 escalation rules (HIGH interrupts + MEDIUM/WATCH).
- `config/resources.yaml` — curated VA + national resources (STUB URLs — verify).
- `config/explainers.yaml` — "More about this" text + vetted question buttons, by node/type.
- `engine.py` — pure interpreter: flow + flags + resource matching (no Streamlit).
- `persistence.py` — two streams, never crossed: A) `analytics.jsonl` de-identified (ZIP3,
  no PHI); B) `phi_queue.json` MOCK PHI callback queue (REDCap in production).
- `learn_more.py` — optional live "Learn more" Claude call; guardrails + allowlist + telemetry.
- `trials.py` — live ClinicalTrials.gov lookup: current dementia studies in Virginia + the NIH
  Clinical Center (Bethesda, MD), NIH-first (pure).
- `app.py` — Streamlit UI (navigator + staff coordinator).
- `seed_data.py` — loads synthetic personas into the dashboard (`--md` prints a report).
- `verify_ai.py` — proves the live call works and the guardrails hold.
- `tests/` — `test_engine.py` (clinical regression), `test_learn_more_guardrails.py` (AI safety),
  `test_trials.py` (trial parsing + grounded summary).

## Commands
- Run the app: `streamlit run app.py`
- Tests: `python tests/test_engine.py` and `python tests/test_learn_more_guardrails.py`
- Seed demo data: `python seed_data.py` (`--md` for the user-story report)
- Prove the AI feature (needs a key): `python verify_ai.py`
- Live trials check (needs internet): `python trials.py`
- Base deps: `pip install -r requirements.txt`; AI feature: `pip install -r requirements-ai.txt`

## Conventions
- Every clinical-logic or routing change ships with a persona test in `tests/test_engine.py`.
- Every AI-safety change ships with a test in `tests/test_learn_more_guardrails.py`.
- AI model is `learn_more.model_name()` (default `claude-opus-4-8` at `medium` effort; override
  `VMP_AI_MODEL` / `VMP_AI_EFFORT`). The request uses adaptive thinking + `output_config.effort`
  and sends NO `temperature` — Opus 4.7/4.8 reject sampling params with a 400; `max_tokens` is
  sized to cover thinking plus the short answer. Overrides must be effort-capable, sampling-free
  models (Opus 4.6/4.7/4.8, Sonnet 4.6); Haiku 4.5 and Sonnet 4.5 reject the effort param.
- Field names mirror the working doc — **reconcile against the live REDCap data dictionary**
  before relying on them (note `vadar_*` vs `vadr_*` inconsistencies).
- Accessibility: one question per screen, plain ~6th-grade language, large/high-contrast UI,
  no time pressure. Keep it calm and conventional, not flashy.

## Don't (inviting traps)
- Don't add a free-text box to the assistant, or pass the session/answers into it "to
  personalize" — use the allowlist. Don't let the LLM triage, score, or interpret the user.
- Don't put clinical thresholds or routing in Python — they go in `config/*.yaml`.
- Don't commit `.streamlit/secrets.toml` or anything in `data/` (see `.gitignore`).
- Don't treat the regex PHI/crisis gate as sufficient — it's defense-in-depth; the real
  controls are "no free text" and "no session in the prompt."

## Definition of done
Config-driven (no clinical logic in code), persona-tested, PHI rules respected, contact
optional, default data synthetic, both test suites green.

## Known next steps
Real REDCap PhiSink (replace mock); deepen Tree 3 caregiver + Tree 6 trial-matching; live
CMS/DARS lookups; accessibility audit (axe); confirm the clock-collector URL + its IRB;
decide the AI data-handling path (1P API + BAA, or Bedrock/Vertex) before any real-user
pilot. See AI_FEATURES.md and README.md.
