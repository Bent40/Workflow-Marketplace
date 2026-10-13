<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# REVIEW — clean-context review pass (profile: civilian)

Review in a fresh context, separate from whoever wrote the change.

## Steps
- Inspect the diff — read only what changed.
- Check each acceptance criterion against the change.
- Identify risks (security, correctness, scope).
- Do not broaden scope or start new work.
- Report findings honestly; separate validated from not-validated.

## Review rules
- Meaningful changes need an independent review pass, not only self-review.  <!-- rule:review.require_independent_review_for_meaningful_changes severity:high -->
- Always probe the baseline set — XSS, URL-scheme sanitization, SQLi/LIKE, traversal, validation, pagination, error leakage, response security headers; for agentic/LLM systems also probe prompt-injection, unrestricted tool use, exfiltration, and malicious tool/skill definitions.  <!-- rule:review.security_probe_baseline severity:high -->
- Reviews disagree → the stricter verdict governs.  <!-- rule:review.stricter_review_wins severity:high -->
- Give each finding a 0-100 confidence + change-only scope; filter low-confidence noise — EXCEPT security/honesty bars, which are never suppressed (allowlist, not denylist).  <!-- rule:review.confidence_scored_findings severity:medium -->
- Report each finding as Finding/Severity/Repro/Evidence/Root-cause/Fix/Regression-test/fail-before-pass-after; the affected suite must also pass before AND after (no silent regression); then sweep for sibling instances and prefer a durable detector over a one-off test.  <!-- rule:review.finding_protocol severity:medium -->
