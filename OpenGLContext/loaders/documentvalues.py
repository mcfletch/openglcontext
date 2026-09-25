"""Numbers, flags and names read out of a document, checked before use.

A model file is input the running program does not control: a value in a
custom property may be misspelt, of the wrong type, infinite, or far outside
anything the engine can draw. :class:`DocumentValues` reads one value at a
time and answers something usable. A value it cannot use is reported and
replaced by the reader's default, and a value outside the declared bounds is
reported and clamped to them, so a malformed property is a model to load
rather than a file to refuse::

    values = DocumentValues(logger=log)
    depth = values.number(params.get('depth'), 0.0, 'water depth', minimum=0.0)
    views = values.integer(extras.get('views'), 0, 'impostor views', minimum=0)
    hemi = values.flag(extras.get('hemi'), True, 'impostor hemisphere')

Each distinct report is logged once per :class:`DocumentValues`, so one
reader held for the length of a load reports a value repeated on a thousand
primitives once. A reader handed ``warn`` reports through that instead, which
is how a reader already holding a once-per-document report joins it.

:func:`bounded` is the same check with no report, for a value code set on a
node: a field an application wrote is read through it where a NaN or an
infinity would otherwise reach ``int()`` in a frame.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable, Iterable, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

__all__ = ['DocumentValues', 'bounded', 'TRUE', 'FALSE']

#: The spellings a flag reads as true, and as false, compared lower-cased.
TRUE = frozenset(('1', 'true', 'yes', 'on'))
FALSE = frozenset(('0', 'false', 'no', 'off'))


def _as_float(raw: Any) -> Optional[float]:
    """``raw`` as a finite float, or None. A bool is not a number here."""
    if isinstance(raw, bool):
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _clamped(number: float, minimum: Optional[float],
             maximum: Optional[float]) -> float:
    if minimum is not None and number < minimum:
        return minimum
    if maximum is not None and number > maximum:
        return maximum
    return number


def bounded(value: Any, default: float, minimum: Optional[float] = None,
            maximum: Optional[float] = None) -> float:
    """``value`` as a finite float within the bounds given.

    ``default`` where ``value`` is not a finite number; the nearer bound where
    it lies outside them.
    """
    number = _as_float(value)
    if number is None:
        return default
    return _clamped(number, minimum, maximum)


class DocumentValues:
    """Reads values from one document, reporting each problem once.

    ``warn`` receives each report's text; without one, reports are logged as
    warnings on ``logger`` (this module's where none is given), each distinct
    text once.
    """

    def __init__(self, warn: Optional[Callable[[str], None]] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        self._warn = warn
        self._logger = logger or log
        self._said: Set[str] = set()

    def warn(self, message: str) -> None:
        """Report ``message``, once for this reader."""
        if message in self._said:
            return
        self._said.add(message)
        if self._warn is not None:
            self._warn(message)
        else:
            self._logger.warning('%s', message)

    def number(self, raw: Any, default: float, what: str, *,
               minimum: Optional[float] = None,
               maximum: Optional[float] = None) -> float:
        """``raw`` as a finite float within the bounds, or ``default``.

        None is an absent value and is ``default`` without a report. A value
        that is no finite number is reported and is ``default``; one outside
        the bounds is reported and is the nearer bound.
        """
        if raw is None:
            return default
        number = _as_float(raw)
        if number is None:
            self.warn('%s is %r, which is not a finite number; it is taken as %r'
                      % (what, raw, default))
            return default
        clamped = _clamped(number, minimum, maximum)
        if clamped != number:
            self.warn('%s is %r, outside %s; it is taken as %r'
                      % (what, raw, _range(minimum, maximum), clamped))
        return clamped

    def integer(self, raw: Any, default: int, what: str, *,
                minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
        """``raw`` as a whole number within the bounds, or ``default``.

        ``2``, ``2.0`` and ``"2"`` are all 2; ``2.5`` is no whole number and
        is reported, as :meth:`number` reports what is no number at all.
        """
        if raw is None:
            return default
        number = _as_float(raw)
        if number is None or not number.is_integer():
            self.warn('%s is %r, which is not a whole number; it is taken as %r'
                      % (what, raw, default))
            return default
        return int(self.number(number, default, what, minimum=minimum,
                               maximum=maximum))

    def flag(self, raw: Any, default: bool, what: str) -> bool:
        """``raw`` as a bool, or ``default``.

        A bool is itself; a number is its truth; a string is true for one of
        :data:`TRUE` and false for one of :data:`FALSE`, in any case. Anything
        else is reported and is ``default``.
        """
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and math.isfinite(raw):
            return bool(raw)
        if isinstance(raw, str):
            word = raw.strip().lower()
            if word in TRUE:
                return True
            if word in FALSE:
                return False
        self.warn('%s is %r, which is neither true nor false; it is taken as %r'
                  % (what, raw, default))
        return default

    def choice(self, raw: Any, default: str, what: str,
               options: Iterable[str]) -> str:
        """``raw`` as one of ``options``, compared lower-cased, or ``default``."""
        if raw is None:
            return default
        allowed = tuple(options)
        word = raw.strip().lower() if isinstance(raw, str) else None
        if word is not None and word in allowed:
            return word
        self.warn('%s is %r, which is not one of %s; it is taken as %r'
                  % (what, raw, ', '.join(allowed), default))
        return default

    def vector(self, raw: Any, default: Sequence[float], what: str,
               length: int = 3) -> Tuple[float, ...]:
        """``raw`` as ``length`` finite floats, or ``default``."""
        if raw is None:
            return tuple(default)
        if isinstance(raw, (list, tuple)) and len(raw) == length:
            numbers = [_as_float(value) for value in raw]
            if all(number is not None for number in numbers):
                return tuple(numbers)  # type: ignore[arg-type]
        self.warn('%s is %r, which is not %d finite numbers; it is taken as %r'
                  % (what, raw, length, tuple(default)))
        return tuple(default)


def _range(minimum: Optional[float], maximum: Optional[float]) -> str:
    if minimum is None:
        return 'at most %r' % (maximum,)
    if maximum is None:
        return 'at least %r' % (minimum,)
    return '%r to %r' % (minimum, maximum)
