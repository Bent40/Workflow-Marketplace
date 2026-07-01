# Repo evals — observing a skill on a real codebase

Artifact and counterfactual evals run a skill against a *prompt + staged fixture
files*. A **repo eval** goes one step further: it points the runner's existing
project-copy isolation at a **checked-in fixture repository** and observes how the
agent behaves on a *real change in a real repo* — the closest proxy to production
use. No new code is needed; this is a recipe over the isolation the runner already
has (`references/isolation.md`).

## When to use

When a skill's value only shows up against real repo structure — cross-file
edits, build/test wiring, navigating an existing module graph — and a single
staged file can't represent that. (For pure prose/output skills, an artifact eval
is enough; don't reach for this.)

## Recipe

1. **Check in a small fixture repo** under the skill's eval tree, e.g.
   `evals/fixtures/<scenario>-repo/` — a minimal but *real* project (a few
   modules, a test, a README) that the skill's task will operate on. Keep it
   small; it is committed and lives forever.

2. **Point an eval at it via `files` + `--project-root`.** Stage the fixture repo
   as the eval's working tree and set the project root to the fixture so the
   runner copies *it* (not the host project) into the isolated workspace:

   ```
   wf eval <skill-path> --evals <skill>/evals/repo-evals.json \
     --project-root <skill>/evals/fixtures/<scenario>-repo
   ```

   The eval `prompt` describes the real change ("add endpoint X and a test"); the
   `expectations` assert against the *resulting repo state* (the new file exists
   and imports correctly, the test runs, no unrelated file was rewritten).

3. **Grade on repo outcomes, not just text.** Good repo-eval expectations check
   the diff and the build: a file was created at the right path, the existing
   test suite still passes, an unrelated module was left byte-identical. The
   grader walks the workspace after the run (it already has the artifacts dir).

4. **Pair with a counterfactual run** when the question is "does the skill help
   *here*": run the same fixture-repo eval `--mode counterfactual` to see whether
   the skill changes the real-repo outcome vs. without it.

## Honesty notes

- A fixture repo is a *representative* sample, not the user's real repo — say so;
  a green repo eval is evidence the skill works on *that* structure.
- Trigger evals should still run under Docker when available — local mode can let
  the host's installed skills bleed in via cwd-based discovery (`isolation.md`).
- Keep fixtures minimal and committed; never point a repo eval at a path outside
  the eval tree (it would copy whatever happens to be there into the workspace).
