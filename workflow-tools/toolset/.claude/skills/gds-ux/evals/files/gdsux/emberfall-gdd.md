# Emberfall — GDD excerpt (game UX input)

**Game.** Emberfall is a 2D side-scrolling action-platformer. Engine: Godot 4
(Control nodes for UI). Target platforms: PC (keyboard+mouse and gamepad) and
Steam Deck (gamepad, smaller handheld screen). Stakes: commercial indie.

**Core loop.** Explore interconnected biomes, fight enemies, manage a "heat"
resource that powers a dash and a charged attack. Heat depletes over time and
refills by landing hits; running out of heat makes the player vulnerable.

**Combat & feel.** Fast, momentum-driven. Hits should feel crunchy. The
developer wants the player to *feel* their heat level rising and draining without
staring at a number.

**HUD needs (from the developer):**
- Player health.
- The heat resource — central to the feel; must be readable at a glance during
  fast combat.
- Current equipped charged-attack state (ready / charging / spent).
- A minimal, non-intrusive look — "I don't want a cluttered MMO HUD; the art
  should breathe."

**Menus needed:** title screen, pause menu, an options menu with control
remapping (required for both keyboard and gamepad), and an inventory/upgrade
screen.

**Player journey (from playtests):** Rosa, a Steam Deck player on her third run,
chains a dash into a charged attack at low heat to clear a room before her heat
runs out — the tense climax beat is the moment she commits with almost no heat
left.

**Out of scope for v1:** online multiplayer, controller motion/gyro, VR.
