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

A JSON document is read as a :data:`JSONObject`, a ``Mapping[str, object]``:
every reader of a document (:func:`parse_object`, and the loaders' entry
points built on it) answers one, so a value taken out of it is an ``object``
that the type checker refuses to use as a number, a string or a table until it
is narrowed. :class:`DocumentValues` narrows with a report
(:meth:`~DocumentValues.mapping`, :meth:`~DocumentValues.array`,
:meth:`~DocumentValues.text`, :meth:`~DocumentValues.texts` and the numbers
above); :func:`require_object`,
:func:`require_array`, :func:`require_number`, :func:`require_numbers`,
:func:`require_text`, :func:`require_whole`, :func:`require_index` and
:func:`require_item` narrow the parts a document cannot be read without, and raise :class:`DocumentError` where one is
missing or malformed::

    tileset = parse_object(data, 'tileset.json')
    root = require_object(tileset.get('root'), 'tileset root')
    children = values.array(root.get('children'), 'tile children')
"""
from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Optional, TypeGuard

log = logging.getLogger(__name__)

__all__ = [
    'DocumentValues', 'DocumentError', 'JSONObject', 'JSONArray', 'bounded',
    'parse_object', 'require_object', 'require_array', 'require_numbers',
    'require_number', 'require_text', 'require_whole', 'require_index',
    'require_item',
    'TRUE', 'FALSE',
]

#: A JSON object as a document reader answers it. Its values are ``object``,
#: so each is narrowed (:class:`DocumentValues`, :func:`require_object`)
#: before it is used.
JSONObject = Mapping[str, object]

#: A JSON array as :meth:`DocumentValues.array` answers it.
JSONArray = Sequence[object]

_EMPTY: JSONObject = {}


class DocumentError(ValueError):
    """A document lacks a part it cannot be read without, or is not JSON at all."""

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


def parse_object(data: str | bytes, what: str) -> JSONObject:
    """``data``, JSON text whose top level is an object, as a :data:`JSONObject`.

    Raises :class:`DocumentError` where ``data`` is not JSON (or not UTF-8),
    or its top level is not an object.
    """
    try:
        parsed = json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise DocumentError('%s is not JSON: %s' % (what, error)) from error
    if not _is_object(parsed):
        raise DocumentError('%s is not a JSON object' % (what,))
    return parsed


def require_object(raw: object, what: str) -> JSONObject:
    """``raw``, which must be a JSON object, or :class:`DocumentError`."""
    if not _is_object(raw):
        raise DocumentError('%s is %r, which is not an object' % (what, raw))
    return raw


def require_array(raw: object, what: str) -> JSONArray:
    """``raw``, which must be a JSON array, or :class:`DocumentError`."""
    if not isinstance(raw, (list, tuple)):
        raise DocumentError('%s is %r, which is not an array' % (what, raw))
    return raw


def require_numbers(raw: object, what: str, length: int) -> tuple[float, ...]:
    """``raw`` as ``length`` finite floats, or :class:`DocumentError`."""
    numbers = _numbers(raw, length)
    if numbers is None:
        raise DocumentError('%s is %r, which is not %d finite numbers'
                            % (what, raw, length))
    return numbers


def require_number(raw: object, what: str) -> float:
    """``raw`` as a finite float, or :class:`DocumentError`."""
    number = _as_float(raw)
    if number is None:
        raise DocumentError('%s is %r, which is not a finite number' % (what, raw))
    return number


def require_text(raw: object, what: str) -> str:
    """``raw``, which must be a string, or :class:`DocumentError`."""
    if not isinstance(raw, str):
        raise DocumentError('%s is %r, which is not a string' % (what, raw))
    return raw


def require_whole(raw: object, what: str) -> int:
    """``raw`` as a whole number, or :class:`DocumentError`."""
    number = require_number(raw, what)
    if not number.is_integer():
        raise DocumentError('%s is %r, which is not a whole number' % (what, raw))
    return int(number)


def require_index(raw: object, what: str) -> int:
    """``raw`` as an index or an offset: a whole number, not negative."""
    number = require_whole(raw, what)
    if number < 0:
        raise DocumentError('%s is %r, which is negative' % (what, raw))
    return number


def require_item(document: JSONObject, table: str, index: int) -> JSONObject:
    """Object ``index`` of the document's array ``table`` (a glTF ``accessors``,
    say), or :class:`DocumentError` where there is no such object."""
    items = require_array(document.get(table), table)
    if index >= len(items):
        raise DocumentError('%s %d is named and there are %d'
                            % (table, index, len(items)))
    return require_object(items[index], '%s %d' % (table, index))


def _is_object(raw: object) -> TypeGuard[JSONObject]:
    return isinstance(raw, Mapping) and all(isinstance(key, str) for key in raw)


def _numbers(raw: object, length: int) -> Optional[tuple[float, ...]]:
    """``raw`` as ``length`` finite floats, or None."""
    if not isinstance(raw, (list, tuple)) or len(raw) != length:
        return None
    numbers = [number for number in map(_as_float, raw) if number is not None]
    return tuple(numbers) if len(numbers) == length else None


def bounded(value: object, default: float, minimum: Optional[float] = None,
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
        self._said: set[str] = set()

    def warn(self, message: str) -> None:
        """Report ``message``, once for this reader."""
        if message in self._said:
            return
        self._said.add(message)
        if self._warn is not None:
            self._warn(message)
        else:
            self._logger.warning('%s', message)

    def number(self, raw: object, default: float, what: str, *,
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

    def integer(self, raw: object, default: int, what: str, *,
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

    def flag(self, raw: object, default: bool, what: str) -> bool:
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

    def choice(self, raw: object, default: str, what: str,
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

    def vector(self, raw: object, default: Sequence[float], what: str,
               length: int = 3) -> tuple[float, ...]:
        """``raw`` as ``length`` finite floats, or ``default``."""
        if raw is None:
            return tuple(default)
        numbers = _numbers(raw, length)
        if numbers is not None:
            return numbers
        self.warn('%s is %r, which is not %d finite numbers; it is taken as %r'
                  % (what, raw, length, tuple(default)))
        return tuple(default)


    def mapping(self, raw: object, what: str) -> JSONObject:
        """``raw`` as a JSON object, or an empty one.

        None is an absent object and is empty without a report; anything else
        that is not an object with string keys is reported.
        """
        if raw is None:
            return _EMPTY
        if _is_object(raw):
            return raw
        self.warn('%s is %r, which is not an object; it is taken as empty'
                  % (what, raw))
        return _EMPTY

    def array(self, raw: object, what: str) -> JSONArray:
        """``raw`` as a JSON array, or an empty one; None is empty without a report."""
        if raw is None:
            return ()
        if isinstance(raw, (list, tuple)):
            return raw
        self.warn('%s is %r, which is not an array; it is taken as empty'
                  % (what, raw))
        return ()

    def text(self, raw: object, default: str, what: str) -> str:
        """``raw`` as a string, or ``default``; None is ``default`` without a report."""
        if raw is None:
            return default
        if isinstance(raw, str):
            return raw
        self.warn('%s is %r, which is not a string; it is taken as %r'
                  % (what, raw, default))
        return default


    def texts(self, raw: object, default: Iterable[str], what: str) -> list[str]:
        """``raw`` as a list of strings, or ``default``; None is ``default`` without a report."""
        if raw is None:
            return list(default)
        if isinstance(raw, (list, tuple)) and all(isinstance(item, str) for item in raw):
            return [str(item) for item in raw]
        self.warn('%s is %r, which is not a list of strings; it is taken as %r'
                  % (what, raw, list(default)))
        return list(default)


def _range(minimum: Optional[float], maximum: Optional[float]) -> str:
    if minimum is None:
        return 'at most %r' % (maximum,)
    if maximum is None:
        return 'at least %r' % (minimum,)
    return '%r to %r' % (minimum, maximum)
