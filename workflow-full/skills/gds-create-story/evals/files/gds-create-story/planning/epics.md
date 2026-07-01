# EmberFall - Epic Breakdown (excerpt)

## Epic 2: Relics & Progression

### Story 2.1: Pick up a relic
As a player, I want to collect a relic from a treasure room, so that my build grows
during the run.
(Status: done — RelicSystem and the relic loadout state already exist.)

### Story 2.2: Stack duplicate relics
As a player, I want a second copy of a relic to stack additively, so that doubling
down on a relic is rewarded.

**Acceptance Criteria:**
**Given** the player already holds one copy of a relic,
**When** they pick up a second copy of that same relic,
**Then** the relic's passive modifier is applied a second time, additively (e.g. two
copies of "+15% melee damage" yield +30%).
**And** the pause-screen loadout shows the relic with a stack count of x2.
**And** picking up a relic the player does not yet hold adds it as a new entry at x1.
**And** stacking is capped at x5 per relic; a sixth copy is converted to gold instead.

### Story 2.3: Display the relic loadout
As a player, I want to see my active relics on the pause screen, so that I understand
my current build.
(Out of scope for 2.2 — the pause-screen UI layout work is its own story.)
