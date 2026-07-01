# PlayerController — top-down player movement for the prototype.
#
# CONVENTION (follow this for any new movement ability):
# - Each ability is a small private helper `_apply_<ability>(delta: float) -> void`
#   that reads input and mutates `velocity` (the CharacterBody2D field).
# - Tunable numbers are exported `@export` vars at the top so designers can tweak
#   them in the Godot inspector. Do NOT hardcode magnitudes inside the helpers.
# - Register the helper by calling it from `_physics_process`; do NOT inline new
#   movement math directly in `_physics_process`.
extends CharacterBody2D

@export var move_speed: float = 220.0
@export var acceleration: float = 1400.0
@export var friction: float = 1600.0

func _physics_process(delta: float) -> void:
	_apply_walk(delta)
	move_and_slide()

func _apply_walk(delta: float) -> void:
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	if direction != Vector2.ZERO:
		velocity = velocity.move_toward(direction * move_speed, acceleration * delta)
	else:
		velocity = velocity.move_toward(Vector2.ZERO, friction * delta)
