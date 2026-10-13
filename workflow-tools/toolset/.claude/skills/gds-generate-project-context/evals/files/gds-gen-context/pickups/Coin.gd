# pickups/Coin.gd
# A collectible. Note it talks to nothing directly — it just emits on the bus.
extends Area2D

@export var value: int = 10

func _on_body_entered(body: Node2D) -> void:
	if body.is_in_group("player"):
		# Cross-system notification ALWAYS goes through EventBus.
		EventBus.coin_collected.emit(value)
		queue_free()
