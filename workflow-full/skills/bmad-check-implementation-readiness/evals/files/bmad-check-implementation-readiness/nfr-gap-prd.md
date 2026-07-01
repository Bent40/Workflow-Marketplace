# PRD — SecureNotes

## Vision

A local-only note-taking app for professionals who need strong confidentiality guarantees.

## Functional Requirements

- **FR-1** A user can create, edit, and delete encrypted notes.
- **FR-2** A user must authenticate with a master password before viewing any notes.
- **FR-3** A user can search notes by keyword.

## Non-Functional Requirements

- **NFR-1** All notes must be encrypted at rest using AES-256.
- **NFR-2** Authentication must lock out the user after 5 failed attempts for 60 seconds.
- **NFR-3** The app must open and display the note list in under 2 seconds on target hardware.

## MVP Scope

In scope: FR-1 through FR-3 and NFR-1 through NFR-3.
Out of scope: cloud sync, sharing, version history.
