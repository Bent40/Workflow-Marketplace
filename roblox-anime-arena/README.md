# Anime Arena

A Roblox wave-defense gacha: **roll anime fighters, deploy them on your base, survive the waves.**
Eight bases per map, each claimed by a player as they log in. Two currencies — **Gold** earned
in-game and **Gems** bought with Robux. A six-slot shop you refresh to fish for better units.

Built as Luau source with [Rojo](https://rojo.space), so the whole game is reviewable in a diff.

---

## Quick start

```bash
# 1. Install the toolchain (rokit, or install rojo however you like)
rokit install

# 2. Serve the project
rojo serve

# 3. In Roblox Studio: install the Rojo plugin, click Connect, then press Play
```

There is nothing to place by hand — `MapBuilder` generates the hub, the eight base plots,
their tracks and cores at server boot.

### Running the tests

```bash
./tests/run.sh          # 107 checks, no Roblox required
```

The suite loads the pure config/util modules under Roblox stubs and asserts on the parts
that are invisible in play but ruin the economy if wrong: the odds ladder, the luck curve,
pity ordering, wave determinism and scaling, the stat pipeline, upgrade curves and the shop's
refresh escalation.

---

## Before you publish

Two things are placeholders and **must** be filled in:

1. **Robux asset ids.** Every `Id` in `src/shared/Config/Monetization.luau` is `0`. Create the
   dev products and passes in the Creator Dashboard and paste their ids in.
   `MonetizationService` refuses to process an unconfigured id rather than granting by accident,
   so nothing breaks until you fill them — the products just won't be purchasable.
2. **Unit art.** Units render as coloured placeholder blocks. `BaseService.buildUnitModel` and
   `Widgets.unitCard` are the only two places that need to change to swap in real models.

---

## How it fits together

```
src/
  shared/          → ReplicatedStorage.Shared   (config + types + math, both sides)
    Config/          rarities, traits, mutations, units, waves, shop, upgrades,
                     items, codes, monetization, global tuning
    Util/            StatMath, WeightedPick, Format
    Net.luau         the entire remote surface, in one list
    Types.luau       shapes that cross the client/server boundary

  server/          → ServerScriptService.Server
    Services/        one file per concern; see below
    World/           MapBuilder — generates the arena at boot
    RateLimiter      per-player, per-remote sliding window
    init.server      builds remotes, starts services, binds every handler

  client/          → StarterPlayerScripts.Client
    Controllers/     State store, PanelManager, and one controller per panel
    UI/              Theme (tokens) and Widgets (constructors)
    init.client      wires pushes to controllers
```

### The rule everything follows

**The server decides; the client draws.** Every remote handler resolves the caller's profile,
validates its own arguments, and returns a `Result` — it never throws across the boundary.
The roll animation, the placement ghost turning green, the affordability greying on a button:
all cosmetic. The server re-checks every one of them.

`StatMath` is the single place a unit's numbers are computed, and both sides call it. That is
deliberate: a tooltip cannot promise damage the unit does not deal.

### Services

| Service | Owns |
| --- | --- |
| `DataService` | Profiles: DataStore load/save, session locking, autosave, shutdown flush |
| `CurrencyService` | The only writer of Gold/Gems/Items, plus derived luck/gold/slot values |
| `RollService` | The gacha: luck-weighted rarity, pity, trait and mutation rolls |
| `ShopService` | Six refreshable slots and the escalating refresh price |
| `InventoryService` | Granting, selling, locking, merging, the loadout, Equip Best |
| `BaseService` | Claiming one of 8 plots, placement legality, base integrity |
| `CombatService` | The wave runner: spawning, movement, targeting, damage, drops |
| `UpgradeService` | The four permanent gold sinks |
| `TraitService` | The Trait Machine |
| `MonetizationService` | Receipts and passes |
| `CodeService` | Redeemable codes |
| `MutationEventService` | The server-wide mutation window |
| `SyncService` | Builds snapshots and coalesces pushes to one per frame |

---

## Design decisions worth knowing

These are the places where the code makes a choice you might otherwise want to revisit.

**Two clocks in combat.** Enemy movement runs every Heartbeat so parts replicate smoothly;
targeting and damage run on a fixed 10Hz tick. Resolving every unit against every enemy each
frame is what actually costs server time, and 10Hz is imperceptible at tower-defense pacing.

**Pity resolves weakest-first.** A player sitting at both Legendary and Secret pity gets the
Legendary and keeps the Secret counter running. That is the less generous reading, and it is
what keeps the long-tail counters meaningful.

**The shop is the deterministic path, rolling is the lottery.** The shop has its own, much
flatter rarity table, and luck influences it at 45% strength. The gold price of each refresh
within a free-refresh interval escalates geometrically — that escalation is the entire reason
a player with a large bank cannot simply spin the shop until a God unit appears.

**Health is what makes tanks worth a slot.** Units don't die. A placed unit's Health stat is
added to the base's integrity pool, so a tank raises the pool the core draws from rather than
soaking hits itself.

**Support auras are global to the base, not positional.** A positional aura would make "where
do I put the support" the only real decision and collapse every optimal layout into the same
clump. Global auras keep placement about coverage of the track. Each distinct unit id
contributes only once, at its strongest, so stacking six copies of one support does nothing.

**Health outpaces bounty as waves climb.** That gap *is* the difficulty curve. It is asserted
in the test suite so a tuning pass can't quietly flatten it.

**Losing costs time, not progress.** When a base falls the run restarts at wave 1, but the
collection, levels and upgrades are untouched.

**A disconnect doesn't cost your run.** A released base is reserved for its owner for two
minutes; rejoining inside that window restores the plot at the same wave.

**Receipts confirm only after the grant is persisted.** `ProcessReceipt` returns
`NotProcessedYet` on every failure path, records each `PurchaseId` on the profile, and treats a
re-delivered id as a no-op. Roblox delivers at least once; this makes the grant idempotent.

---

## Original content

The unit roster, traits and enemies are **original to this project**. Reference screenshots of a
similar game were used to understand the genre's systems and screen layout, but the characters
here are not renamed real anime characters — that is the fastest way to get a Roblox experience
taken down, and the systems are what make the game anyway.

---

## What isn't built yet

The systems below are visible in the reference and have config or hooks in place, but no
gameplay implementation:

- **Clone Machine** — `Items.CloneCost` defines essence costs and durations per rarity; no
  service consumes them yet.
- **Evolution Machine** — not started.
- **Infinite Tower** — `InfiniteTicket` exists as an item and `Stats.HighestTower` is persisted;
  there is no tower mode.
- **Spin wheel, daily VIP chest, group rewards** — not started.
- **Leaderboards** — `BaseService` broadcasts per-base wave and owner, which is enough to build
  the People/Waves/Gold board, but the UI isn't written.
- **Unit skills / active abilities** — the reference has a SKILLS bar; not started.
