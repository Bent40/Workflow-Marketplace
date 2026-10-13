# Architecture — MiniBlog

## Tech stack

- Python 3.12, SQLAlchemy 2.x.
- Testing: `pytest`. Tests live under `tests/` mirroring the `src/` tree.

## Service layer

Services (suffix `Service`, under `src/blog/`) receive their repository
dependencies via the constructor. Services NEVER open an ORM session or run a
query directly — they call repository methods only.

## Persistence

`PostRepository` (`src/blog/post_repository.py`) is the single persistence path
for posts. It already exposes:

- `slug_exists(slug: str) -> bool` — lower-cases the slug, then checks existence.
- `add(post) -> Post` — persists and returns the post.

A second persistence path for posts is forbidden — extend the repository if a
new query is needed.

## Testing standards

- Every service change gets/updates a unit test file under `tests/blog/`.
- Tests must include the failing case first (assert the raised error) before the
  passing case.
