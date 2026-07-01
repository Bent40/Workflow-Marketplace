# Godot 4 (GDScript) — pure-logic gameplay class. ALREADY COVERED (see test_health_pool.gd).
class_name HealthPool
extends RefCounted

var maximum: int
var current: int

func _init(max_hp: int) -> void:
    maximum = max_hp
    current = max_hp

func damage(amount: int) -> void:
    current = clampi(current - amount, 0, maximum)

func heal(amount: int) -> void:
    current = clampi(current + amount, 0, maximum)

func is_dead() -> bool:
    return current <= 0
