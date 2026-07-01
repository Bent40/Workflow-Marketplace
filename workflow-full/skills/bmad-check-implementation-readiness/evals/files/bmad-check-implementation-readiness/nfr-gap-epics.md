# Epics & Stories — SecureNotes

## FR Coverage Map

- FR-1: Epic 1 (Stories 1-1, 1-2, 1-3)
- FR-2: Epic 2 (Story 2-1)
- FR-3: Epic 1 (Story 1-4)
- NFR-1: Epic 2 (Story 2-2)

(NFR-2 and NFR-3 are not listed in this coverage map.)

## Epic 1 — Notes

User value: users can manage their encrypted notes.

- **1-1 Create a note** — As a user, I want to create a note with a title and body. ACs:
  1. Given I am authenticated and provide a title and body, when I save, then the note appears in my list.

- **1-2 Edit a note** — As a user, I want to edit an existing note. ACs:
  1. Given an existing note, when I edit and save, then the updated content is persisted.

- **1-3 Delete a note** — As a user, I want to delete a note. ACs:
  1. Given a note, when I delete it, then it is removed from the list.

- **1-4 Search notes** — As a user, I want to search my notes by keyword. ACs:
  1. Given a keyword, when I search, then only notes containing the keyword are shown.

## Epic 2 — Security

User value: notes are secure and access is controlled.

- **2-1 Master password authentication** — As a user, I must authenticate before viewing notes. ACs:
  1. Given a correct master password, when I authenticate, then I can view my notes.
  2. Given a wrong master password, when I authenticate, then access is denied.

- **2-2 Encryption at rest** — All notes are stored encrypted using AES-256. ACs:
  1. Given a note is saved, when I inspect the storage file, then the content is encrypted (not plaintext).
