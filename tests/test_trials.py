"""
Tests for the live clinical-trials feature.

Parsing is tested against sample API responses (no network). The live fetch is tested only
for graceful failure (the build sandbox can't reach ClinicalTrials.gov; your deployment can).
The AI summary is tested for grounding and no-PHI behavior without a live model.

Run:  python tests/test_trials.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import learn_more  # noqa: E402
import trials  # noqa: E402

# Real-shaped ClinicalTrials.gov API v2 records (trimmed).
SAMPLE_VA = {  # Virginia site (+ an unrelated Maryland site that should be dropped)
    "protocolSection": {
        "identificationModule": {"nctId": "NCT05555555", "briefTitle": "A Memory Study in Richmond"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "conditionsModule": {"conditions": ["Alzheimer Disease"]},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "VCU"}},
        "contactsLocationsModule": {"locations": [
            {"facility": "VCU Health", "city": "Richmond", "state": "Virginia", "status": "RECRUITING"},
            {"facility": "Somewhere Else", "city": "Baltimore", "state": "Maryland", "status": "RECRUITING"},
        ]},
    }
}
SAMPLE_NIH = {  # NIH Clinical Center in Bethesda, MD
    "protocolSection": {
        "identificationModule": {"nctId": "NCT07777777", "briefTitle": "An NIH Aging Study"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "contactsLocationsModule": {"locations": [
            {"facility": "National Institutes of Health Clinical Center",
             "city": "Bethesda", "state": "Maryland", "status": "RECRUITING"},
        ]},
    }
}
SAMPLE_OUT_OF_STATE = {  # Texas only -> not relevant
    "protocolSection": {
        "identificationModule": {"nctId": "NCT06666666", "briefTitle": "A Study in Texas"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "contactsLocationsModule": {"locations": [
            {"facility": "Houston Center", "city": "Houston", "state": "Texas", "status": "RECRUITING"},
        ]},
    }
}


def test_parse_extracts_core_fields():
    rec = trials._parse_study(SAMPLE_VA)
    assert rec["nct_id"] == "NCT05555555"
    assert rec["title"] == "A Memory Study in Richmond"
    assert rec["status"] == "RECRUITING"
    assert rec["url"] == "https://clinicaltrials.gov/study/NCT05555555"


def test_va_study_keeps_only_relevant_sites_and_is_not_nih():
    rec = trials._parse_study(SAMPLE_VA)
    assert {s["state"] for s in rec["sites"]} == {"Virginia"}  # Maryland (non-NIH) dropped
    assert rec["is_nih"] is False


def test_nih_bethesda_study_is_flagged():
    rec = trials._parse_study(SAMPLE_NIH)
    assert rec["is_nih"] is True
    assert rec["sites"][0]["city"] == "Bethesda"


def test_drops_studies_with_no_va_or_nih_site():
    assert trials._parse_study(SAMPLE_OUT_OF_STATE) is None


def test_nih_sorts_first():
    # Mimic the sort used in search_trials.
    recs = [trials._parse_study(SAMPLE_VA), trials._parse_study(SAMPLE_NIH)]
    recs.sort(key=lambda r: (not r["is_nih"], r["title"] or ""))
    assert recs[0]["is_nih"] is True, "NIH study must be surfaced first"


def test_search_fails_gracefully_without_network():
    res = trials.search_trials(max_results=3)
    assert isinstance(res, dict) and "ok" in res and "studies" in res
    if not res["ok"]:
        assert res["studies"] == []


def test_summary_disabled_returns_fallback():
    parsed = [trials._parse_study(SAMPLE_NIH)]
    assert not learn_more.is_enabled()
    out = learn_more.summarize_trials(parsed, fallback_text="SEE_LIST", context={"audience": "self"})
    assert out == "SEE_LIST"


def test_summary_grounding_excludes_phi_context():
    safe = learn_more._safe_context({"audience": "caregiver", "region_zip3": "232",
                                     "name": "Robert", "vadr_cg1": "yes", "zip": "23220"})
    assert safe == {"audience": "caregiver", "region_zip3": "232"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
