"""Checks on the physical values the physics service is given.

A NaN or an infinity sent to the world spreads to every body it touches, and a
mass of zero is made a tiny one, so each value is checked where the
application hands it over and a ValueError names the argument.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

__all__ = ['number', 'vector']


def number(value: Any, name: str, *, positive: bool = False,
           non_negative: bool = False) -> float:
    """``value`` as a finite float; ValueError naming ``name`` where it is not one.

    ``positive`` asks for one above zero and ``non_negative`` for one at or above it.
    """
    found = float(value)
    if not math.isfinite(found):
        raise ValueError('%s must be finite, not %r' % (name, value))
    if positive and not found > 0.0:
        raise ValueError('%s must be above zero, not %r' % (name, value))
    if non_negative and found < 0.0:
        raise ValueError('%s must not be below zero, not %r' % (name, value))
    return found


def vector(value: Iterable[Any], name: str, size: int = 3) -> tuple[float, ...]:
    """``value`` as a tuple of ``size`` finite floats; ValueError naming ``name`` where it is not."""
    found = tuple(float(v) for v in value)
    if len(found) != size:
        raise ValueError('%s must have %d numbers, not %r' % (name, size, value))
    if not all(math.isfinite(v) for v in found):
        raise ValueError('%s must be finite, not %r' % (name, value))
    return found
