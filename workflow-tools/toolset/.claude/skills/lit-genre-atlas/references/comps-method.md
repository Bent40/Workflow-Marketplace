# Comps via trope fingerprints — method and mode taxonomy

Derived from the TVTropes ecosystem research (docs/research/literary-pack/
R7-tvtropes.md). TVTropes is a hand-maintained bipartite work⇄trope graph
with no multi-trope reverse search — this manual join is the method its human
"Media Finder" forum performs.

## The 4-step method

1. **Anchor.** Find the work page of the nearest known comparable
   (`site:tvtropes.org <title>`); harvest its main trope list. Read YMMV
   items separately — they are subjective reception, not textual fact.
2. **Fingerprint.** Pick 5–10 *distinctive* tropes that define the
   manuscript's specific appeal. Drop genre stop-words — the omnipresent
   tropes every work in the genre carries (the genre's "Necessary Tropes" /
   Necessary Weasels); they match everything and identify nothing. Verify
   each trope's meaning via its Laconic one-liner before using it.
3. **Pivot.** On each fingerprint trope's page, read the Literature (and Web
   Original, for serials) example folders; rank candidate works by how many
   fingerprint tropes they appear under.
4. **Validate.** Open each candidate's work page: check overlap density AND
   **how** each shared trope is played (mode, below). Cross-check candidates
   on Goodreads shelves/Listopia and StoryGraph tags — TVTropes literature
   coverage is patchy (strong for TV/film/anime and darling web serials, thin
   for literary/midlist fiction): a missing page ≠ no comp.

## Playing-With mode taxonomy (store mode, not just presence)

- **Presentation/degree:** Played Straight · Exaggerated · Downplayed ·
  Justified · Inverted (incl. Gender-Inverted) · Subverted · Double
  Subverted · Untwisted · Zig-Zagged · Averted
- **Meta/production:** Enforced · Implied · Lampshaded
- **Character agency:** Invoked · Exploited · Defied · Discussed · Conversed
- **Critical distance:** Parodied · Deconstructed · Reconstructed
- **Tonal:** Played for Laughs · Played for Drama · Played for Horror

Two works sharing a trope in opposed modes (played straight vs deconstructed)
are **anti-comps**: they attract different readers with the same keyword. A
comps list that ignores mode misleads.

## Cautions (binding)

- **No checklist writing.** SoYouWantTo genre guides recapitulate what
  successful authors already did — useful scaffolding, but compliance
  produces the median existing book. Comps inform positioning; they do not
  dictate content.
- **Tropes are tools.** Presence is quality-neutral; execution and mode carry
  the value. Never frame a trope's presence as inherently a flaw or a merit.
- **Licensing.** CC BY-NC-SA: trope names and graph structure are usable;
  scraped page text is not shipped into outputs or the atlas. Structured
  alternative when needed: the dhruvilgala/tvtropes ACL-2020 dataset
  (~30K tropes / 1.9M examples).
