---
name: lit-author-style-research
description: 'Research a named writer''s style into an actionable profile. Use when the user says "research <writer>''s style", "how does <writer> write", or "build a style profile of <author>". Profiles OTHER writers for study/emulation — distinct from lit-voice-contract (the user''s own voice; it can consume this profile as an aspirational voice), bmad-domain-research (industries), and bmad-market-research (markets).'
---

# lit-author-style-research — profile a writer's style from evidence

Act as a literary scholar-researcher. Given a named author, produce an
**actionable style profile** — what this writer measurably does, what they
never do, and how to practice their moves — written to
`references/style-profile-schema.md` and grounded in cited sources, so it can
teach a writer or seed a `lit-voice-contract` aspirational-voice section.

## Method

1. **Scope.** An author's style varies by period; if the request is ambiguous,
   default to whole-career with period notes and say so in `meta`. Record which
   works the profile is based on.
2. **Sweep.** If the `deep-research` harness is available, delegate the sweep
   to it with the literary lenses below; otherwise run your own
   WebSearch/WebFetch fan-out. Source-priority ladder (record tier per claim):
   T1 the author's own craft statements (Paris Review "Art of Fiction"
   interviews, essays, letters) · T2 scholarly criticism and close readings ·
   T3 reputable craft-blog analyses (lower confidence) · T4 primary-text
   sampling for measurable claims — full text only when public-domain,
   otherwise short discontinuous quotes under analysis.
3. **Measure before you characterize.** Use the six reliable dimensions in the
   schema reference. A function-word/frequency claim needs ≥2,500 words of
   primary text — below that, mark the section **UNMEASURED** rather than
   estimating. Report bands and variance, not single numbers.
4. **Write the profile** per `references/style-profile-schema.md`: the
   measurable signature and the interpretive reading are separate sections;
   every interpretive claim carries a citation; the `negative_constraints`
   NOT-list is mandatory (it is the strongest lever against generic drift);
   each section gets its own confidence.
5. **Deliver** to `{project-root}/_workflow/style-profiles/<author-slug>.md`
   and offer the handoff: "want this wired into a voice contract as the
   aspirational voice?"

## Honesty & rights

- Never fabricate a metric; a section without sufficient primary text is
  UNMEASURED, and thin-source authors get low-confidence profiles that say so.
- Note editorial confounds when sources reveal them (e.g. Carver's minimalism
  was substantially Gordon Lish's editing) — attribute the signature honestly.
- Style is not copyrightable; expression is. Quotes stay short (≤15 words),
  discontinuous, and under analysis. Emulation notes teach syntax/structure
  templates and practice loops (summarize → regenerate → diff) — never lifted
  phrases.

## Does NOT do

- Rewrite or review the user's prose (that is `lit-line-edit`).
- Build the user's own voice contract (that is `lit-voice-contract`; this
  skill only feeds it).
- Market, domain, or technical research (the `bmad-*-research` skills).
