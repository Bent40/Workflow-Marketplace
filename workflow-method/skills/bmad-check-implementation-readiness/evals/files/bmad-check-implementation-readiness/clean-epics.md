# Epics & Stories — TaskFlow MVP

## FR Coverage Map

- FR-1: Epic 1 (Story 1-1)
- FR-2: Epic 1 (Story 1-2)
- FR-3: Epic 1 (Story 1-3)
- FR-4: Epic 1 (Story 1-4)
- NFR-1: Epic 2 (Story 2-1, performance test)
- NFR-2: Epic 1 (local storage; all stories write to SQLite)

## Epic 1 — Task Management

User value: a contributor can manage their daily tasks.

- **1-1 Create a task** — As a user, I want to create a task with a title and optional due date. ACs:
  1. Given I provide a title, when I submit the form, then a new task appears in my list with the correct title and due date.
  2. Given I omit the due date, when I submit, then the task is created with no due date.
  3. Given I omit the title, when I submit, then the form shows a validation error and no task is created.

- **1-2 Complete a task** — As a user, I want to mark a task as complete. ACs:
  1. Given an incomplete task, when I click complete, then it is marked done and moves out of the incomplete view.
  2. Given a completed task, when I view the incomplete list, then the completed task is not shown.

- **1-3 View incomplete tasks sorted by due date** — As a user, I want to see my incomplete tasks sorted soonest-first. ACs:
  1. Given multiple tasks with different due dates, when I open the task list, then tasks appear in ascending due-date order.
  2. Given tasks without a due date, when I open the task list, then undated tasks appear after dated tasks.

- **1-4 Delete a task** — As a user, I want to delete a task I no longer need. ACs:
  1. Given any task, when I click delete and confirm, then the task is permanently removed from my list.
  2. Given I click delete but cancel the confirmation, then the task remains.

## Epic 2 — Performance & Persistence

User value: tasks are fast to load and reliably saved locally.

- **2-1 Performance baseline test** — Verify the task list loads within 1 second for 500 tasks. ACs:
  1. Given 500 tasks in the local database, when the task list screen is opened, then it renders in under 1 second (measured via automated test).
