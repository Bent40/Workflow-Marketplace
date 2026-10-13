---
name: bmad-decision-propagation
description: Given one or more finalized, human-approved decisions (e.g. a new entry in a canonical decision log), propagates them consistently across already-written PROSE planning artifacts (PRD, architecture, UX spec, test-design, epics/stories, briefs), producing surgical per-document edit plans, a cross-document consistency sweep, and a follow-on-flags list. Use when a decision is settled AFTER planning docs already exist and those docs must be brought into agreement — distinct from bmad-correct-course (which navigates an unresolved change) and from code/contract-diff propagation (which propagates a code or contract change across repos, not prose).
---

# BMAD Decision Propagation

When a planning effort already has a body of written artifacts (PRD, architecture,
UX spec, test-design, epics/stories, briefs) and a **new decision is finalized
after the fact** — typically recorded in a canonical decision log — every artifact
that touched the old assumption must be brought into agreement. Doing this by hand
is error-prone: stale allowances get left behind, traceability/gate rows dangle,
and "resolved" human-review items keep saying "to be decided".

This skill turns one or more **settled decisions** into: per-document surgical edit
plans, a cross-document consistency sweep, and a flags list for the human. It is
**offline and self-contained**, and it edits prose only — it does not touch code.

## When to use this vs. neighboring skills

Use **bmad-decision-propagation** when:
- A decision is **already made and human-approved** (it lives in a decision log,
  or the human just confirmed it) and now the *existing* prose docs disagree with
  it or pre-date it.
- The job is **mechanical fan-out + reconciliation**: apply the known decision
  everywhere, then prove the docs are mutually consistent.

Use **bmad-correct-course** instead when the change is **not yet resolved** — you
need to analyze a triggering issue, weigh options, and produce a *Sprint Change
Proposal* deciding *what* to do. (Correct-course decides; this skill propagates a
decision already made. They compose: run correct-course to settle the change, then
this skill to spread it.)

Use a **code/contract-diff propagation** pass instead when the changeset is a **code /
schema diff** to a shared contracts library — classifying breaking vs
non-breaking symbol changes across repos. This skill is for **prose planning
documents**, not source.

## Inputs

- **Decision(s)**: one or more finalized decisions. Accept any of: an ID + summary
  (e.g. "S3 — Tier-C microVM sandbox is the v1 baseline"), a decision-log section,
  or a described decision the human just approved. Each decision carries an
  **invariant** (what is now true) and, ideally, what it **replaces/rejects** (the
  old assumption it supersedes).
- **Canonical source**: the decision log or doc that is the single source of truth.
  Edits flow FROM it TO the artifacts; never the reverse. If an artifact seems to
  contradict the canonical source on substance, that is a flag for the human, not a
  silent edit.
- **Target artifacts**: the prose docs to reconcile. By default discover the usual
  BMAD planning set under the planning/output folder: product brief, PRD,
  market/domain research, UX spec, architecture, test-design, epics-and-stories,
  human-dependency / readiness reports, and any review/changelog records. Accept a
  caller-provided list or glob to narrow scope.
- **Scope guard**: only the named decision(s) may drive edits. Nothing outside the
  decision set is changed — record this constraint and honor it.

## Procedure

### 1. Normalize each decision into an invariant + supersession pair
For every decision, write down explicitly:
- **Invariant** — the single statement that must now hold ("P and Q run as two
  separate served instances in distinct processes").
- **Supersedes** — the old wording/assumption it replaces, if any ("single-model
  P/Q collapse"; "Tier A/B reserved-microVM allowance").
- **Surface terms** — the concrete strings likely to appear in docs (model names,
  tier labels, FR/NFR numbers, numeric bounds, capability names). These drive the
  search in step 2.

### 2. Locate every touchpoint
For each decision's surface terms, search all target artifacts (use the project's
content-search tool / ripgrep / Grep). For each hit, classify it as:
- **STALE** — asserts or allows the superseded assumption → must be edited.
- **ALREADY-ALIGNED** — already states the invariant (or correctly states the
  *rejecting* language) → leave intact, but record it so the sweep can confirm.
- **DANGLING** — a traceability row, gate, acceptance criterion, risk entry, or
  "human to decide" item that referenced the old state and will be left inconsistent
  unless updated.

Record: artifact, section/anchor, the exact current text, and the classification.

### 3. Draft surgical edits (old → new), per document
For each STALE or DANGLING touchpoint, propose a minimal edit in old → new form
with a one-line rationale tied to the decision ID. Editing rules:
- **Surgical only.** Change the smallest span that makes the doc state the
  invariant. Do not rewrite surrounding prose, restructure, or "improve" unrelated
  text.
- **Preserve rejecting language.** If a doc deliberately says "we reject X / X is
  replaced by Y", that is correct under the decision — keep it; do not mistake it
  for a stale allowance.
- **Resolve human-review items.** Flip any "to be decided / confirm whether…" item
  the decision settles to **RESOLVED by <decision-id>**, stating the resolution.
- **Keep traceability whole.** When you change a gate/row/criterion, update every
  row that references it so nothing dangles (e.g. if a guard is demoted to
  defense-in-depth, keep it referenced, don't delete the row).
- **Never invent substance.** If applying the decision requires a fact the decision
  doesn't supply, stop and raise it as a flag — do not guess.

### 4. Cross-document consistency sweep
After the edits are drafted, verify the docs agree:
- Re-search each surface term across ALL artifacts; confirm no remaining occurrence
  asserts the superseded assumption (every survivor is either the invariant or
  explicit rejecting language).
- Check cross-references line up: an FR/NFR number, gate, or capability named in one
  doc must match its definition in the canonical/owning doc.
- Confirm no traceability/gate/acceptance row was left pointing at deleted or
  changed text.
- Note any artifact that needed **zero** edits because it was already aligned (this
  is a positive consistency signal, not a miss).

### 5. Surface follow-on flags
Capture anything the propagation **reveals** but does not itself resolve:
- **Second-order impacts** the decision creates (e.g. a mandate that makes a budget
  tighter, a build heavier, a timeline longer) — non-blocking, but the human should
  see them. Name the skill that should size them if one exists.
- **Genuine contradictions** where an artifact disagrees with the canonical source
  on substance (not just stale wording) — never silently overwrite; flag for human.
- **Out-of-scope adjacencies** you noticed but did not touch (honoring the scope
  guard), so the human can decide whether a follow-up pass is warranted.

## Output template

Produce exactly this structure.

**1. Decision normalization**

| ID | Invariant (now true) | Supersedes (old assumption) | Surface terms |
|----|----------------------|-----------------------------|---------------|
| S3 | Tier-C microVM is the v1 sandbox baseline | Tier A/B reserved-microVM allowance | "Tier A/B", "reserved microVM", FR-18..20, GATE C |

**2. Per-document edit plan** (one block per artifact that needs changes, in a
stable order — canonical source first, then the rest):

```
### architecture/platform-architecture.md
- [S3] §12 traceability (FR-18/19/20):
  OLD: "broker + sandbox tiers"
  NEW: "broker + Tier-C microVM sandbox baseline (S3)"
  Why: align traceability row to the settled v1 baseline.
```

List only artifacts with at least one edit. Each edit is concrete (section anchor +
exact old → new + rationale). Group edits by decision ID where several apply.

**3. Consistency sweep result**

```
- Searched: "Tier A/B", "reserved microVM", FR-18..20 across all 11 artifacts.
- Remaining occurrences: all are rejecting/replacing language (S2/S3) — OK.
- Cross-refs: GATE C still references S-SBX + S-NOCODE (no dangling rows).
- Zero-edit-but-aligned: architecture (already S1–S4 aligned bar one row).
- Verdict: artifacts mutually consistent on <decisions>.
```

**4. Follow-on flags for the human**

```
1. <Second-order impact> — <non-blocking>; size with <skill if any>.
2. <Genuine contradiction needing a human call> — NOT auto-edited.
3. <Out-of-scope adjacency noticed, untouched>.
```

If there are no flags, say so explicitly.

## Working mode

- Default to a **batch** edit plan (all proposals at once) for review; offer an
  **incremental** mode (approve/edit/skip each) when the caller prefers it or the
  blast radius is large.
- If asked to **apply** the edits, apply only the approved old → new spans exactly;
  then re-run the step-4 sweep against the now-edited files and report the result.
  Leaving the edits as a reviewed plan is also a valid stopping point — propagation
  proposals are themselves a useful artifact.

## Degraded mode — canonical source or artifacts missing

If the decision log / canonical source or some target artifacts can't be found:

1. Print: `NOTE: <source/artifact(s)> not found; running in PLANNED mode. Invariants
   are taken from the described decision; touchpoints are UNVERIFIED.`
2. Still normalize the decision(s) into invariants and list the artifacts that
   *would* be affected from the standard BMAD planning set.
3. Produce the same output template with edit *targets* described rather than exact
   old → new spans, and flag every item for re-verification once the docs are
   available.
