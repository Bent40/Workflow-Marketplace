"""Small, well-tested utility module for clamping a numeric value to a range."""

from typing import Union

Number = Union[int, float]


def clamp(value: Number, low: Number, high: Number) -> Number:
    """Clamp `value` into the inclusive range [low, high].

    Raises ValueError if low > high so callers cannot pass an inverted range.
    """
    if low > high:
        raise ValueError(f"low ({low}) must not exceed high ({high})")
    if value < low:
        return low
    if value > high:
        return high
    return value


# --- tests ---

def test_within_range():
    assert clamp(5, 0, 10) == 5


def test_below_low():
    assert clamp(-3, 0, 10) == 0


def test_above_high():
    assert clamp(99, 0, 10) == 10


def test_boundaries_inclusive():
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_inverted_range_rejected():
    try:
        clamp(5, 10, 0)
        assert False, "expected ValueError"
    except ValueError:
        pass
