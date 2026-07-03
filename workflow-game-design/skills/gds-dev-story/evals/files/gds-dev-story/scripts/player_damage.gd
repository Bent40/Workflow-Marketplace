# PlayerDamage — the player's damage gate.
#
# Holds a reference to the player's HealthComponent and decides whether an
# incoming hit is allowed through. It must NEVER edit health directly and must
# NEVER keep its own duplicate health value — it delegates to HealthComponent.
extends Node
class_name PlayerDamage

var _health: HealthComponent

func setup(health: HealthComponent) -> void:
	_health = health

func apply_damage(amount: int) -> void:
	# TODO (story 2-3): gate hits behind a brief invincibility window before
	# delegating to the HealthComponent.
	_health.take_damage(amount)

# TODO (story 2-3): advance any time-based state from an explicit delta tick so
# the invincibility window can be unit-tested deterministically.
