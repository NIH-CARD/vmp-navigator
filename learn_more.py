"""
VMP Navigator — "Learn more" assistant (OPTIONAL, opt-in, reference implementation).

This is the ONE place an LLM is allowed in the navigator: general education, on
demand, grounded in advisory-board-approved text. It is deliberately built so that
the unsafe things are hard to do:

  - The public function has NO session/answers/flags/contact parameter. It is
    structurally impossible to pass a user's PHI or questionnaire answers into it.
  - It refuses crisis and personal-detail inputs BEFORE any network call.
  - It is grounded: the model answers from approved reference text, not open domain.
  - It is additive, never load-bearing: any failure returns the curated fallback.
  - It is OFF until a key is available. Provide one via Streamlit secrets
    (.streamlit/secrets.toml -> ANTHROPIC_API_KEY) or the environment. No key = off.

Compliance notes (verify against the live Trust Center before production):
  - The Claude Messages API (api.anthropic.com) is HIPAA-eligible only with a signed
    BAA + HIPAA-enabled org; web search and most beta features are NOT covered.
  - The real control is keeping PHI out of the prompt in the first place. A BAA covers
    Anthropic's side; it does not stop a user typing PHI into a box. Hence the input
    gate below, plus: prefer pre-generated + human-reviewed + cached answers, and do
    not persist the free-text question. For an in-region/no-vendor-egress posture,
    Amazon Bedrock / Vertex keep data inside your cloud under that provider's BAA.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# Default model. Opus 4.8 at MEDIUM effort: adaptive thinking is on, but capped at `medium`
# so the model reasons briefly before a short grounded answer instead of overthinking a 2-4
# sentence reply. Two things this forces in the request below (see answer() / summarize_trials):
#   - NO `temperature`/`top_p`/`top_k`: Opus 4.7/4.8 reject sampling params with a 400.
#   - MAX_TOKENS must cover thinking AND the answer (thinking counts against it), so it is far
#     larger than the ~120 tokens the visible reply needs.
# Override per deployment with VMP_AI_MODEL / VMP_AI_EFFORT (env or Streamlit secrets). An
# override must be an effort-capable, sampling-param-free model (Opus 4.6/4.7/4.8, Sonnet 4.6);
# Haiku 4.5 and Sonnet 4.5 reject the effort param. Any failure falls back to curated text, so
# a bad override degrades gracefully rather than breaking the page.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "medium"      # low | medium | high | max
MAX_TOKENS = 2048              # headroom for adaptive thinking + the short answer


def model_name() -> str:
    return os.environ.get("VMP_AI_MODEL") or DEFAULT_MODEL


def effort() -> str:
    return os.environ.get("VMP_AI_EFFORT") or DEFAULT_EFFORT

FOOTER = ("\n\n_General information, not medical advice. For your specific situation, "
          "a clinician or the VMP team can help._")

CRISIS_REPLY = ("If you or someone else may be in danger, please call 911 now. "
                "For a mental-health crisis, call or text 988. You can also reach the "
                "Alzheimer's Association 24/7 Helpline at 800-272-3900.")

PHI_REPLY = ("To protect your privacy, please ask in general terms and leave out "
             "personal details like names, phone numbers, dates of birth, or medical "
             "record numbers. For help with a specific person's situation, the VMP team "
             "or a clinician can assist.")

SYSTEM_PROMPT = """You are the Virginia Memory Project's information assistant. You give \
GENERAL, plain-language education about memory, thinking, brain health, aging, and \
dementia (including Alzheimer's disease), and about caring for someone with these \
conditions, for people in Virginia.

STAY IN DOMAIN. Only discuss memory, cognition, brain health, healthy aging, dementia and \
Alzheimer's disease, caregiving for those conditions, and the related clinical care, \
community support, and research options. If a question falls outside this domain, briefly \
say it is outside what you can help with here and point to the VMP team or a clinician.

Use ONLY the reference material provided in the user message, plus widely-accepted \
general knowledge about how memory care, caregiver support, and clinical research work. \
If a question cannot be answered from that, say the VMP team or a clinician can help, and \
do not guess.

You may receive a short note about the reader's PERSPECTIVE (for example, that they are a \
caregiver, which kind of help interests them, or an approximate ZIP region). Use it only \
to choose tone and framing — for example, addressing a caregiver about the person they \
support, or noting that services exist in their general area. It is NOT a clinical fact \
about the reader. Any location is approximate (a 3-digit ZIP region) — you may acknowledge \
the general area, but do not name a specific local facility or address, and do not infer \
or state anything about the reader's own health or assume any diagnosis.

You must NEVER:
- diagnose, estimate risk, or interpret the reader's symptoms, situation, or their \
answers to any questionnaire;
- tell the reader whether they or anyone else has a condition;
- give individualized medical, legal, or financial advice, or specific treatment, \
medication, or dosing guidance;
- invent specifics (hours, cost, phone numbers, eligibility, wait times, addresses) \
about any named clinic or organization — describe the type of service generally and tell \
the reader to call to confirm.

If the reader describes a medical emergency, thoughts of self-harm, or someone in danger, \
respond only that they should call 911 (or 988 for a mental-health crisis), and stop.

Keep answers brief (2-4 sentences), warm, and at about a 6th-grade reading level."""

# Defense-in-depth pattern matching. These are intentionally simple and MUST be replaced
# by a real DLP / safety classifier in production; they are not sufficient on their own.
_CRISIS = re.compile(
    r"\b(kill myself|killing myself|end my life|want to die|suicid|hurt myself|"
    r"harm myself|overdose|take my life|jump off|no reason to live)\b", re.I)

_PHI = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                       # SSN
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),             # phone
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b\d{6,}\b"),                                  # long id / MRN
    re.compile(r"\b(my|his|her|their)\s+name\s+is\b", re.I),    # explicit naming
    re.compile(r"\b(date of birth|dob|social security|medical record|mrn)\b", re.I),
]

_OUTPUT_BLOCK = re.compile(
    r"\b(you (likely )?have|you are showing signs|you should take|i recommend taking|"
    r"prescrib|your diagnosis is)\b", re.I)


# --- Non-identifying context allowlist ---------------------------------------
# The ONLY context that may reach the model is coarse perspective: which audience the
# reader is, and which service tracks interest them. The user's specific questionnaire
# answers, flags, ZIP, and contact are NEVER eligible. _safe_context() drops anything not
# on this allowlist, so the context channel cannot be used to smuggle PHI into the prompt.
_ALLOWED_AUDIENCE = {"self", "caregiver", "both", "general"}
_ALLOWED_TRACKS = {"clinical", "community", "research"}
_ZIP3_RE = re.compile(r"^\d{3}$")   # exactly 3 digits — a full ZIP can never pass this

_AUDIENCE_PHRASE = {
    "self": "someone exploring their own memory or thinking",
    "caregiver": "someone helping care for a person with memory concerns",
    "both": "a person with their own memory concerns who is also a caregiver",
    "general": "someone looking for general information",
}


def _safe_context(context) -> dict:
    """Return ONLY allowlisted, non-identifying perspective. Everything else is discarded."""
    if not isinstance(context, dict):
        return {}
    safe = {}
    aud = context.get("audience")
    if aud in _ALLOWED_AUDIENCE:
        safe["audience"] = aud
    tracks = context.get("tracks")
    if isinstance(tracks, (list, tuple, set)):
        keep = sorted({t for t in tracks if t in _ALLOWED_TRACKS})
        if keep:
            safe["tracks"] = keep
    z = context.get("region_zip3")
    if isinstance(z, str) and _ZIP3_RE.match(z):   # 3 digits only; full ZIPs are rejected
        safe["region_zip3"] = z
    return safe


def _context_line(safe: dict) -> str:
    if not safe:
        return ""
    parts = []
    if "audience" in safe:
        parts.append(f"the reader is {_AUDIENCE_PHRASE[safe['audience']]}")
    if "tracks" in safe:
        parts.append("they are interested in " + ", ".join(safe["tracks"]))
    if "region_zip3" in safe:
        parts.append(f"their approximate area is ZIP region {safe['region_zip3']}xx")
    return ("Reader perspective (for tone and framing only, not a clinical fact about "
            "the reader): " + "; ".join(parts) + ".\n\n")


def is_enabled() -> bool:
    """Live unless no key is available. The presence of a key (in Streamlit secrets or
    the environment) is the deliberate opt-in. No key -> the feature is off and all
    calls return the curated fallback."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# --- De-identified usage telemetry (the "proof of use") ----------------------
# We log that a call happened and how it resolved — NEVER the question or the answer.
USAGE_LOG = Path(__file__).parent / "data" / "ai_usage.jsonl"


def _log_usage(topic_key: str, outcome: str, latency_ms: int, output_chars: int,
               error_type: str | None = None) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "topic_key": topic_key,           # which explainer/resource — not PHI
        "model": model_name(),
        "outcome": outcome,               # answered | blocked_* | fallback_*
        "latency_ms": latency_ms,
        "output_chars": output_chars,     # length only, never the text
    }
    if error_type:
        # Exception CLASS name only (e.g. "ModuleNotFoundError", "NotFoundError") so silent
        # fallbacks are diagnosable. Never the exception message — it could echo input.
        rec["error_type"] = error_type
    try:
        USAGE_LOG.parent.mkdir(exist_ok=True)
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass  # telemetry must never break the user experience


def read_usage() -> list[dict]:
    if not USAGE_LOG.exists():
        return []
    with open(USAGE_LOG, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _looks_like_crisis(text: str) -> bool:
    return bool(_CRISIS.search(text or ""))


def _looks_like_phi(text: str) -> bool:
    return any(p.search(text or "") for p in _PHI)


def answer(topic_key: str, question: str, grounding_text: str, *, fallback_text: str,
           context: dict | None = None) -> str:
    """Return a short, grounded answer to a GENERAL question.

    `context` may carry ONLY coarse, non-identifying perspective (audience + tracks); it is
    run through _safe_context() so the user's questionnaire answers, flags, ZIP, or contact
    can never reach the prompt. There is deliberately no parameter for session/answers/PHI.

    Order of operations (fail safe, fail closed):
      1. empty question  -> fallback
      2. crisis language -> crisis reply (no model call)
      3. personal detail -> privacy reply (no model call)
      4. feature off / SDK missing / any error / blocked output -> fallback
      5. otherwise       -> grounded model answer + footer
    """
    q = (question or "").strip()
    if not q:
        _log_usage(topic_key, "fallback_empty_question", 0, 0)
        return fallback_text
    if _looks_like_crisis(q):
        _log_usage(topic_key, "blocked_crisis", 0, len(CRISIS_REPLY))
        return CRISIS_REPLY
    if _looks_like_phi(q):
        _log_usage(topic_key, "blocked_phi", 0, len(PHI_REPLY))
        return PHI_REPLY
    if not is_enabled():
        _log_usage(topic_key, "fallback_disabled", 0, 0)
        return fallback_text

    user_content = (
        _context_line(_safe_context(context))
        + f"Reference material:\n<<<\n{grounding_text}\n>>>\n\n"
        + f"Reader's question: {q}\n\n"
        + "Answer in 2-4 short sentences using only the reference material and general "
          "knowledge as instructed."
    )
    t0 = time.monotonic()
    try:
        import anthropic  # imported lazily so the app runs without the package
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        msg = client.messages.create(
            model=model_name(),
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": effort()},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        _log_usage(topic_key, "fallback_error", int((time.monotonic() - t0) * 1000), 0,
                   error_type=type(e).__name__)
        return fallback_text  # network/SDK/auth failure -> curated baseline

    latency_ms = int((time.monotonic() - t0) * 1000)
    if not text or _OUTPUT_BLOCK.search(text):
        _log_usage(topic_key, "fallback_blocked_output", latency_ms, len(text or ""))
        return fallback_text
    # Do NOT persist `q` or `text`. Telemetry above records only metadata.
    _log_usage(topic_key, "answered", latency_ms, len(text))
    return text + FOOTER


# --- Trials summary: explain REAL ClinicalTrials.gov results (never invent studies) -----
TRIALS_SYSTEM = """You help people in Virginia understand current Alzheimer's, dementia, \
and memory research studies. You will be given a list of REAL studies retrieved live from \
ClinicalTrials.gov.

Use ONLY the studies in the provided list. NEVER add studies, NCT numbers, eligibility \
criteria, locations, dates, or contacts that are not in the list, and never change the \
details given. Do not tell the reader whether they qualify — eligibility is decided by \
each study team. Do not give medical advice or interpret the reader's own health.

Write 2-4 short, warm, plain-language sentences (about a 6th-grade reading level) that give \
an overview of what these studies are about. If any study is marked [NIH Clinical Center], \
point it out as a notable option to consider. Remind the reader that taking part is \
voluntary, that eligibility is set by each study team, and that they should talk with their \
doctor and confirm details on ClinicalTrials.gov. Stay within memory/dementia/aging \
research."""


def summarize_trials(trials_list: list[dict], *, fallback_text: str, context: dict | None = None) -> str:
    """Summarize a list of REAL trial records (from trials.search_trials) in plain language.

    Grounded strictly in the provided studies. Carries no PHI — only the public trial data
    and the non-identifying perspective allowlist. Off (or any failure) -> fallback_text.
    """
    if not trials_list:
        return fallback_text
    if not is_enabled():
        _log_usage("trials_summary", "fallback_disabled", 0, 0)
        return fallback_text

    listing = "\n".join(
        f"- {t.get('title')}{' [NIH Clinical Center]' if t.get('is_nih') else ''} "
        f"(status: {t.get('status')}; "
        + "sites: " + "; ".join(
            f"{s.get('facility') or '—'}, {s.get('city') or '—'}" for s in (t.get('sites') or [])[:2]
        )
        + f"; {t.get('url')})"
        for t in trials_list
    )
    user_content = (
        _context_line(_safe_context(context))
        + "Studies retrieved live from ClinicalTrials.gov:\n" + listing
        + "\n\nSummarize these studies for the reader as instructed."
    )
    t0 = time.monotonic()
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model_name(), max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"}, output_config={"effort": effort()},
            system=TRIALS_SYSTEM, messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        _log_usage("trials_summary", "fallback_error", int((time.monotonic() - t0) * 1000), 0,
                   error_type=type(e).__name__)
        return fallback_text
    latency_ms = int((time.monotonic() - t0) * 1000)
    if not text or _OUTPUT_BLOCK.search(text):
        _log_usage("trials_summary", "fallback_blocked_output", latency_ms, len(text or ""))
        return fallback_text
    _log_usage("trials_summary", "answered", latency_ms, len(text))
    return text + FOOTER


# --- Staff-only request-shape probe (temporary diagnostic) -------------------
# The de-identified usage log records only the error CLASS, never the API's message, so a
# 400 can't be diagnosed from telemetry alone. This probe makes a few live calls with a
# FIXED, non-PHI staff question and returns each variant's raw result so staff can see WHICH
# request shape this key + model accepts. It takes no user input and persists nothing, so the
# "no free text" and "no session in prompt" guarantees are intact. Remove once the shape is known.
def diagnose() -> list[dict]:
    if not is_enabled():
        return [{"variant": "disabled", "ok": False, "detail": "no ANTHROPIC_API_KEY"}]
    try:
        import anthropic
    except Exception as e:
        return [{"variant": "import anthropic", "ok": False, "detail": type(e).__name__}]
    client = anthropic.Anthropic()
    base = dict(model=model_name(), max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "What is an Area Agency on Aging?"}])
    variants = [
        ("thinking+effort", {**base, "thinking": {"type": "adaptive"},
                             "output_config": {"effort": effort()}}),
        ("effort only", {**base, "output_config": {"effort": effort()}}),
        ("thinking only", {**base, "thinking": {"type": "adaptive"}}),
        ("plain (model only)", dict(base)),
    ]
    results = []
    for name, kwargs in variants:
        try:
            msg = client.messages.create(**kwargs)
            txt = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            results.append({"variant": name, "ok": True, "detail": f"ok · {len(txt)} chars"})
        except Exception as e:
            detail = getattr(e, "message", None) or str(e)
            results.append({"variant": name, "ok": False,
                            "detail": f"{type(e).__name__}: {detail}"})
    return results
