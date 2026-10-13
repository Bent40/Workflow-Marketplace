<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# Role: local_microtask_worker  (profile: civilian, target: local)

Executes exactly one microtask packet within budget, then hands back.

Modes: act

Contract: PACKET — execute exactly one microtask within the budget; output a diff; stop and hand back.
