# UX Spec — TaskFlow MVP

## Screens

### Task List Screen
- Header: "My Tasks"
- Task rows: title, due date chip (if set), complete button (checkmark icon), delete button (trash icon)
- Tasks sorted by due date ascending; undated tasks at the bottom
- Empty state: "No tasks yet. Add your first task below."
- Add task inline form at the bottom: title field, optional due-date picker, Submit button

### Confirmation Dialog — Delete
- Title: "Delete task?"
- Body: "This cannot be undone."
- Actions: Cancel (secondary), Delete (destructive primary)

## Coverage
- FR-1: Add task inline form covers task creation with title and optional due date.
- FR-2: Checkmark icon / complete button on each task row.
- FR-3: Task list screen with ascending due-date sort.
- FR-4: Delete button + confirmation dialog.
