---
name: bmad-security-decision-framing
description: Facilitated framing of an UPFRONT security-architecture decision that is still OPEN — trust boundaries, agent splits, sandbox tier, capability grants — for systems that handle untrusted content (agentic/LLM systems especially). Elicits the system map and assets, applies the Lethal Trifecta and Meta's Rule of Two lenses plus least-privilege/blast-radius, builds an option table with per-option residual risk, drives the human to a decision, and emits decision-log-ready entries. Use BEFORE design, while the decision is unmade — distinct from an injection-boundary review (which reviews an already-DESIGNED flow), bmad-decision-propagation (spreads an already-SETTLED decision across prose docs), and bmad-correct-course (general mid-sprint change navigation).
---

# BMAD Security Decision Framing

When a system will process untrusted content (email, web, documents, other
agents' output) and also touch private data or real-world actions, the costly
security decisions — where the trust boundaries sit, how agents are split, what
sandbox tier applies, which capabilities each component gets — must be framed
**before** anything is designed. This skill runs that framing as a facilitated,
gated conversation: map the system, apply the standard lenses, lay out options
with honest residual risk, get the human to choose, and record the choice in a
shape the decision log (and bmad-decision-propagation) can consume directly.

It frames and decides. It does not design the resulting flow, review code, or
edit documents.

## When to use this vs. neighboring skills

Use **bmad-security-decision-framing** when the security decision is **still
open**: "should the agent be allowed both X and Y?", "which sandbox tier?",
"how do we split capabilities so injection can't exfiltrate?" — and the human
needs structured options, not a verdict on an existing design.

Use an **injection-boundary review** instead when a flow is **already
designed** (or built) and needs a pass/fail review against the same lenses.
They compose: frame the decision here, design the flow, then run that review
to verify the design honors the decision.

Use **bmad-decision-propagation** instead when the decision is **already
settled** and existing prose planning docs must be brought into agreement.
This skill's Round-4 entries are written precisely as its input.

Use **bmad-correct-course** instead for a general unresolved mid-sprint change
(scope, schedule, requirements) with no security-architecture core.

## Inputs

- **The candidate decision(s)**: what is open, in the human's words. One run
  may frame several related decisions.
- **System knowledge**: any briefs, architecture notes, PRDs, or a verbal
  description of components, data flows, and tools. Accept docs as substitutes
  for questions — read first, ask only what's still missing.
- **Assets & sensitive systems**: what an attacker would want (data stores,
  credentials, money-moving or state-changing APIs, the user's reputation).
- **Constraints**: latency/cost/UX limits, model-instance budgets, compliance
  requirements — these shape which options are viable.

Hard rules, in force throughout:
- **Never invent system facts.** A missing fact becomes a Round-1 question (or
  a headless ASSUMPTION-NEEDED flag) — never an assertion.
- **Every lens mark cites its earner.** A trifecta leg or Rule-of-Two property
  is only marked when a named component/flow/tool earns it.
- **"No good option" is a legitimate outcome.** If every option leaves an
  unacceptable residual risk under the constraints, say so and escalate; do
  not force a recommendation.
- **Project-agnostic.** This skill is tied to no single project or platform — it frames the decision for any system that handles untrusted content.

## Procedure — four rounds, two gates

### Round 1 — System & decision elicitation
Establish, from supplied docs first and targeted questions second:
- **Components/agents** and the **data flows** between them.
- **Trust level per input source**: TRUSTED (direct human request) or
  UNTRUSTED (web, email, documents, files of unknown origin, other-agent
  output, memory derived from any of these).
- **Assets and sensitive systems** reachable from each component.
- **The decision(s) to frame**, restated as a question with its candidate
  answers if any were floated.
Ask only for what is missing; do not re-elicit what a brief already states.

### Round 2 — Lens application → GATE 1
For each component/flow, mark:
- **Lethal Trifecta legs** — (1) access to private/sensitive data,
  (2) exposure to untrusted content, (3) ability to externally communicate or
  act. All three in one flow = trifecta hit.
- **Rule of Two properties** — [A] processes untrustworthy inputs,
  [B] accesses sensitive systems/private data, [C] changes state or
  communicates externally. **No more than two without a human in the loop**;
  3/3 means a human gate is mandatory for that flow.
- **Least-privilege / blast-radius note** — what this component could do if
  fully compromised; which capabilities exceed its actual need.
Each mark names the component, tool, or input that earns it.
**GATE 1:** present the boundary/lens map (Output §1); the human confirms or
corrects it. Do not proceed on a map the human hasn't validated — options
built on a wrong map are worse than no options.

### Round 3 — Option table → GATE 2
Enumerate the candidate architectures that answer the decision. Draw on the
standard moves where they apply: planner/quarantined-executor split (untrusted
content read by a capability-stripped instance), capability stripping
(remove a leg entirely), human-approval gating on consequential actions,
sandbox tiers, taint/provenance tracking, deny-by-default capability scoping.
For **each** option record: which legs/properties remain per flow, the
mitigations it adds, the **residual risk** (what an attacker can still do),
and cost/complexity against the stated constraints. End with **one**
recommendation and its rationale — unless no option clears the bar, in which
case state that and what would have to change (a constraint, an asset, a
capability) to create a viable option.
**GATE 2:** the human picks. The pick may diverge from the recommendation —
record the divergence and the human's stated reason verbatim.

### Round 4 — Decision record
Emit one entry per settled decision, in exactly the shape
bmad-decision-propagation consumes (ID / Invariant / Supersedes / Surface
terms), plus rationale, rejected options, and follow-ons (Output §3–§4).
Follow-ons must name: **an injection-boundary review** to verify the flow
once it is designed, and **bmad-decision-propagation** if prose planning docs
already exist that the decision contradicts.

## Output template

Produce exactly this structure.

**1. Boundary / lens map** (Round 2; presented at GATE 1)

| # | Component / flow | Trifecta legs (1 data · 2 untrusted · 3 act) | Rule of Two ([A][B][C]) | Earned by | Least-privilege / blast-radius |
|---|------------------|----------------------------------------------|--------------------------|-----------|--------------------------------|
| F1 | Concierge agent — process incoming mail | 1+2+3 → **TRIFECTA HIT** | [A][B][C] = 3/3 → **human gate REQUIRED** | 1: mail-read (full mailbox); 2: email bodies, web-fetch pages; 3: mail-send, pay-invoice | One context holds every capability; compromise = full mailbox exfil + payments |

**2. Option table** (Round 3; presented at GATE 2)

| Opt | Architecture | Legs/props remaining | Mitigations | Residual risk | Cost / complexity |
|-----|--------------|----------------------|-------------|---------------|-------------------|
| O1 | Planner + quarantined reader split | Reader: 2 only; Planner: 1+3, [B][C] | Reader has no send/pay/data tools; planner never sees raw untrusted text | Injection can still bias the reader's summaries (lying, not acting) | 2 instances; summary-schema work |

```
RECOMMENDATION: O<n> — <one-paragraph rationale tied to the lens map>.
(or) NO VIABLE OPTION: <which constraint/asset blocks every option; what must change>. Escalating.
```

**3. Decision entries** (Round 4 — one block per settled decision)

```
### SD-1 — <short title>
- Status: SETTLED by human at GATE 2 | DRAFT (headless — human has not chosen)
- Invariant (now true): <single statement that must hold, e.g. "The component
  that reads untrusted mail holds no send, pay, or private-data capability.">
- Supersedes (old assumption, if any): <e.g. "single agent with all tools">
- Surface terms: <concrete strings docs will contain: tool names, agent names,
  capability labels, tier labels>
- Rationale: <why this option; if the human diverged from the recommendation,
  the human's stated reason verbatim>
- Rejected options: O<n> (<one-line why>), ...
```

**4. Follow-on flags**

```
1. injection-boundary review — run on the designed flow before build,
   to verify the design upholds SD-1's invariant.
2. bmad-decision-propagation — <list the existing prose docs that now
   contradict SD-1>, or "no prose docs exist yet — not needed".
3. <anything the framing revealed but did not resolve>
```

## Working mode

- Default is **facilitated**: run the rounds in order, stop at GATE 1 and
  GATE 2, and wait. Keep each round's output tight enough to confirm at a
  glance; the gates exist so the human corrects cheaply, early.
- **Headless mode** — when the prompt starts with `Run headless.` and supplies
  full context: run all four rounds without pausing; mark every decision entry
  **DRAFT (headless — human has not chosen)**; pick the recommendation as the
  draft basis but list all options; and append a **Gate questions** section
  listing, per gate, the exact questions/confirmations that would have been
  put to the human. Missing facts become explicit ASSUMPTION-NEEDED flags —
  still never invented.

## Degraded mode — insufficient system information

If the system map cannot be established (no docs, vague description, key flows
unknown):

1. Print: `NOTE: system facts incomplete; running in PLANNED mode. Lens marks
   on <items> are UNVERIFIED.`
2. Build the boundary map from what IS known, marking each unverified cell
   `UNVERIFIED:<missing fact>` rather than guessing.
3. Produce the option table only for options whose viability doesn't hinge on
   an unverified mark; list the rest as "blocked pending <fact>".
4. Emit no SETTLED entries — DRAFT at most — and make the first follow-on flag
   the fact-gathering needed to leave PLANNED mode.
