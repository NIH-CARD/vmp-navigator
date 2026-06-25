# Where an LLM "Learn more" call fits in the VMP Navigator

A short, defensible answer to "can we add AI?" — so the AI lands where it helps and
not where it hurts.

## One principle

**AI may explain; it must never decide. It runs on no-PHI or de-identified data,
never on the PHI path, and it is additive — if it fails, the user still gets the
curated baseline.**

Routing and urgency flagging stay deterministic and testable (that's what protects
vulnerable users and survives an audit). The only sanctioned role for a model is
*general education on demand*.

## The decision rule

Ask three questions of any proposed AI feature. If all three are "yes," it's a
candidate; if any is "no," it's risky or off-limits.

1. **Could a wrong answer change a clinical or routing outcome?** If yes → no. The
   model must not triage, score, diagnose, or pick who gets flagged.
2. **Does it need the user's answers, free text, or contact (i.e., PHI)?** If yes →
   no, or redesign so it doesn't. Education doesn't need the chart.
3. **Does the user still get a correct result if the model is down or wrong?** Must
   be yes. The model is a layer on top of curated content, never the only path.

**Facts come from retrieval, not the model's memory.** Anything time-sensitive or
verifiable — clinical trials, resource details, eligibility — is fetched live from an
authoritative source (e.g., the ClinicalTrials.gov API) and shown as real data. The LLM
may *summarize* what was retrieved, but is instructed never to add or alter studies, NCT
numbers, eligibility, or sites. An LLM's training data is stale and it hallucinates trials,
so it is never the source of trial facts.

## Useful **and** safe (do these)

| Feature | Why it's safe | Why it's useful |
|---|---|---|
| **"Learn more" follow-ups** on a question or resource, grounded in approved text | No session data in; answers only from reviewed grounding; refuses diagnosis/advice; fails to curated text | Handles the long tail of phrasing curated FAQs can't ("what do I bring to the visit?") |
| **Plain-language / translation rendering** of the *same approved content* | The model is a renderer, not an author; can be pre-generated and human-reviewed once, then cached | Meets an older, diverse, cognitively-impaired population where they are (reading level, Spanish/Korean/Vietnamese/Tagalog) |
| **"Explain this resource"** (what an AAA / memory clinic / clinical trial *is*) | Describes the *category*, not specifics of a named site; grounded | Demystifies the steps people avoid — especially the "am I a guinea pig?" trial fear |
| **"Help me prepare"** — generate a generic list of questions to ask the doctor | Generic checklist, no personal data, nothing to interpret | Empowers patients and caregivers; pure upside |
| **Coordinator: summarize the *de-identified* dashboard** | Reads Stream A only (ZIP3, flags, counts) — never the PHI queue | A real "AI feature" for staff reporting, far from any patient or PHI |
| **Current local trials** — live ClinicalTrials.gov lookup, AI summarizes the *real* results | Currency comes from the live registry, not the model; the AI is told to use only the retrieved studies and never invent NCT numbers, eligibility, or sites; no PHI in the prompt | Gives people *current, local, recruiting* dementia studies — the one thing the model's memory must never be trusted for |

## Tempting but risky (only with heavy guardrails, usually later)

- **Conversational / free-text intake** ("describe your symptoms"). Free text *is*
  PHI, and interpreting it is diagnosis. If ever done, the text must be handled like
  REDCap PHI (BAA + minimum-necessary + input redaction), and interpretation still
  stays out.
- **Personalizing resources to the user's answers via the model.** That feeds
  PHI-ish data in and lets the model make routing-like choices. Keep matching
  deterministic; let the model only *explain* the resources the rules already chose.

## Off-limits (no path in Phase 1)

- **LLM triage / urgency scoring.** Unauditable; replaces the deterministic safety
  logic. Never.
- **Anything that reads the PHI / callback queue.**
- **Crisis or self-harm handling by the model.** Detect and route to 911 / 988 /
  the helpline; do not generate.
- **Inventing specifics** (hours, cost, eligibility) about a named clinic.

## The controls that make the "yes" features safe

These are implemented in `learn_more.py` and checked in
`tests/test_learn_more_guardrails.py`:

1. **No-PHI by construction** — the function signature has no session/answers/contact
   parameter, so PHI can't be passed in even by mistake. (Tested.) **There is also no
   free-text box:** users tap from a fixed set of vetted questions, so the only inputs the
   model ever sees are pre-approved — the input scrubber below is pure backup.
2. **Non-identifying personalization** — answers can be tailored using only *coarse
   perspective*: whether the reader is a person with memory concerns or a caregiver, which
   track interests them, and the first three ZIP digits (a Safe Harbor element). This passes
   through an **allowlist** that drops everything else, so the user's specific questionnaire
   answers, flags, full ZIP, and contact can never reach the prompt (a full ZIP is rejected
   even if supplied). The model is told this is for tone/framing only, not a clinical fact.
   This is intentionally conservative for IRB simplicity; richer personalization is a single
   allowlist change away if the advisory board and IRB approve it.
3. **Domain-locked** — the system prompt restricts the assistant to memory, cognition,
   brain health, aging, and dementia/Alzheimer's, and tells it to redirect anything else.
2. **Input gates before any call** — crisis language → 911/988 reply; personal
   details (SSN/phone/email/name/DOB/MRN) → a privacy redirect. No model call happens.
3. **Grounded generation** — the model answers from approved reference text with a
   system prompt that forbids diagnosis, individualized advice, and invented specifics.
4. **Output gate + fail-closed fallback** — disallowed output or any error returns the
   curated text. The model is never load-bearing.
5. **Don't persist the question** — the free-text question is not written to analytics;
   at most log a topic key and a coarse, de-identified category.
6. **Off until keyed** — the feature is inert until an `ANTHROPIC_API_KEY` is provided
   (via Streamlit secrets or the environment). No key = curated text only.
7. **De-identified usage telemetry** — every call logs metadata (topic, model, latency,
   outcome) but never the question or answer, giving auditable proof of use without a
   transcript. Run `python verify_ai.py` to see a real call plus the gates firing.

## Compliance reality (verify against Anthropic's Trust Center before go-live)

- The **Claude Messages API is HIPAA-eligible only with a signed BAA and a HIPAA-enabled
  organization** (admin signs, sales enables). **Web search and most beta features are
  not covered.** Consumer tiers (Free/Pro/Max/Team), Console/Workbench, and Cowork are
  not covered.
- **The real safeguard is keeping PHI out of the prompt.** A BAA covers Anthropic's
  side; it does not stop a user typing PHI into a box, and it doesn't redact PHI in
  uploads. That's why these features are designed to carry *no* PHI, with an input gate
  as defense-in-depth — not a policy promise.
- For a **no-vendor-egress / in-region** posture, **Amazon Bedrock or Vertex AI** keep
  data inside your cloud under that provider's BAA — often the cleanest healthcare path,
  and consistent with a data-locality-controlled platform.
- **Prefer pre-generated + reviewed + cached** answers (especially translations and the
  common explainers). That converts "a live model talking to patients" into "reviewed
  content," which is cheaper, faster, and far easier for an IRB to approve. Reserve live
  generation for the genuine long tail.

## Rollout gates

- Clinical advisory board reviews the grounding text (`config/explainers.yaml`) and the
  assistant's scope.
- A **refusal eval suite** (diagnosis bait, advice bait, jailbreak, invented-specifics,
  crisis) runs as a release gate, the way the persona suite gates the routing logic.
- BAA / data-handling path decided with your privacy office (1P API + BAA, or
  Bedrock/Vertex) before any feature that *could* see PHI; the education features here
  are designed to need none.
