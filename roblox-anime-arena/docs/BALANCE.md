# Balance notes

Where the numbers came from and what happens if you change them. Everything referenced here
lives in `src/shared/Config/`.

## The core loop

```
kill enemies → gold → roll / buy units → deploy → survive further → more gold
                 ↓                          ↑
             upgrades ────────────────────────
```

Gold is the only in-game currency and every sink competes for it: rolling (1,500), deploying
units (per-unit `PlaceCost`), shop purchases, shop refreshes, and the four permanent upgrades.
That competition is intentional — a player who dumps everything into rolling has no gold to
deploy with, and a player who only upgrades never builds a collection.

## Rarity ladder

| Tier | Weight @ luck 1 | Odds | Pity |
| --- | ---: | ---: | ---: |
| Common | 1000 | 63.475% | — |
| Rare | 420 | 26.659% | — |
| Epic | 120 | 7.617% | — |
| Legendary | 28 | 1.777% | 40 |
| Mythic | 6.5 | 0.413% | 90 |
| Secret | 0.85 | 0.054% | 240 |
| God | 0.08 | 0.005% | 900 |

Luck does not simply multiply every weight (that would renormalise to no change). Each tier
carries a `LuckBias`: negative tiers decay toward a floor as luck rises, positive tiers scale up.
The test suite asserts that God odds strictly improve with luck and still stay under 2% at max.

**Pity resolves weakest-first.** Rolling a tier resets its counter and every counter below it.

## Wave scaling

```lua
health(w) = 1 + (w-1)*0.42 + (w-1)^1.72 * 0.028
bounty(w) = 1 + (w-1)*0.16 + (w-1)^1.22 * 0.010
```

Health is super-linear and bounty is close to linear. **That gap is the difficulty.** It means
raw stat-stacking stops working around wave 40 and the player has to start levelling and
merging instead of just placing more units.

If you flatten the health exponent, the game becomes trivially infinite. If you raise bounty
growth to match health, gold inflates and every sink stops mattering. `tests/run.luau` asserts
the gap still exists between wave 5 and wave 80.

Composition widens slowly (1 archetype early, up to 4 late) and every 10th wave is a boss wave
with the trash budget cut to 55%, so a boss wave is not just "the same wave plus a boss".

Wave specs are **deterministic** given a wave number — same composition on server and client,
which is what lets the client preview an upcoming wave without a round trip.

## Stat pipeline

Applied in this order, all multiplicative:

```
base → level → mutation → trait → support auras
```

Crit chance and crit damage are additive percentage points and applied last. Crit chance is
clamped to 100%.

Level growth is **additive** (`1 + (level-1) * 0.35`, so level 20 = 7.65x), not geometric.
Geometric growth on top of merging on top of traits compounds far too fast — a level 20 Superior
unit would trivialise every wave in the table.

## Traits

Trait odds are independent of the unit roll. The tiers are lifted from the reference's published
table (Sharp/Swift/Strong through Cursed) because those numbers are known-good for this genre.
`Ascendant` is ours — a second God trait that rewards board width (extra summons, range) rather
than more single-unit damage, so the top of the chase isn't one-dimensional.

Rerolling is **unconditional**. It can and will replace a Mythic trait with None. That tension is
the point of the machine; the client is expected to confirm before spending on a good unit.

## The shop

Six slots, its own rarity table, luck at 45% influence.

| Tier | Roll table | Shop table |
| --- | ---: | ---: |
| Epic | 7.617% | 16.317% |
| Legendary | 1.777% | 5.711% |
| Mythic | 0.413% | 1.496% |
| God | 0.005% | 0.030% |

The shop's table is deliberately **flatter and more generous at every tier** — roughly 3x the
roll table's Legendary rate and 6x its God rate. What gates the shop is not odds but **price**:
a God unit on a slot costs 42,000,000 gold, a Secret 5,200,000. So a rare slot appearing is
common; affording it is not.

That is the trade the two systems make. Rolling is cheap and random; the shop shows you exactly
what you would get and charges accordingly. The test suite asserts the shop's Legendary share
stays above the roll table's, so a tuning pass can't accidentally invert the relationship.

Refresh cost escalates at 1.85x per paid refresh within a free-refresh interval (5 min), capped
at 750k. **This escalation is the anti-whale mechanism.** Remove it and a player with a large
bank spins until a God unit appears, which collapses both the roll economy and the pity system.
Gem refreshes are a flat bypass and deliberately do *not* increment the escalation counter.

## Base integrity

```
max integrity = 1000 + Σ (Health of every placed unit)
```

Units never die. A TANK's Health raises the pool the core draws from — that is the whole reason
to spend a slot on one. Placing a tank mid-wave restores integrity proportionally, not fully.

## Tuning checklist

Before shipping a balance change, run `./tests/run.sh`. It will catch:

- a rarity ladder that no longer strictly decreases
- luck that stops improving top-tier odds, or that makes them too common
- pity thresholds out of order
- average unit power that doesn't increase with rarity
- wave entry counts that don't sum to the total (this desyncs the "X/Y left" counter and can
  stop a wave from ever registering as cleared)
- health scaling that no longer outpaces bounty
- upgrade or shop cost curves that stop rising
