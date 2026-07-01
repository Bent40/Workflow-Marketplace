# Epics: GroceryCap

## Epic 1: Household & Accounts and First Cap View

Goal: A household can be created, a second person can join, and members can see Remaining against the Weekly Cap.

Success Criteria:
- A user can create a Household and invite a second member.
- An invited user can join.
- After a Trip commits, members see Trip total, Weekly Cap, and Remaining, and Remaining stays correct across both devices.

### Story 1.1: Create a Household Account
As a new user, I want to create a Household, So that I can set a shared Weekly Cap.
Acceptance Criteria:
- Given a signed-in user, When they create a Household, Then they become its first member.

### Story 1.2: Join a Household by Invite
As an invited user, I want to accept an invitation, So that I become the second member.
Acceptance Criteria:
- Given a valid invite, When accepted, Then the user is added as the second member.

### Story 1.3: Show Remaining Against Cap
As a Household member, I want to see Remaining after a Trip commits, So that I know how the week is tracking.
Acceptance Criteria:
- Given a committed Trip, When viewing the summary, Then Remaining equals Weekly Cap minus this week's committed Trip totals.
- Given two devices, When a sync completes, Then both devices show the same Remaining.

## Epic 2: Receipt Capture

Goal: A user can scan a receipt and commit a Trip total.
(Not yet started.)
