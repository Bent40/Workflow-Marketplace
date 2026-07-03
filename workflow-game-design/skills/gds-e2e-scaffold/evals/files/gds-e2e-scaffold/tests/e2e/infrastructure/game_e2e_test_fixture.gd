extends GutTest
## EXISTING E2E test fixture base — Ember Drift already has E2E infrastructure.
## This file's presence under tests/e2e/ means the e2e-scaffold preflight should
## FAIL: "No existing E2E infrastructure" is not satisfied.

var game_manager
var scenario
var input_sim


func before_all() -> void:
	# Load main scene, wait for GameManager ready, wire up helpers.
	pass


func after_all() -> void:
	# Tear down scene, free helpers.
	pass


func _wait_for_ready() -> void:
	# Existing async-ready helper.
	pass
