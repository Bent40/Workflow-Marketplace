# GDD Excerpt — "Lantern Keep" (design facts for test design)

- **Engine / platforms:** Unity. Single-player only. PC (Steam) and Nintendo Switch. **No multiplayer. No microtransactions / no in-app purchases (premium one-time purchase).**
- **Genre:** cozy base-defense + crafting roguelite.

## Core mechanics
1. **Lantern light radius** — the player's lantern projects a light radius; enemies entering darkness inside the keep deal extra damage. Oil drains over time; refilling oil expands the radius.
2. **Crafting** — collect 3 resource types (wood, iron, ember) to craft 8 defensible structures. Recipes gate on resource counts.
3. **Night waves** — each in-game night spawns escalating enemy waves; surviving to dawn advances the run.
4. **Permadeath + meta-progression** — death ends the run, but earned "embers" persist and unlock new starting recipes (save/load of meta-progression is critical).

## Progression / persistence
- A run is in-memory; only meta-progression (unlocked recipes, ember bank) is saved to disk between runs.
- Save corruption would lose permanent unlocks — high data-integrity risk.

## Platform requirements
- Must pass **Nintendo Switch (Lotcheck) certification**: suspend/resume handling, controller disconnect handling, and save-during-suspend safety are required.
- Full controller support on both platforms; Steam Deck input must work.

## Known risk areas (per the team)
- The oil-drain / light-radius math interacts with the damage system — a balance/logic risk.
- Save-during-night-wave (autosave timing) is suspected to be fragile.

## Explicitly OUT of scope for this title
- No multiplayer / co-op.
- No leaderboards or online services.
- No monetization beyond the one-time purchase.
