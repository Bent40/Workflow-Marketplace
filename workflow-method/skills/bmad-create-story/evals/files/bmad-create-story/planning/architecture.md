# Architecture — Tasklytic

## Tech stack

- Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic for migrations.
- Testing: `pytest`. Tests live under `tests/` mirroring the `src/` tree.

## Code structure

- `src/data/` — repositories (one class per aggregate, suffix `Repository`).
- `src/services/` — business-logic services (suffix `Service`). Services depend
  on repositories, never on the web layer.
- `src/api/` — FastAPI routers. Routers call services, never repositories
  directly.

## Service layer

Services are constructed with their repository dependencies injected via the
constructor (see `TaskService` in `src/services/task_service.py`). Scheduling
work is dispatched through the existing `JobQueue` abstraction in
`src/services/job_queue.py` — do not call the OS scheduler or `cron` directly.

## Persistence

All timestamps are stored and compared in **UTC**. The `RemindersRepository`
(added in story 2-1, `src/data/reminders_repository.py`) exposes
`add(reminder)`, `get_pending_for_task(task_id)`, and `cancel(reminder_id)`.
A second persistence path for reminders is forbidden — extend the repository if
new queries are needed.

## Testing standards

- Every new service gets a unit test file under `tests/services/`.
- Use the `freeze_time` fixture (already in `tests/conftest.py`) for any logic
  that depends on the current time.
