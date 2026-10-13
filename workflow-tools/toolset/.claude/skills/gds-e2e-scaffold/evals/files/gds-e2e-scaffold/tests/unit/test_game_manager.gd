extends GutTest
## Existing unit test — proves the GUT test framework is already initialized.
## (gds-test-framework / gds-test-init has already been run on this project.)

var gm


func before_each() -> void:
	gm = load("res://scripts/game_manager.gd").new()
	add_child(gm)


func after_each() -> void:
	gm.free()


func test_game_manager_initializes_ready() -> void:
	gm._ready()
	assert_true(gm.is_ready, "GameManager should be ready after _ready()")


func test_run_starts_at_wave_one() -> void:
	gm.start_run()
	assert_eq(gm.current_wave, 1, "Run should start at wave 1")
