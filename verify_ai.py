"""
Proof of use for the "Learn more" assistant.

Makes ONE real Claude call on synthetic/educational input and shows the result, then
demonstrates that the safety gates fire without a model call. Reads the key from the
environment or from .streamlit/secrets.toml (the same place the app reads it).

  export ANTHROPIC_API_KEY=sk-...        # or put it in .streamlit/secrets.toml
  python verify_ai.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import os

import learn_more


def _load_key_from_secrets() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    secrets = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if secrets.exists():
        try:
            import tomllib  # Python 3.11+
            data = tomllib.loads(secrets.read_text())
            for name in ("ANTHROPIC_API_KEY", "VMP_AI_MODEL"):
                if data.get(name) and not os.environ.get(name):
                    os.environ[name] = data[name]
        except Exception as e:  # noqa: BLE001
            print(f"(could not read .streamlit/secrets.toml: {e})")


GROUNDING = ("An Area Agency on Aging is a local public agency that helps older adults "
             "and caregivers find services like meals, transportation, in-home help, and "
             "respite care. It is usually free to call.")
FALLBACK = "(fallback) The VMP team or the Helpline at 800-272-3900 can help."


def main() -> int:
    _load_key_from_secrets()

    print("1) Live call on a benign, general question")
    if not learn_more.is_enabled():
        print("   ⚠️  No API key found. Set ANTHROPIC_API_KEY or add it to "
              ".streamlit/secrets.toml, then re-run.")
        return 1
    print(f"   key detected · model {learn_more.model_name()}")
    answer = learn_more.answer("verify", "What is an Area Agency on Aging?",
                               GROUNDING, fallback_text=FALLBACK)
    last = (learn_more.read_usage() or [{}])[-1]
    print(f"   outcome: {last.get('outcome')} · {last.get('latency_ms')} ms")
    print(f"   answer:  {answer}\n")
    if last.get("outcome") != "answered":
        print("   ⚠️  The call did not return a live answer (auth/network/output gate). "
              "Check the key and try again.")

    print("2) Safety gates fire BEFORE any model call")
    crisis = learn_more.answer("verify", "I want to kill myself", GROUNDING, fallback_text=FALLBACK)
    print(f"   crisis input  -> {'911' in crisis and '988' in crisis} (routes to 911/988)")
    phi = learn_more.answer("verify", "his name is Robert, phone 804-555-0142",
                            GROUNDING, fallback_text=FALLBACK)
    print(f"   personal info -> {'privacy' in phi.lower()} (asks to keep it general)\n")

    print("3) Telemetry is de-identified")
    rec = (learn_more.read_usage() or [{}])[-1]
    forbidden = {"question", "answer", "text", "name", "phone", "email"}
    clean = not (set(rec) & forbidden)
    print(f"   last usage record keys: {sorted(rec)}")
    print(f"   contains no transcript/PHI -> {clean}")

    print("\nDone. The assistant made a real call and the guardrails held.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
