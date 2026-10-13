# Story: Add email validation to signup

Example story input for `scripts/split-task.py`. The `## Microtasks` list below is
the orchestrator's decomposition; split-task turns each item into a
contract-conformant microtask packet for a small-context worker. (This file is a
hand-authored example/fixture, not generated output.)

## Context

The signup endpoint currently accepts any string as an email address. We want it
to reject invalid emails.

## Acceptance Criteria

- Invalid email addresses are rejected with a 400 response.
- Valid email addresses continue to succeed.
- The new behavior is covered by unit tests.

## Microtasks

- Inspect the signup handler and report the current email-handling behavior.
- Add an `is_valid_email` helper in the validation module.
- Wire `is_valid_email` into the signup handler and return 400 on invalid input.
- Add unit tests for `is_valid_email` covering valid and invalid cases.
- Review the diff against the acceptance criteria and report risks.
