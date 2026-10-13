# Embertide — Context for Game Architecture

## What it is
Embertide is a 4-player online co-op survival-crafting game. Players share an island,
gather resources, build a base, and survive escalating night-time creature waves. Think
a smaller, cozier Valheim-style loop.

## Target / scope (agreed)
- Engine: Unity (the team knows it; this is locked).
- Platform: PC first (Steam), controller + KB/M.
- Online co-op, up to 4 players, drop-in/drop-out. One player hosts (peer-hosted/
  client-host model is acceptable for v1 — no dedicated servers budgeted yet).
- A persistent island world that saves between sessions (the host owns the save).
- Systems in v1: gathering/inventory, crafting, base building (placeable structures),
  day/night cycle, enemy wave spawning + simple combat, basic hunger/health.

## Team / constraints
- Small indie team (3 people). Must be shippable; avoid over-engineering.
- No dedicated-server budget for v1; host-authoritative networking is acceptable.
- Wants the architecture to keep simulation authority clear so co-op doesn't desync.

## Known concerns the team raised
- Keeping the host authoritative for world state (resources, enemy spawns, structure
  placement) so clients can't desync or cheat trivially.
- Save/load of a mutable world (placed structures, gathered/depleted resource nodes,
  player inventories) owned by the host, including a late-joiner getting current state.
- Performance of many placed structures + enemies in a wave on a mid-range PC.

## Deliberately undecided (team has NOT chosen)
- Networking transport/middleware (e.g. Netcode for GameObjects vs Mirror vs Photon).
- Whether to move to dedicated servers post-v1.
- Save format / serialization approach.
- Mod support (probably later, not v1).
