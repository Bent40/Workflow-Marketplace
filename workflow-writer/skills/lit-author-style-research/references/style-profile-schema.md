# Author style profile — output schema

Seven sections, in order. Split measurable from interpretive; cite every
interpretive claim; give per-section confidence (high/medium/low).

## 1. `meta`
Author · corpus basis (works/period the profile rests on) · editorial caveats
(editor-made signatures, e.g. Carver/Lish) · per-section confidence · sources
with tier (T1 author's own craft statements / T2 scholarship / T3 craft blogs
/ T4 primary-text sampling).

## 2. `movement_context`
Nearest families from the working taxonomy — minimalism, maximalism, gothic,
noir/hardboiled, magical realism, stream-of-consciousness, metafiction,
lyrical, transparent/invisible, purple (as failure mode) — plus where the
author deviates from the family template.

## 3. `measurable_signature` (bands, not points; mark UNMEASURED when thin)
- Sentence-length band + variance + distribution shape (never mean alone).
- Syntax: coordination vs subordination lean, clauses per T-unit, phrasal
  density, fragment tolerance.
- Punctuation fingerprint: hot marks and cold marks (authors separate on
  relative mark frequencies alone).
- Lexicon: register, concreteness, Latinate vs Anglo-Saxon lean, signature
  words; word-frequency/function-word profile (requires ≥2,500 words of
  primary text — the Burrows's-Delta basis).
- Lexical-diversity band via MTLD (never raw TTR — length-dependent).
- Dialogue ratio (% words inside quotes) against a genre baseline (~50%
  genre fiction, ~30% literary).
- Paragraph rhythm and white-space habits.

## 4. `narrative_mechanics` (the habits generic imitation misses)
POV and tense defaults · thought presentation (direct / indirect / free
indirect) · scene construction and pacing moves · dialogue mechanics (tags,
beats, dialect rendering) · figuration density and preferred trope families ·
tonal stance (style as a way of thinking, not surface flourishes).

## 5. `negative_constraints`
The explicit NOT-list — what this author never does (e.g. Márquez's narrator
never shows astonishment). Strongest single lever against generic-LLM drift;
minimum three entries or explain why fewer.

## 6. `emulation_notes`
Franklin loop (summarize a passage → regenerate from the summary → diff
against the original) · syntax pattern templates, structure only, no lifted
phrases · known failure modes (pastiche→parody, purple drift, applying the
style to the wrong register).

## 7. `verification`
Concrete assertions a text claiming this style must satisfy (band checks from
§3, NOT-list from §5) + the standing caution: descriptive profile, not
authorship-identification evidence.

## Known traps
Short samples (<2,500 words) make every metric noise · raw TTR is invalid ·
cross-genre comparisons mislead · adversarial imitation defeats stylometry ·
point values overfit — always bands.

## Method sources
- Leech & Short style checklist: https://www.uv.es/~tronch/stu/CommentTextsGuideChecklist.html
- Programming Historian, stylometry with Python: https://programminghistorian.org/en/lessons/introduction-to-stylometry-with-python
- GPT-4o literary style imitation study (DSH 2025): https://academic.oup.com/dsh/article/40/2/587/8118784
