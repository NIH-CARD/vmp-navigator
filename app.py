"""
VMP Care Navigator — Streamlit prototype.

Run:  streamlit run app.py

Phase 1 scope: deterministic, structured-form navigator (no free text, no LLM at
runtime) that routes people to Virginia clinical/community/research resources,
flags urgent cases for human follow-up, and logs de-identified activity.
SYNTHETIC DATA ONLY — the "PHI" queue is a mock; production writes to REDCap.
"""
from __future__ import annotations

import base64
import html
import os
from pathlib import Path

import streamlit as st

import engine
import learn_more
import persistence as db
import trials

st.set_page_config(page_title="VMP Care Navigator", page_icon="🧠", layout="centered")


def _load_secrets() -> None:
    """Bridge config from Streamlit secrets (.streamlit/secrets.toml or Streamlit Cloud)
    into the environment, where the Anthropic SDK and learn_more look for it. Safe if no
    secrets exist. Honors ANTHROPIC_API_KEY (enables the assistant) and optional
    VMP_AI_MODEL (overrides the default model)."""
    for name in ("ANTHROPIC_API_KEY", "VMP_AI_MODEL"):
        try:
            val = st.secrets.get(name)
        except Exception:
            val = None
        if val and not os.environ.get(name):
            os.environ[name] = val


_load_secrets()

# ---- Accessibility-minded styling (larger type, generous spacing, calm palette) ----
st.markdown(
    """
    <style>
      html, body, [class*="css"] { font-size: 18px; }
      .main .block-container { max-width: 720px; padding-top: 1.5rem; }
      h1, h2, h3 { line-height: 1.25; }
      .stRadio label, .stMultiSelect label { font-size: 1.05rem; }
      div[role="radiogroup"] label { padding: 0.35rem 0; }
      .stButton button { font-size: 1.05rem; padding: 0.55rem 1.1rem; border-radius: 10px; }
      .vmp-disclaimer {
        background: #eef4fb; border-left: 4px solid #2f6db5; border-radius: 8px;
        padding: 0.7rem 0.9rem; margin-bottom: 1rem; font-size: 0.95rem; color: #1f3a5f;
      }
      .vmp-resource {
        border: 1px solid #dfe4ea; border-radius: 10px; padding: 0.8rem 1rem; margin-bottom: 0.7rem;
      }
      .vmp-priority { border-color: #2f6db5; background: #f5f9ff; }
      .vmp-pill { display:inline-block; font-size:0.72rem; font-weight:600; color:#fff;
                  background:#2f6db5; border-radius:999px; padding:2px 8px; margin-left:6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_config() -> dict:
    return engine.load_config()


CFG = get_config()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sess() -> dict:
    if "sess" not in st.session_state:
        st.session_state.sess = engine.start_session()
        st.session_state.pop("_logged", None)
    return st.session_state.sess


def reset() -> None:
    st.session_state.sess = engine.start_session()
    st.session_state.pop("_logged", None)


def commit(value) -> None:
    """Advance the engine, sync any flagged cases to the queue, and rerun."""
    s = engine.submit(sess(), CFG, value)
    _sync_queue(s)
    st.rerun()


def _sync_queue(s: dict) -> None:
    for f in s["flags"]:
        if f.get("queue"):
            db.enqueue_escalation(s, f)


def label_map(node: dict) -> dict:
    return {o["value"]: o["label"] for o in node["options"]}


ASSETS = Path(__file__).parent / "assets"
PARTNER_LOGOS = [
    "centerforalzheimersandrelateddementias_logo.png",
    "VCU_logo.png",
    "datatecnicahoriz_logo.png",
]


def _logo_tag(path: Path, height: int = 44) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return (f'<img src="data:image/png;base64,{b64}" alt="" '
            f'style="height:{height}px;margin:0 16px 8px;vertical-align:middle;">')


def render_partner_logos() -> None:
    paths = [ASSETS / n for n in PARTNER_LOGOS if (ASSETS / n).exists()]
    if not paths:
        return
    imgs = "".join(_logo_tag(p) for p in paths)
    st.markdown(
        f'<div style="text-align:center;padding:0.5rem 0 1.2rem;line-height:1;">{imgs}</div>',
        unsafe_allow_html=True,
    )


def ai_context(s: dict | None) -> dict:
    """Coarse, non-identifying perspective for the AI assistant — audience and tracks only.
    The user's specific answers, flags, ZIP, and contact are deliberately excluded; the
    module re-filters this through an allowlist as well."""
    if not s:
        return {}
    a = s.get("answers", {})
    cats = a.get("vadr_wellbeing") or []
    plwd, cg = "plwd" in cats, "caregiver" in cats
    audience = "both" if (plwd and cg) else "self" if plwd else "caregiver" if cg else "general"
    tracks = [t for t in (a.get("service_tracks") or []) if t in ("clinical", "community", "research")]
    ctx = {"audience": audience, "tracks": tracks}
    z = a.get("vadr_2009_s12_16a")
    if isinstance(z, str) and z[:3].isdigit():   # first 3 ZIP digits only — never the full ZIP
        ctx["region_zip3"] = z[:3]
    return ctx


def explainer(key: str, scope: str = "nodes") -> None:
    """Show a curated 'More about this' expander if content exists for this key.
    General education only — no LLM, no PHI, no interpretation of the user's answers."""
    item = (CFG.get("explainers", {}).get(scope, {}) or {}).get(key)
    if item:
        with st.expander("ℹ️ More about this"):
            st.markdown(f"**{item['title']}**")
            st.write(item["body"])
            # No free-text entry: only curated, vetted questions as buttons. The model
            # can only ever be asked one of these approved questions. (Off without a key.)
            if learn_more.is_enabled() and item.get("questions"):
                akey = f"lm_a_{scope}_{key}"
                st.caption("Common questions:")
                for idx, ques in enumerate(item["questions"]):
                    if st.button(ques, key=f"q_{scope}_{key}_{idx}"):
                        with st.spinner("Asking…"):
                            ans = learn_more.answer(
                                key, ques, item["body"],
                                fallback_text=("I can't answer that here, but the VMP team or a "
                                               "clinician can help. You can also call the Alzheimer's "
                                               "Association Helpline at 800-272-3900."),
                                context=ai_context(st.session_state.get("sess")),
                            )
                        st.session_state[akey] = (ques, ans)
                picked = st.session_state.get(akey)
                if picked:
                    st.markdown(f"**{picked[0]}**")
                    st.info(picked[1])
                    st.caption("Answered by Claude · general information, not medical advice.")


# --------------------------------------------------------------------------- #
# Node renderers
# --------------------------------------------------------------------------- #
def render_info(node: dict) -> None:
    if node.get("id") == "landing":
        render_partner_logos()
    st.subheader(node.get("title", ""))
    st.write(node["body"])
    if node.get("note"):
        st.caption("ℹ️ " + node["note"])
    explainer(node["id"])
    if st.button("Continue", type="primary"):
        commit(None)


def render_single(node: dict) -> None:
    st.subheader(node["prompt"])
    if node.get("help"):
        st.caption(node["help"])
    explainer(node["id"])
    lm = label_map(node)
    key = f"{node['id']}_radio"
    choice = st.radio(
        "Choose one", list(lm.keys()), index=None,
        format_func=lambda v: lm[v], key=key, label_visibility="collapsed",
    )
    if st.button("Continue", type="primary"):
        if choice is None:
            st.warning("Please choose an option to continue.")
        else:
            st.session_state.pop(key, None)
            commit(choice)


def render_multi(node: dict) -> None:
    st.subheader(node["prompt"])
    if node.get("help"):
        st.caption(node["help"])
    explainer(node["id"])
    lm = label_map(node)
    key = f"{node['id']}_multi"
    picks = st.multiselect(
        "Choose all that apply", list(lm.keys()),
        format_func=lambda v: lm[v], key=key, label_visibility="collapsed",
    )
    if st.button("Continue", type="primary"):
        if not picks:
            st.warning("Please choose at least one option.")
        else:
            st.session_state.pop(key, None)
            commit(picks)


def render_collect(node: dict) -> None:
    st.subheader(node["prompt"])
    if node.get("help"):
        st.caption(node["help"])
    key = f"{node['id']}_text"
    val = st.text_input("Your answer", key=key, label_visibility="collapsed",
                        max_chars=5 if node.get("input") == "zip" else None)
    if st.button("Continue", type="primary"):
        if node.get("input") == "zip" and not (val.isdigit() and len(val) == 5):
            st.warning("Please enter a 5-digit ZIP code.")
        elif not val.strip():
            st.warning("Please enter a response to continue.")
        else:
            st.session_state.pop(key, None)
            commit(val.strip())


def render_contact(node: dict) -> None:
    s = sess()
    esc = s.get("pending_escalation")
    if esc:
        st.subheader("Let's get you connected")
        st.info(esc.get("message") or "Would it be OK if someone from our team reached out to you?")
    else:
        st.subheader(node["prompt"])
    if node.get("help"):
        st.caption(node["help"])
    explainer(node["id"])

    name = st.text_input("Name (optional)", key=f"{node['id']}_name")
    email = st.text_input("Email (optional)", key=f"{node['id']}_email")
    phone = st.text_input("Phone (optional)", key=f"{node['id']}_phone")

    c1, c2 = st.columns(2)
    send = c1.button("Share my info", type="primary")
    skip = c2.button("Skip — just show my resources")
    if send or skip:
        contact = {"vadr_name": name, "vadr_email": email, "vadr_phone": phone} if send else {}
        for k in ("name", "email", "phone"):
            st.session_state.pop(f"{node['id']}_{k}", None)
        commit(contact)


@st.cache_data(ttl=21600, show_spinner=False)
def _cached_trials(max_results: int) -> dict:
    """6-hour cache so we don't re-hit ClinicalTrials.gov on every rerun (data updates daily)."""
    return trials.search_trials(max_results=max_results)


def render_current_trials(s: dict) -> None:
    # Only for Virginia residents — surfaces studies with a Virginia site or at the NIH clinic.
    if s["answers"].get("vadr_state") == "no":
        return
    st.divider()
    with st.container(border=True):
        st.markdown("**Current Alzheimer's & dementia studies — Virginia & the NIH Clinical Center**")
        st.caption("Live from ClinicalTrials.gov, including studies at the NIH Clinical Center in "
                   "Bethesda, MD. Taking part is voluntary, eligibility is decided by each study "
                   "team, and you should talk with your doctor.")
        if st.button("Find current studies"):
            with st.spinner("Searching ClinicalTrials.gov…"):
                st.session_state["trials_result"] = _cached_trials(6)
        res = st.session_state.get("trials_result")
        if not res:
            return
        if not res["ok"]:
            st.warning("Couldn't reach ClinicalTrials.gov just now. You can search directly at "
                       "https://clinicaltrials.gov.")
            return
        if not res["studies"]:
            st.write("No current matching studies right now — the full registry is at "
                     "https://clinicaltrials.gov.")
            return
        # Optional AI summary, grounded ONLY in the real results above.
        if learn_more.is_enabled():
            summary = learn_more.summarize_trials(
                res["studies"], fallback_text="",
                context=ai_context(st.session_state.get("sess")))
            if summary:
                st.info(summary)
                st.caption("Summary by Claude · based on the live results below.")
        for t in res["studies"]:
            site = t["sites"][0] if t["sites"] else {}
            where = " · ".join(filter(None, [site.get("facility"), site.get("city"), site.get("state")]))
            badge = ('<span class="vmp-pill">NIH Clinical Center</span>' if t["is_nih"] else "")
            # Escape external ClinicalTrials.gov text before rendering as HTML (defense-in-depth).
            title = html.escape(t.get("title") or "—")
            status = html.escape(t.get("status") or "—")
            where_html = html.escape(where)
            url = html.escape(t.get("url") or "#")
            st.markdown(
                f'<div class="{"vmp-resource vmp-priority" if t["is_nih"] else "vmp-resource"}">'
                f'<strong>{title}</strong>{badge}<br>'
                f'<span style="color:#555">Status: {status}'
                f'{(" · " + where_html) if where_html else ""}</span><br>'
                f'<a href="{url}" target="_blank">View on ClinicalTrials.gov ↗</a></div>',
                unsafe_allow_html=True)
        st.caption(f"Fetched {res['fetched_at'][:16].replace('T',' ')} UTC · source: ClinicalTrials.gov")


def render_results(s: dict) -> None:
    # Log de-identified analytics exactly once.
    if not st.session_state.get("_logged"):
        db.log_session(s)
        _sync_queue(s)
        st.session_state["_logged"] = True

    high = [f for f in s["flags"] if f["tier"] == "HIGH"]
    if high:
        slas = [f["sla_hours"] for f in high if f.get("sla_hours")]
        within = f"within {min(slas)} hours" if slas else "soon"
        st.success(f"✅ Someone from the VMP team will reach out to you {within}. "
                   "Your information has been saved securely.")

    st.subheader("Resources for you")
    st.caption("Tap any resource to open it. You can share these or come back any time.")

    matched = engine.match_resources(s, CFG)
    if not matched:
        st.write("Connect with the Alzheimer's Association 24/7 Helpline at 800-272-3900 for help getting started.")
    for r in matched:
        priority = r.get("always_include") and r["source"] == "NIH"
        pill = '<span class="vmp-pill">Priority connection</span>' if priority else ""
        cls = "vmp-resource vmp-priority" if priority else "vmp-resource"
        st.markdown(
            f'<div class="{cls}"><strong>{html.escape(r["name"])}</strong>{pill}<br>'
            f'<span style="color:#555">{html.escape(r.get("blurb",""))}</span><br>'
            f'<a href="{html.escape(r.get("url","#"))}" target="_blank">Open resource ↗</a></div>',
            unsafe_allow_html=True,
        )
        if r.get("note"):
            st.caption("↗ " + r["note"])
        explainer(r["type"], scope="resource_types")

    render_current_trials(s)

    st.divider()
    if st.button("Start a new session"):
        reset()
        st.rerun()


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
def navigator_view() -> None:
    st.markdown(
        '<div class="vmp-disclaimer">This tool helps you find resources. It is '
        '<strong>not medical advice</strong> and cannot diagnose any condition. '
        'In an emergency, call 911.</div>',
        unsafe_allow_html=True,
    )
    s = sess()
    node_id = s["current"]

    if node_id == "__END__":
        render_results(s)
        return

    node = CFG["nodes"][node_id]
    ntype = node["type"]
    if ntype == "info":
        render_info(node)
    elif ntype in ("single_select", "gate"):
        render_single(node)
    elif ntype == "multi_select":
        render_multi(node)
    elif ntype == "collect":
        render_collect(node)
    elif ntype == "contact":
        render_contact(node)


def coordinator_view() -> None:
    st.subheader("Coordinator dashboard (staff)")
    st.markdown(
        '<div class="vmp-disclaimer">⚠️ <strong>MOCK PHI.</strong> In production the '
        'callback queue lives in REDCap (HIPAA-compliant), not in a local file. '
        'Analytics below are de-identified.</div>',
        unsafe_allow_html=True,
    )

    queue = db.read_queue()
    analytics = db.read_analytics()

    open_cases = [q for q in queue if q["status"] == "open"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sessions", len(analytics))
    c2.metric("Completed", sum(1 for a in analytics if a["status"] == "completed"))
    c3.metric("Open callbacks", len(open_cases))
    c4.metric("HIGH flags", sum(1 for a in analytics for f in a["flags"] if f["tier"] == "HIGH"))

    st.markdown("#### Human-review queue")
    if not queue:
        st.write("No flagged cases yet. Run a session in the Navigator (try a 'no provider' "
                 "answer, an unmet-need answer, or the 'Talk to a person' button).")
    for q in sorted(queue, key=lambda x: (x["status"] != "open", x["created_at"])):
        tier_color = {"HIGH": "🔴", "MEDIUM": "🟠", "WATCH": "🟡"}.get(q["tier"], "⚪")
        contact = " · ".join(filter(None, [q.get("name"), q.get("phone"), q.get("email")])) or "anonymous (no contact)"
        sla = f"SLA {q['sla_hours']}h" if q.get("sla_hours") else ""
        with st.container(border=True):
            st.markdown(f"{tier_color} **{q['label']}** — {sla}  \n"
                        f"Contact: {contact}  \n"
                        f"Status: `{q['status']}` · session `{q['session_id'][:8]}`")
            if q["status"] == "open":
                cc1, cc2 = st.columns(2)
                if cc1.button("Mark contacted", key=f"ct_{q['session_id']}_{q['flag_id']}"):
                    db.update_status(q["session_id"], q["flag_id"], "contacted")
                    st.rerun()
                if cc2.button("Close", key=f"cl_{q['session_id']}_{q['flag_id']}"):
                    db.update_status(q["session_id"], q["flag_id"], "closed")
                    st.rerun()

    if analytics:
        st.markdown("#### De-identified activity")
        from collections import Counter
        regions = Counter(a["region_zip3"] for a in analytics if a.get("region_zip3"))
        dropoff = Counter(a["last_node"] for a in analytics if a["status"] != "completed")
        cols = st.columns(2)
        with cols[0]:
            st.caption("Sessions by region (ZIP3)")
            st.bar_chart(dict(regions)) if regions else st.write("—")
        with cols[1]:
            st.caption("Drop-off points")
            st.bar_chart(dict(dropoff)) if dropoff else st.write("No drop-offs recorded.")

    st.markdown("#### AI assistant (diagnostics)")
    with st.container(border=True):
        if learn_more.is_enabled():
            st.markdown(f"🟢 **Live** — key detected · model `{learn_more.model_name()}`")
        else:
            st.markdown("⚪ **Off** — no API key. Add `ANTHROPIC_API_KEY` to "
                        "`.streamlit/secrets.toml` to enable the live assistant.")
        if st.button("Test the assistant"):
            grounding = ((CFG.get("explainers", {}).get("resource_types", {}) or {})
                         .get("aaa", {}).get("body", "An Area Agency on Aging helps older "
                                                     "adults find local services."))
            with st.spinner("Calling Claude…"):
                out = learn_more.answer(
                    "diagnostics_test", "What is an Area Agency on Aging?", grounding,
                    fallback_text="(fallback) The VMP team or 800-272-3900 can help.",
                    context={"audience": "caregiver", "tracks": ["clinical"], "region_zip3": "232"})
            st.write(out)
            last = (learn_more.read_usage() or [{}])[-1]
            err = f" · error `{last['error_type']}`" if last.get("error_type") else ""
            st.caption(f"outcome: `{last.get('outcome','?')}` · "
                       f"{last.get('latency_ms','?')} ms · model `{last.get('model','?')}`{err}")

        usage = learn_more.read_usage()
        if usage:
            from collections import Counter
            answered = [u for u in usage if u["outcome"] == "answered"]
            avg_ms = round(sum(u["latency_ms"] for u in answered) / len(answered)) if answered else 0
            uc1, uc2, uc3 = st.columns(3)
            uc1.metric("AI calls", len(usage))
            uc2.metric("Answered live", len(answered))
            uc3.metric("Avg latency", f"{avg_ms} ms")
            st.caption("By outcome: " + " · ".join(
                f"{k}={v}" for k, v in Counter(u["outcome"] for u in usage).items()))
            st.caption("Telemetry is de-identified — the question and answer text are never stored.")


# --------------------------------------------------------------------------- #
# Sidebar + routing
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### Virginia Memory Project")
    st.caption("Care Navigator — Phase 1 prototype")
    mode = st.radio("View", ["Navigator", "Coordinator (staff)"], label_visibility="collapsed")
    st.divider()
    s = st.session_state.get("sess")
    if mode == "Navigator" and s and s["current"] not in ("landing", "__END__"):
        if st.button("🗣️ Talk to a person"):
            engine.request_human(sess(), CFG)
            _sync_queue(sess())
            st.rerun()
        if st.button("↩︎ Start over"):
            reset()
            st.rerun()
    st.divider()
    st.caption("Synthetic data only. Not for real PHI.")
    if st.button("🧹 Clear demo data"):
        for p in (db.ANALYTICS, db.PHI_QUEUE):
            if p.exists():
                p.unlink()
        reset()
        st.rerun()

if mode == "Navigator":
    navigator_view()
else:
    coordinator_view()
