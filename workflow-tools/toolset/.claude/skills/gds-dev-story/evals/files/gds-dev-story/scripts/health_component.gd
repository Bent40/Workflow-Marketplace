# HealthComponent — the single source of truth for the player's health.
# This is the ONLY place health is mutated. Do not add a second health store.
extends Node
class_name HealthComponent

signal health_changed(current: int, max: int)

@export var max_health: int = 100
var _current: int

func _ready() -> void:
	_current = max_health

func get_health() -> int:
	return _current

func take_damage(amount: int) -> void:
	if amount <= 0:
		return
	_current = max(0, _current - amount)
	health_changed.emit(_current, max_health)

func heal(amount: int) -> void:
	if amount <= 0:
		return
	_current = min(max_health, _current + amount)
	health_changed.emit(_current, max_health)
