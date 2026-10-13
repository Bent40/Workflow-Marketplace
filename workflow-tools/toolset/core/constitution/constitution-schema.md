# Constitution + spec schema — Epic C / C1+C2

`core/constitution/*.yaml` holds **checkable constraints** (gates), distinct from
`core/rules/*.yaml` (guidance). `wf spec` (`scripts/wf-spec.py`) scaffolds
and validates per-feature spec packs and **gates them on the constitution**. This
composes with — never replaces — the BMAD authoring skills (`bmad-spec`,
`bmad-prd`, `bmad-create-epics-and-stories`), which own the authoring conversation.

## Constitution constraint shape

```yaml
# core/constitution/<area>.yaml   (security, architecture, data, ux)
constraints:
  - id: SEC-1                     # unique across ALL files
    statement: <the constraint>   # non-empty string
    activation: default           # default | secure_only
    check: <verify hint>          # human how-to-verify pointer
    severity: high                # low | medium | high
```

- **`activation` reuses the proven civilian/secure split:** `default` constraints
  are active in every profile; `secure_only` constraints are active **only** in the
  secure profile and **never** load into a civilian profile (same mechanism as
  `secure_only` rules — re-proven by the selftest's isolation assertion).
- Fail-closed: duplicate id, missing/blank statement, `activation`/`severity` out
  of range, or a non-mapping constraint ⇒ typed error (exit 2).

## Spec pack — `specs/<feature>/`

| File | Required sections |
|---|---|
| `spec.md` | Goal, Requirements, Out of scope |
| `plan.md` | Approach |
| `tasks.md` | Tasks |
| `acceptance.md` | Acceptance criteria, **Constitution acknowledgements** |

## `wf spec`

| Invocation | Behavior |
|---|---|
| `spec init <feature>` | scaffold the 4 files (idempotent); seeds `acceptance.md`'s acknowledgements with the **default** constraint ids |
| `spec check <feature> [--profile civilian\|secure]` | structural (sections) + constitution gate |
| `spec split <feature>` | `tasks.md` → `split-task.py` microtask packets |
| `spec --selftest` | self-check (wf-doctor check 19) |

`--profile` defaults to **civilian**. The **constitution gate** loads the
constraints active for the profile and asserts `acceptance.md` acknowledges every
active `id` — an acknowledgement is a list item beginning `- <ID>:` (deterministic
presence check; no LLM). Civilian excludes `secure_only`, so an `init`-seeded spec
passes civilian `check` and (correctly) fails secure `check` until the
`secure_only` ids are acknowledged. Exit 0 ok / 1 violations / 2 config error.
