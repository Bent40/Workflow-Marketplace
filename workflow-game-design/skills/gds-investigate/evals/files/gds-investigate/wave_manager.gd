extends Node
class_name WaveManager

signal wave_cleared(next_wave: int)

var current_wave: int = 1
var enemies_alive: int = 0

func start_wave(enemy_count: int) -> void:
	enemies_alive = enemy_count

# Called by each enemy when it dies.
func on_enemy_died() -> void:
	# BUG: the decrement is guarded so it never reaches 0; the last
	# enemy's death does not decrement, so the clear check below never fires.
	if enemies_alive > 1:
		enemies_alive -= 1

	if enemies_alive <= 0:
		current_wave += 1
		emit_signal("wave_cleared", current_wave)
