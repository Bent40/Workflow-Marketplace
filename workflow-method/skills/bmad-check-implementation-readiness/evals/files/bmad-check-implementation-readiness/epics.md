# Epics & Stories — PetClinic Scheduler

## FR Coverage Map

- FR-1: Epic 1 (Story 1-1)
- FR-2: Epic 2 (Story 2-2)
- FR-3: Epic 2 (Story 2-3)
- FR-5: Epic 3 (Story 3-1)

(FR-4 is intentionally absent from this map.)

## Epic 1 — Accounts & pets

User value: a pet owner can get set up to book.

- **1-1 Register and add pets** — As a pet owner, I want to register and add my
  pets, so that I can book for them. ACs:
  1. Given valid details, when I register, then an account is created.
  2. Given I am registered, when I add a pet, then it appears in my pet list.

## Epic 2 — Booking

User value: a pet owner can manage appointments.

- **2-1 Set up the database** — Create all the tables and SQLAlchemy models for
  accounts, pets, appointments, and slots up front. ACs:
  1. The schema is created.
- **2-2 Book an appointment** — As a pet owner, I want to book an open slot, so
  that my pet is seen. ACs:
  1. Given an available slot, when I book it, then the appointment is created and
     the slot is marked taken.
  2. Given a slot that was just taken by someone else, when I try to book it,
     then I get an error and no double-booking occurs.
- **2-3 Reschedule or cancel** — As a pet owner, I want to change or cancel an
  appointment. ACs:
  1. The user can reschedule.
  2. The user can cancel.

## Epic 3 — Staff dashboard

User value: staff can run the day.

- **3-1 Staff schedule view** — As clinic staff, I want to see and adjust the
  day's schedule. ACs:
  1. Given I am staff, when I open the dashboard, then I see today's
     appointments.
  2. Given an appointment, when I move it to another open slot, then the change
     is saved and the owner is notified.
