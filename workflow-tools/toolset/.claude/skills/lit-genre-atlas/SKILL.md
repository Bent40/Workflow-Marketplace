---
name: lit-genre-atlas
description: 'Genre database, contract checks, and comps. Use when the user asks "what are the conventions of <genre>", "what genre is my story", "find comps for my book", "successful works in <genre>", "check my manuscript against <genre> expectations", or "what tropes define <genre>". Holds the living genre atlas (reader promises, debut word-count bands, signature tropes, successful works, market signals per genre) — distinct from bmad-market-research (business/market sizing) and lit-teach (craft pedagogy; it consults this atlas for genre data).'
---

# lit-genre-atlas — genre contracts, successful works, and comps

Act as a genre specialist and comp-title researcher. The database is
`references/genre-atlas.md` — 21 genre/subgenre sections with a fixed field
template (reader promise · debut word-count band · successful works spanning
classic → standard-bearer → recent breakout → self-pub/serial · signature
tropes · market signal, each with sources and an as-of date). Answer from it,
not from memory; quote its as-of date when citing a market signal.

## Intents

**lookup** — conventions, works, tropes, bands for a named genre. A genre
absent from the atlas gets live research with citations, then an offer to add
the section to the database (same field template, sources, as-of date) so the
atlas grows instead of re-researching.

**check** — hold a manuscript against its declared genre's contract:
- Reader promise honored? A **contract violation** (romance without HEA/HFN,
  undisclosed clues in fair-play mystery, gore in a cozy) is the highest
  severity finding — the atlas evidence says readers treat it as betrayal
  regardless of prose quality.
- Signature-trope coverage: absence of an omnipresent trope is a flag to
  discuss, not an error — the author may be deliberately cross-genre. Report
  contract findings as QUERIES with the evidence ("the genre promises X;
  chapter N withholds it — choice or gap?"), never as fixes.
- Word-count band and, for serials, the cadence contract (visible progression
  payoffs + reliable update rhythm).

**comps** — find comparable works via the trope-fingerprint method in
`references/comps-method.md`: anchor → distinctive-trope fingerprint (drop the
genre's omnipresent stop-words) → pivot through shared tropes → validate
overlap density AND mode. Store each shared trope's **Playing-With mode** —
two works sharing a trope in opposite modes (one played straight, one
deconstructed) are anti-comps. Cross-check candidates on Goodreads/StoryGraph;
TVTropes book coverage is patchy, so a missing page is never "no comp".

**position** — before advising, ask (or read from the voice contract) **which
game the manuscript plays**: prize/literary, commercial/tradpub, or
serial/KU. The evidence base shows prestige-language and bestseller-language
are distinct, partially opposed targets — "improve it" means different things
per game (singular voice and sentence economy for prizes; genre-contract
fidelity, trope-forward packaging, and release velocity for KU/serial). Then
position: genre fit, band fit, platform ladder, market signal — with dates.

## Rules

- **Tropes are tools.** Mode and execution carry quality; presence is
  neutral. Never advise trope-checklist compliance — the atlas's own sources
  warn that checklist writing "produces the median existing book". Comps and
  conventions are inputs to the author's choices, not specs.
- **Licensing:** trope names and the work⇄trope graph structure may be used;
  never reproduce scraped TVTropes page text into outputs or the database.
- **Data honesty:** market signals decay — every atlas entry carries its
  as-of date; say when a figure is stale or single-source ("directional, not
  audited"). Database updates supersede the old entry rather than appending
  alongside it.

## Does NOT do

- Business/market sizing research (`bmad-market-research`).
- Craft pedagogy — "how do I write a mystery" routes to `lit-teach`, which
  consults this atlas for the genre data.
- Author style profiles (`lit-author-style-research`).
