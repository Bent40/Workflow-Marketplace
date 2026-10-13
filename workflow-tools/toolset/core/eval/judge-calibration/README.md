# Judge calibration gold set

`wf calibrate` measures how well an LLM **judge** (the one behind `wf orchestra
--grader judge`, `bmad-eval-runner`, and the review gates) agrees with **human**
labels — Cohen's kappa — and fails the judge below a floor. This makes the
*measurer itself* falsifiable, closing a gap in the "measured, not asserted" bar:
every judge gate is otherwise trusted but never validated.

## This is a PLACEHOLDER

`example.jsonl` carries **synthetic, illustrative** labels so the harness has its
shape and the selftest has data. **It is not a real calibration.** A trustworthy
calibration needs **real human-labeled `(output, verdict)` pairs** for the judge
and criteria you actually use — synthetic labels prove the math runs, nothing
more (the same honesty stance as `wf finetune`'s empty training scaffold).

## How to make it real

1. Collect a few dozen real outputs your judge will grade, across PASS and FAIL.
2. Have a human label each `gold: "PASS" | "FAIL"` against the `criterion`.
3. Save them here as JSONL (`{"id","output","gold","criterion"}`).
4. Run: `wf calibrate --gold core/eval/judge-calibration/<your>.jsonl \
   --judge-model <url> --judge-model-name <name> --floor 0.6`

Keep the set **small and scoped to the owned/priority judges** — a tiny set's
kappa is itself noisy, so treat the result as a **floor check**, not a precise
score.
