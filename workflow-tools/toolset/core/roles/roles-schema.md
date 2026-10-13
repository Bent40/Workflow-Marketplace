# Roles & modes schema — Epic F

`core/modes/*.yaml` (Plan/Act contracts) and `core/roles/*.yaml` (worker role
contracts) are rendered per-(profile × target) by `scripts/generate-adapters.py`
into `adapters/<profile>/<target>/modes/<id>.md` and `…/roles/<id>.md`. They are
**additive** to the rule output — no rule renderer is touched, so the existing
rule files stay **byte-identical** (the change is new files only).

> Note: the generated banner's "Source of truth" line is generic
> (`core/rules + core/profiles + core/targets`); modes/roles are *also* sources.
> The line is intentionally left unchanged so the 152 pre-existing rule files
> stay byte-identical — updating the banner would rewrite every adapter file.

## Mode contract — `core/modes/*.yaml`
```yaml
id: plan                       # unique; filename stem must match
summary: Inspect and propose; do not edit.
may:     [inspect, propose, ask]   # optional list of action tokens
may_not: [edit]                    # optional
must:    [validate, ...]           # optional
```
Modes are **universal** — rendered for every profile × target. The headline
safety invariant (**plan mode never grants edit**) is asserted in
`generate-adapters --selftest` against every rendered `modes/plan.md`.

## Worker role contract — `core/roles/*.yaml`
```yaml
id: reviewer                   # unique; filename stem must match
summary: Independent review of changes…
activation: default            # must be a known activation (currently only `default`)
applies_to: [claude, codex, copilot, gemini, local]   # targets this role renders into
applicable_modes: [plan]       # must be a subset of defined modes
render:                        # one note PER applies_to target (target-appropriate shape)
  claude:  "Subagent: …"
  local:   "PACKET REVIEW — …"
  …
```

Seed roles (6): `implementer`, `reviewer`, `tester`, `security_reviewer`,
`docs_writer` (all 5 targets) and `local_microtask_worker` (`local` only).

## Selection (reused from the rule plumbing)
- A role renders only when `role.activation ∈ profile.includes_activations`
  (same mechanism as rules; the former `team`/`secure` activations and the
  `secure_note` human-gate variant were removed 2026-10-13 — core/DECISIONS.md D6).
- A role renders only into targets in its `applies_to`.

## Gates (folded into the generator's existing checks — no new doctor check)
- **Drift — doctor check 11 (`--check`)** covers the new role/mode files
  automatically (they are part of `build()`'s outputs).
- **Invariants — doctor check 15 (`--selftest`)** asserts:
  1. **Plan-mode never grants edit** in any rendered surface.
  2. **Every active role renders into each of its `applies_to` targets** (no
     silent drop).

Fail-closed: bad activation/target/mode reference, a missing per-target render
note, a render note for a non-`applies_to` target, duplicate ids, or empty
modes/roles dirs ⇒ typed error (exit ≠ 0).
