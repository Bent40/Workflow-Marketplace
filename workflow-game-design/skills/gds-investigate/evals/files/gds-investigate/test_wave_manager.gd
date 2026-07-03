extends GutTest

# Reproduction of BUG-209: wave never clears on the final kill.

func test_wave_clears_when_all_enemies_dead() -> void:
	var wm = WaveManager.new()
	add_child(wm)
	wm.start_wave(5)

	var cleared = [false]
	wm.wave_cleared.connect(func(_n): cleared[0] = true)

	for i in range(5):
		wm.on_enemy_died()

	# enemies_alive should reach 0 and the wave should clear, advancing to wave 2.
	assert_eq(wm.enemies_alive, 0, "all 5 enemies dead -> enemies_alive should be 0")
	assert_true(cleared[0], "wave_cleared should have been emitted")
	assert_eq(wm.current_wave, 2, "current_wave should advance to 2")
