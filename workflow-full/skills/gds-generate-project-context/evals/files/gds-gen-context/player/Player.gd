# player/Player.gd
# UNOBVIOUS RULES embodied here:
#  1. All movement/physics runs in _physics_process, never _process.
#  2. Tunables are @export vars, never literals baked into the logic.
#  3. Death is announced by emitting EventBus.player_died — Player never
#     references the GameManager or UI directly.
extends CharacterBody2D

@export var speed: float = 220.0
@export var jump_velocity: float = -400.0
@export var gravity: float = 980.0

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta

	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = jump_velocity

	var direction := Input.get_axis("move_left", "move_right")
	velocity.x = direction * speed

	move_and_slide()

func die() -> void:
	# Announce via the bus; do NOT reach into other systems.
	EventBus.player_died.emit()
	queue_free()
