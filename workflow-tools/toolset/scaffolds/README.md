# scaffolds/ — project starter templates for `wf scaffold`

`scripts/wf-scaffold.py` reads these templates and emits a ready-to-use
project directory: the **minimal civilian starter**. (The former `--secure` /
`--team` postures and their `scaffolds/secure/` machinery were removed
2026-10-13 — `core/DECISIONS.md` D6.)

## How it maps

| Invocation                         | Profile               | Emitted                                                   |
|------------------------------------|-----------------------|-----------------------------------------------------------|
| `wf scaffold --out DIR`            | `civilian`            | CLAUDE.md + README + .gitignore + .env.example + `_bmad/` config glue |
| `--profile local-small-context`    | `local-small-context` | same files; CLAUDE.md is the small-context render         |

The **CLAUDE.md** placed in the generated project is the rendered
`adapters/<profile>/claude/CLAUDE.generated.md` for the chosen profile, so the
operating model the project ships with matches the profile. `--multi-repo`
emits a contracts repo + N member repos (each this same starter) plus a
repo-set manifest (`repos.manifest.yaml` by default) and `PROVISIONING.md` at
the parent level; each member gets a dependency pin (`repo-deps.yaml` by
default). The optional private data file `core/private/scaffold.yaml` may
override those names.

## Tree

```
scaffolds/
  README.md                       ← this file
  common/                         ← the templates every scaffold emits
    README.md.tmpl
    .gitignore.tmpl
    .env.example.tmpl
    bmad-bmm-config.yaml.tmpl     → _bmad/bmm/config.yaml
    bmad-core-config.yaml.tmpl    → _bmad/core/config.yaml
```

## Placeholders

Templates use simple `{{PLACEHOLDER}}` substitution. The substituted keys are:

- `{{PROJECT_NAME}}` — display name (e.g. `TactiChat`)
- `{{PROJECT_ID}}`   — slug (lowercase, hyphens; e.g. `tactitchat`)
- `{{PROFILE}}`      — the resolved profile id
- `{{DATE}}`         — ISO date the scaffold was generated
- `{{USER_NAME}}`    — `--owner` (BMAD config `user_name`)

## Secrets convention (load-bearing — do not break)

The scaffold **never** emits real IPs, hosts, ports, or tokens. `--selftest`
fails closed if a bare IP-shaped string or an unsubstituted placeholder ever
appears in any emitted file. New secret-bearing variables get a placeholder-only
entry in `.env.example.tmpl`.

## Deployment artifacts (`wf deploy`)

Deployment artifacts are **not** template files here — `scripts/wf-deploy.py`
generates them **programmatically** (like `wf-scaffold` does for its parent
multi-repo artifacts), so there is no `scaffolds/deploy/` directory. `wf
deploy prep --strat <edge|openshift|casual>` emits the strat's artifacts plus a
per-project `DEPLOYMENT.md` runbook into the chosen `--out` dir:

- **edge** — multi-tar make-bundle scripts (one per service-group) + a spanning
  `docker-compose.yml` + a `registry-manifest.json` version pointer + `install.sh`
  + `rollback.sh`. The service→tar→compose split is asked interactively (or via
  `--split 'tarA=svc1,svc2;tarB=svc3'`).
- **openshift** — `.github/workflows/openshift-deploy.yml` (build → tag → push to
  **Quay** → optional `oc` imagestream-import); all registry/cluster identifiers
  are `$ENV:`/`secrets.*` placeholders.
- **casual** — a plain `docker-compose.yml`.

The same secrets convention applies: every sensitive field is a `$ENV:`
placeholder, and the deploy `--selftest` (wired into `wf-doctor` check 24)
fails closed on a bare IP/secret leak. See
[`docs/deployment-strategies.md`](../docs/deployment-strategies.md).
