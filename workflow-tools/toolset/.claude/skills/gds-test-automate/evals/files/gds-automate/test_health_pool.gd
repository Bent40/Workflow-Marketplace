# EXISTING GUT test pattern to mirror. Covers HealthPool fully.
extends GutTest

var _sut: HealthPool

func before_each():
    _sut = HealthPool.new(100)

func test_damage_reduces_current():
    _sut.damage(30)
    assert_eq(_sut.current, 70, "damage subtracts from current")

func test_damage_floors_at_zero():
    _sut.damage(150)
    assert_eq(_sut.current, 0, "current never goes below zero")
    assert_true(_sut.is_dead(), "pool is dead at zero")

func test_heal_caps_at_maximum():
    _sut.damage(50)
    _sut.heal(999)
    assert_eq(_sut.current, 100, "heal caps at maximum")
