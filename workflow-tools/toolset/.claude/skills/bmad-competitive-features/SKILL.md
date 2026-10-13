---
name: bmad-competitive-features
description: Discover a competitive feature set, designate the MVP, and sequence the build order for an app type. Use when the user asks "what features do I need to be competitive", "what's the MVP feature set", "what are the table-stakes features", or "what build order for this app/concept" — BEFORE the brief or PRD. Distinct from bmad-market-research (market sizing/customers), bmad-product-brief / bmad-prd (which consume this set), and wds-8-product-evolution (evolving a live product).
---

# Competitive Feature Discovery, MVP Designation & Build-Order Sequencing

This skill turns an app type or concept into an **agreed, competitive,
MVP-first feature set with a build order** — the generative upfront pass that a
straight planning chain skips. Act as a pragmatic product lead who knows what a
*strong plain build* of this kind of thing obviously ships. You research the
category expectation, propose a candidate feature set (each feature tagged), cut
the MVP, sequence the build by user-visible value and dependency, and get the
user to agree before any of it feeds the brief or PRD. Use when someone needs to
know **what to build to be competitive, what the MVP is, and in what order** —
before the brief/PRD exist. Produces an agreed feature set + MVP cut + ordered
build plan handed off downstream.

## Why this exists (design rationale — do not optimize it away)

In a documented A/B contest (`docs/field-feedback-backlog.md`, 2026-06-22 todo
round), BMAD's full planning chain produced a product the judge scored **less
competitive than a bare agent's build** — it optimized requirement-traceability
over visible product value and **missed obvious table-stakes** a strong plain
build shipped: search, dark-mode, toggle-all. The root cause (gaps P2/P7): the
spec was never checked against "what would a strong plain build obviously
include?" *before* planning. `dod.product_competitiveness_gate` added that check
at the **end** (baseline-parity + visible-polish before done). This skill is the
missing **generative front end** to that gate: it surfaces the competitive
baseline *upfront* so the spec is competitive by construction, not patched at the
finish line. The table-stakes lens is the whole point — never skip it to save a
step.

## Does NOT do (boundaries — stay inside them)

This skill is feature discovery + MVP + sequencing, and nothing adjacent:

- **NOT market sizing, TAM, segmentation, or competitor/customer research** →
  that is `bmad-market-research` (and `bmad-domain-research` for industry/domain
  depth). This skill consumes their output as an *input* if it exists; it does
  not produce it. It reasons from category knowledge about *what features a
  category ships*, not *how big the market is or who the buyer is*.
- **NOT the product brief or the PRD** → those are `bmad-product-brief` and
  `bmad-prd`, which **consume** the agreed feature set this produces. This skill
  hands off; it does not write the brief, the requirements, or the epics.
- **NOT evolving / improving a live product** → that is
  `wds-8-product-evolution` (brownfield). This is a greenfield "what should this
  app type ship to be competitive" pass, not "what should we add to the running
  product next."
- **NOT the end-of-build competitiveness CHECK** → that is
  `dod.product_competitiveness_gate`, the *verification* lens before done. This
  is the *generative* upfront counterpart; they are two ends of the same
  concern, not the same step.

If the request is really one of those, route there instead of doing it here.

## Right-size the pass (do this first)

Per `gating.right_size_process_to_project`, **classify the app size before
enumerating**, and cap the output:

- **Tiny** (a todo list, a single-screen utility) → a short table-stakes pass:
  the obvious baseline list, a one-line MVP-vs-later cut, a quick build order.
  Do **not** produce a 30-feature treatise — that is the disproportionate
  ceremony the A/B loss warned against.
- **Small** → the baseline list plus a handful of differentiators, MVP cut,
  ordered plan.
- **Medium / Large** → the full pass: category expectation, table-stakes vs
  differentiators, MVP designation, dependency-aware sequencing, and explicit
  hand-off.

Right-sizing is a feature, not a shortcut: match the artifact volume to the
project.

## The method — six steps

### 1. Take the concept and constraints
Capture the **app type / concept** and any constraints that bound the feature
set: target **platform** (web / mobile / CLI / desktop), **audience** (consumer
/ team / enterprise), and **scope / size** (tiny → large). If the app type is
ambiguous ("an app for my business"), ask one clarifying question — you cannot
establish a category expectation for an unknown category. Note constraints that
*exclude* features (e.g. "offline-only" rules out cloud sync from MVP).

### 2. Establish the CATEGORY EXPECTATION (the table-stakes baseline)
State what **a strong plain build of this app type obviously ships** — this is
the baseline-parity list, the lens the A/B loss was missing. Enumerate from
category knowledge: for a **todo app**, that baseline obviously includes
add / edit / complete / delete / filter / **search** / clear-completed /
**toggle-all** / **persistence** / keyboard support / mobile / accessibility.
Separate:
- **Table-stakes** — features whose *absence* makes the product feel broken or
  incomplete versus any competent competitor. Omitting one is how BMAD lost.
- **Differentiators** — features that make this build *better* than the plain
  baseline, not merely on-par.

If a research skill or web access is available and the category is unfamiliar,
**recommend `bmad-market-research` / `bmad-domain-research` as inputs** to
ground the baseline — do not duplicate their work, and do not invent competitor
data. If neither is available, reason from category knowledge and mark the
baseline as *from category knowledge, unverified*.

### 3. Propose the candidate FEATURE SET (every feature tagged)
List the candidate features. **Tag each one on two axes plus a rationale:**

| Feature | table-stakes / differentiator | MVP / later | One-line user-visible value |
|---|---|---|---|

The rationale column is **user-visible value**, never implementation ease — a
feature earns MVP because it delivers visible value or unlocks a table-stakes
flow, not because it is cheap to code. Include the obvious table-stakes
explicitly even when they feel "too basic to mention" — that omission is exactly
the failure mode this skill exists to prevent.

### 4. SEQUENCE the build order (value + dependency)
Produce an **ordered, MVP-first build plan**. Order by:
- **User-visible value** — the soonest-visible, most-load-bearing flows first.
- **Dependency** — what unlocks what (persistence usually precedes search and
  filter; a data model precedes the views over it). Name the dependency when it
  drives the order.

The MVP slice comes first as a coherent, shippable whole; differentiators and
later table-stakes follow in value/dependency order. Make the cut line between
"MVP" and "later" explicit and **justified by user-visible value**, not by what
was easy to build.

### 5. PRESENT for user agreement (never silently finalize)
Present the tagged set, the MVP cut, and the build order **to the user for
confirmation** — AskUserQuestion-style. Ask explicitly:
- Is the **table-stakes baseline** complete, or is an obvious feature missing?
- Is the **MVP cut** right — anything to promote into or drop from MVP?
- Is the **build order** sensible given their constraints?

The user **confirms or edits** the set and the MVP cut before it feeds planning.
Do **not** silently decide the feature set or the MVP — the agreement is the
deliverable's contract with what comes next. Record what they changed.

### 6. HAND OFF the agreed set
Once agreed, hand the feature set + MVP designation + build order to the
downstream planning skills — **name the hand-off, do not do their job**:
- → **`bmad-product-brief`** — to frame the brief around the agreed MVP.
- → **`bmad-prd`** — to write requirements for the agreed feature set.
- → **`bmad-create-epics-and-stories`** — to break the build order into epics
  and stories in sequence.

State the hand-off explicitly so the agreed set carries forward intact.

## Output shape

Produce, right-sized to the app:

1. **Concept & constraints** — app type, platform, audience, scope.
2. **Category expectation** — the table-stakes baseline list (and any
   differentiators), with its source (category knowledge / market-research
   input) noted.
3. **Tagged feature set** — the table from step 3 (table-stakes vs
   differentiator, MVP vs later, user-visible-value rationale).
4. **MVP-first build order** — the ordered plan with the MVP cut line explicit
   and the value/dependency reasons named.
5. **User-agreement prompt** — the confirm/edit questions from step 5.
6. **Hand-off** — which downstream skill(s) consume the agreed set.

For a tiny app, steps 2–4 collapse into a short list; keep step 5 (agreement)
and step 6 (hand-off) always.

## Quick checklist before handing off

- [ ] App size classified; the pass is right-sized (no treatise on a toy).
- [ ] Category expectation stated — the **table-stakes baseline is explicit**
      and not missing an obvious feature (search/persist/etc. for a todo app).
- [ ] Every feature tagged **table-stakes-vs-differentiator AND MVP-vs-later**.
- [ ] MVP cut **justified by user-visible value**, not implementation ease.
- [ ] Build order is MVP-first and respects dependency (what unlocks what).
- [ ] Presented for **user agreement** — not silently finalized.
- [ ] Hand-off to `bmad-product-brief` / `bmad-prd` /
      `bmad-create-epics-and-stories` named; their job not done here.
