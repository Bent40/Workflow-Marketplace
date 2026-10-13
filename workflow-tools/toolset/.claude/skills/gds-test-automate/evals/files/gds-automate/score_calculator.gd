# Godot 4 (GDScript) — pure-logic gameplay class. UNTESTED.
# Computes a run's score from kills, a combo multiplier, and time bonus.
class_name ScoreCalculator
extends RefCounted

const MAX_COMBO := 8

# Returns the score for a wave.
#  base_kills: int >= 0     (each kill is worth 10 base points)
#  combo: int (clamped to 0..MAX_COMBO; multiplier is 1 + combo*0.25)
#  seconds_remaining: float >= 0 (time bonus = floor(seconds_remaining) * 5)
# Raises (via assert) on negative base_kills or negative seconds_remaining.
func score_wave(base_kills: int, combo: int, seconds_remaining: float) -> int:
    assert(base_kills >= 0, "base_kills must be >= 0")
    assert(seconds_remaining >= 0.0, "seconds_remaining must be >= 0")
    var clamped_combo: int = clampi(combo, 0, MAX_COMBO)
    var multiplier: float = 1.0 + float(clamped_combo) * 0.25
    var kill_points: int = int(round(float(base_kills * 10) * multiplier))
    var time_bonus: int = int(floor(seconds_remaining)) * 5
    return kill_points + time_bonus

# Grades the score into a letter rank.
func rank_for(score: int) -> String:
    if score >= 1000:
        return "S"
    elif score >= 500:
        return "A"
    elif score >= 200:
        return "B"
    else:
        return "C"
