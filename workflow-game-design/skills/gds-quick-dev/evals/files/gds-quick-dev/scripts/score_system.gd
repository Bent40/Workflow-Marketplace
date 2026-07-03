# ScoreSystem — central scoring for the arcade prototype.
#
# CONVENTION (follow this for any new scoring rule):
# - Each rule is a method `award_<event>(...) -> void` that mutates `_score`
#   through the single `_add(points)` helper. Never assign `_score` directly.
# - `_add` clamps the score at 0 (it can never go negative) and emits the
#   `score_changed(new_score)` signal so the HUD updates. Every score mutation
#   must go through `_add` so the signal always fires.
# - Register nothing else; the HUD listens on `score_changed`.
extends Node

signal score_changed(new_score: int)

var _score: int = 0

func get_score() -> int:
	return _score

func _add(points: int) -> void:
	_score = max(0, _score + points)
	score_changed.emit(_score)

func award_enemy_kill() -> void:
	_add(100)

func award_coin() -> void:
	_add(10)
