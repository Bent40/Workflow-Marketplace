extends Node
## GameManager — primary game-state autoload for Ember Drift.
## Holds run state, the active wave, and player resources.

signal game_ready
signal run_ended(victory: bool)

var is_ready: bool = false
var current_wave: int = 0
var player_health: int = 100
var ember_currency: int = 0
var active_enemies: Array = []

const MAIN_SCENE := "res://scenes/main.tscn"


func _ready() -> void:
	_initialize_systems()
	is_ready = true
	game_ready.emit()


func _initialize_systems() -> void:
	# Load player profile, seed RNG, spawn first wave.
	current_wave = 1
	player_health = 100
	ember_currency = 0


func start_run() -> void:
	current_wave = 1
	player_health = 100


func load_from_save(save_name: String) -> void:
	# Restore run state from a save file under user://saves/.
	pass


func is_run_active() -> bool:
	return player_health > 0
