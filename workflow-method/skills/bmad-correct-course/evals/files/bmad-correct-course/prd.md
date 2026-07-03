# PRD — FieldNote (offline field-survey app)

## Vision

A tablet app that lets field surveyors record site observations offline and sync
them when connectivity returns.

## Functional Requirements

- **FR-1** A surveyor can create an observation with notes and photos while
  fully offline.
- **FR-2** Observations sync automatically to the server when the device
  reconnects.
- **FR-3** Each observation is tagged with the surveyor's GPS location captured
  at creation time.
- **FR-4** A supervisor can review and approve submitted observations from a web
  dashboard.

## MVP Scope

In scope: offline capture (FR-1), sync (FR-2), GPS tagging (FR-3), supervisor
review (FR-4).

Out of scope: real-time collaboration; multi-language UI.

## Non-Goals

- Not a general-purpose GIS / mapping product.
