"""
VMP Navigator — live clinical-trial lookup (ClinicalTrials.gov API v2).

Why this exists: an LLM's training data is stale and it will hallucinate trials (fake NCT
numbers, wrong eligibility, nonexistent sites). The ONLY safe way to give people current,
local trial info is to query the authoritative registry live. This module does the
retrieval; the LLM (in learn_more.summarize_trials) may only summarize these REAL results.

Scope: studies with a site in VIRGINIA or at the NIH Clinical Center in BETHESDA, MD
(the NIH Memory & Aging Clinic). NIH/Bethesda studies are flagged is_nih and always sorted
first, so the NIH option is highlighted.

Public API, no key, ~50 req/min. Docs: https://clinicaltrials.gov/data-api/api
Pure module (no Streamlit). Run `python trials.py` to do a live search (needs internet).
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

API = "https://clinicaltrials.gov/api/v2/studies"
OPEN_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ENROLLING_BY_INVITATION,AVAILABLE"
DEFAULT_CONDITION = "dementia OR Alzheimer OR mild cognitive impairment"
# We surface studies with a site in either of these. Bethesda, MD = NIH Clinical Center.
LOCATIONS = ["Virginia", "Bethesda, Maryland"]
TIMEOUT = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_va_site(loc: dict) -> bool:
    return loc.get("state") == "Virginia"


def _is_nih_site(loc: dict) -> bool:
    """NIH Clinical Center / Bethesda, MD. We always highlight the NIH option."""
    fac = (loc.get("facility") or "").lower()
    if loc.get("city") == "Bethesda" and loc.get("state") == "Maryland":
        return True
    return any(k in fac for k in (
        "national institutes of health", "nih clinical center", "national institute on aging"))


def _is_relevant(loc: dict) -> bool:
    return _is_va_site(loc) or _is_nih_site(loc)


def _query(location_term: str, condition: str, open_only: bool) -> dict:
    params = {
        "query.cond": condition,
        "query.locn": location_term,
        "pageSize": 50,
        "sort": "LastUpdatePostDate:desc",
        "countTotal": "true",
        "format": "json",
    }
    if open_only:
        params["filter.overallStatus"] = OPEN_STATUSES
    r = requests.get(API, params=params, timeout=TIMEOUT, headers={"accept": "application/json"})
    r.raise_for_status()
    return r.json()


def search_trials(*, condition: str = DEFAULT_CONDITION, max_results: int = 6,
                  open_only: bool = True) -> dict:
    """Current dementia/Alzheimer's studies in Virginia or at the NIH Clinical Center.

    Queries each location, merges/dedupes by NCT, keeps only VA/NIH sites, and sorts NIH
    studies first. Never raises — on total failure returns ok=False for a graceful fallback.
    """
    raw: dict[str, dict] = {}
    errors: list[str] = []
    for term in LOCATIONS:
        try:
            data = _query(term, condition, open_only)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            continue
        for s in data.get("studies", []):
            nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            if nct and nct not in raw:
                raw[nct] = s

    if not raw:
        if errors:
            return {"ok": False, "error": errors[0], "fetched_at": _now(), "studies": []}
        return {"ok": True, "fetched_at": _now(), "studies": []}

    parsed = [rec for rec in (_parse_study(s) for s in raw.values()) if rec]
    # NIH (Bethesda) studies first — always highlight the NIH option — then by title.
    parsed.sort(key=lambda r: (not r["is_nih"], r["title"] or ""))
    return {"ok": True, "fetched_at": _now(), "studies": parsed[:max_results]}


def _parse_study(s: dict) -> dict | None:
    """Pull the few fields we show. Keep only VA / NIH-Bethesda sites; flag NIH studies."""
    ps = s.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    nct = ident.get("nctId")
    if not nct:
        return None
    locs = ps.get("contactsLocationsModule", {}).get("locations", []) or []
    relevant = [l for l in locs if _is_relevant(l)]
    if not relevant:
        return None  # no Virginia or NIH site -> skip
    sites = [{
        "facility": l.get("facility"),
        "city": l.get("city"),
        "state": l.get("state"),
        "status": l.get("status"),
        "is_nih": _is_nih_site(l),
    } for l in relevant[:4]]
    sites.sort(key=lambda x: not x["is_nih"])  # show the NIH site first within a study
    return {
        "nct_id": nct,
        "title": ident.get("briefTitle"),
        "status": ps.get("statusModule", {}).get("overallStatus"),
        "conditions": ps.get("conditionsModule", {}).get("conditions", []) or [],
        "phases": ps.get("designModule", {}).get("phases", []) or [],
        "sponsor": ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name"),
        "summary": (ps.get("descriptionModule", {}).get("briefSummary") or "")[:600],
        "is_nih": any(site["is_nih"] for site in sites),
        "sites": sites,
        "url": f"https://clinicaltrials.gov/study/{nct}",
    }


if __name__ == "__main__":
    res = search_trials(max_results=8)
    if not res["ok"]:
        print("fetch failed:", res["error"])
    else:
        print(f"showing {len(res['studies'])} studies (NIH first):")
        for t in res["studies"]:
            site = t["sites"][0] if t["sites"] else {}
            tag = " [NIH Clinical Center]" if t["is_nih"] else ""
            print(f"\n- {t['title']}{tag}\n  {t['status']} · "
                  f"{site.get('facility','?')} ({site.get('city','?')}, {site.get('state','?')}) · {t['url']}")
