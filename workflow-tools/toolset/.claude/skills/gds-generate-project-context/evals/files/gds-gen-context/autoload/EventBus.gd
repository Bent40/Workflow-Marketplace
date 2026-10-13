# autoload/EventBus.gd
# UNOBVIOUS RULE: nodes NEVER call each other directly across systems. All
# cross-system communication goes through this single autoloaded signal bus
# (registered as the "EventBus" singleton in Project Settings > Autoload).
# Emit here; subscribe here. Direct get_node() references into other systems
# are forbidden.
extends Node

signal player_died
signal score_changed(new_score: int)
signal coin_collected(value: int)

# Helper so callers never emit signals on raw strings.
func emit_score_changed(new_score: int) -> void:
	score_changed.emit(new_score)
