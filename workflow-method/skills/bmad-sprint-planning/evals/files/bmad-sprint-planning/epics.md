# Epics: GroceryCap

This document breaks the GroceryCap PRD into epics and stories for development.

## Epic 1: Household & Accounts

Goal: A household can be created and a second person can join, so a shared Weekly Cap has owners.

### Story 1.1: Create a Household Account
As a new user
I want to create a Household
So that I can set a shared Weekly Cap.

Acceptance Criteria:
- Given I am a signed-in user, When I create a Household, Then I become its first member.

### Story 1.2: Join a Household by Invite
As an invited user
I want to accept an invitation
So that I become the second member of a Household.

Acceptance Criteria:
- Given a valid invite, When I accept it, Then I am added as the second member.

## Epic 2: Receipt Capture

Goal: A user can scan a grocery receipt and commit a Trip total, so spending is captured.

### Story 2.1: Scan a Receipt
As a Household member
I want to photograph a receipt and have OCR extract the total
So that I do not type it by hand.

Acceptance Criteria:
- Given a receipt photo, When OCR runs, Then the extracted Trip total is shown editable before commit.

### Story 2.2: Correct an OCR Total
As a Household member
I want to edit the extracted total before commit
So that an OCR error never becomes a committed Trip.

Acceptance Criteria:
- Given an editable extracted total, When I change it and commit, Then the corrected value is stored.

### Story 2.3: Same-Day Duplicate Prompt
As a Household member
I want to be asked whether a same-day receipt replaces or adds to the earlier one
So that I do not double-count a Trip.

Acceptance Criteria:
- Given a receipt was scanned earlier today, When I scan another, Then the app asks replace-or-add before counting it.

## Epic 3: Cap & Remaining

Goal: A Household can set a Weekly Cap and see Remaining converge across both devices.

### Story 3.1: Set and Edit the Weekly Cap
As a Household member
I want to set or change the Weekly Cap
So that the household has a target.

Acceptance Criteria:
- Given I am a Household member, When I set the Weekly Cap, Then both members see the new value.

### Story 3.2: Show Remaining Against Cap
As a Household member
I want to see Trip total, Weekly Cap, and Remaining after a Trip commits
So that I know how the week is tracking.

Acceptance Criteria:
- Given a committed Trip, When I view the summary, Then Remaining equals Weekly Cap minus this week's committed Trip totals.

### Story 3.3: Sync Cap and Remaining Across Devices
As a Household member
I want the Cap and Remaining to converge across both devices
So that both members see the same numbers.

Acceptance Criteria:
- Given both devices are online, When a sync completes, Then both converge to the same Weekly Cap and Remaining.
