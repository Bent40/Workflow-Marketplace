# Game Brief Excerpt — "Hollow Drift" (technical/performance facts)

- **Engine:** Unity (URP).
- **Genre:** Top-down twin-stick roguelike. Single-player only (no multiplayer, no networking).
- **Target platforms:** PC (Steam) and mobile (iOS/Android). **No console SKUs planned.**
- **Frame-rate intent:** PC targets 60 FPS; mobile targets a stable 60 on high-tier devices, 30 on mid/low-tier (thermal-limited).
- **Structure:** Run-based. Each "run" is a sequence of procedurally combined rooms; there is **no open world, no fast-travel, no level streaming**. A run is loaded once at the start.
- **Worst-case load on the GPU:** "swarm" encounters can spawn 150+ enemies plus dense bullet/particle effects on screen at once. This is the primary frame-rate stress.
- **Memory concern:** procedural room generation across a long run (60-90 min) can accumulate pooled objects; the team has seen memory creep across many rooms.
- **Loading:** initial boot into the hub; then one room-set load at run start. Respawn-on-death restarts a fresh run (full reload acceptable).
- **Representative content available:** a "swarm gauntlet" test scene with maxed enemy counts, and a scripted 60-minute auto-play bot for soak testing.
- **Profiling tools available:** Unity Profiler, Unity Performance Testing package, and on-device Android GPU profiler.
