# MathUtils.gd
# Plain, idiomatic GDScript helpers. Nothing unusual: no autoloads, no signal
# bus, no project-specific layering or surprising patterns. Just simple static
# functions.
class_name MathUtils
extends RefCounted

static func clamp_value(value: float, low: float, high: float) -> float:
	return clamp(value, low, high)

static func lerp_value(from: float, to: float, t: float) -> float:
	return lerp(from, to, t)

static func is_even(n: int) -> bool:
	return n % 2 == 0
