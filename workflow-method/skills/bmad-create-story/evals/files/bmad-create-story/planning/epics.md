# Epics — Tasklytic

## Epic 2 — Task Reminders

**Objective:** Let users receive reminders for tasks that have a due date, so
work does not silently slip past its deadline. Business value: increases task
completion rate, the product's north-star metric.

Stories in this epic:

- **2-1 — Reminder data model** (status: done) — Added a `reminders` table and
  the `Reminder` model. Established the `RemindersRepository` pattern under
  `src/data/`. Reminders are stored with a `fire_at` UTC timestamp and a
  `delivered` boolean.
- **2-2 — Reminder scheduling** (this story, backlog) — Schedule a reminder to
  fire at `task.due_at` minus the user's configured `lead_time_minutes`. The
  scheduler must enqueue the reminder when a task with a due date is created or
  its due date changes, and cancel/reschedule when the due date is removed or
  changed.
- **2-3 — Reminder delivery channel** (backlog) — Deliver fired reminders via
  email and in-app banner.

### Story 2-2 — Reminder scheduling

**As a** task owner,
**I want** a reminder scheduled automatically when I set a due date,
**so that** I am notified before the task is due without configuring anything.

**Acceptance criteria (BDD):**

1. Given a task is created with a `due_at`, when it is saved, then a `Reminder`
   row is created with `fire_at = due_at - lead_time_minutes`.
2. Given a task's `due_at` is changed, when it is saved, then the existing
   pending reminder is rescheduled to the new `fire_at`.
3. Given a task's `due_at` is removed, when it is saved, then any pending
   reminder for that task is cancelled (not delivered).
4. Given `fire_at` would be in the past at schedule time, when scheduling, then
   the reminder is created already-due so it fires on the next scheduler tick.

**Technical requirements:**

- Scheduling logic lives in a new `ReminderScheduler` service.
- Must reuse the existing `RemindersRepository` from story 2-1 — do NOT write a
  second persistence path.
- Lead time comes from `UserSettings.lead_time_minutes` (default 30).

**Source hints:** see architecture sections "Service layer" and "Persistence".
