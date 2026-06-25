---
description: Run both test suites and report results
---
Run the project's test suites and summarize pass/fail:

1. `python tests/test_engine.py` — deterministic routing, flags, and resource-matching regression.
2. `python tests/test_learn_more_guardrails.py` — AI safety (no-PHI signature, context allowlist, crisis/PHI gates, domain lock, telemetry has no transcript).

If anything fails, show the failing assertion and propose a fix that preserves the hard rules in CLAUDE.md (deterministic routing, no PHI to the LLM, no free-text entry, config-driven clinical logic).
