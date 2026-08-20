"""The randomness a session starts from, so the session can be run again.

A game whose world, loot, weapon spread or bot decisions come out of a random
number generator does not replay from its input alone: the same keys pressed
against a different sequence of numbers give a different game.  So a session has
a **seed**, this module owns it, and everything in the engine that would
otherwise have drawn from nowhere in particular draws from a stream derived from
it.

Three things follow from one number:

- ``OPENGLCONTEXT_SEED=4242`` fixes a whole session, including the ordinary
  :mod:`random` and :func:`numpy.random` generators a game reaches for without
  thinking about it.  That is a reproducible run for a bug report, a
  regression test or a level everyone can compare.
- :func:`generator` and :func:`randomizer` hand out **named streams** derived
  from the seed.  Two subsystems drawing from differently-named streams cannot
  disturb each other's sequence, so adding a third does not change what the
  first two produce -- which is what makes a seeded world stay the same world
  as the engine grows.
- :mod:`OpenGLContext.telemetry` records the seed, and a replay puts it back.

**Asking for a seed is what seeds the ordinary generators.**  Left alone, this
module chooses a session seed for its own streams and does not touch
:mod:`random` or :mod:`numpy.random` at all: a library that reseeded the
process's generators behind its caller's back would silently undo an
application's own ``random.seed(...)``.  A recording therefore changes nothing
about a session -- it captures where those generators had got to
(:func:`capture`) instead, and a replay puts them back.
"""

from __future__ import annotations

import logging
import os
import random
import zlib
from typing import Any, Dict, Optional

import numpy as np

log = logging.getLogger(__name__)

__all__ = ['SEED_ENV', 'capture', 'forget', 'generator', 'randomizer',
           'reseed', 'restore', 'seed']

#: Fix this session's randomness. An integer; anything else is a warning and a
#: seed of the session's own choosing.
SEED_ENV = 'OPENGLCONTEXT_SEED'

#: Seeds are 64-bit, which is small enough to read out over a telephone and
#: large enough that two sessions will not collide.
SEED_BITS = 64

_seed: Optional[int] = None
_generators: Dict[str, Any] = {}
_randomizers: Dict[str, random.Random] = {}


# -- the seed ---------------------------------------------------------------

def seed() -> int:
    """This session's seed, chosen on first use.

    From :data:`SEED_ENV` when it names one -- and naming one also seeds the
    process's ordinary generators, because a caller asking for a reproducible
    session means all of it -- otherwise from the system's entropy, leaving
    those generators exactly as they were.
    """
    global _seed
    if _seed is None:
        asked = _configured()
        if asked is None:
            _seed = _fresh()
            _clearStreams()
        else:
            return reseed(asked)
    return _seed


def reseed(value: Optional[int] = None) -> int:
    """Start this session's randomness from ``value``, and answer it.

    ``None`` for a seed of the system's choosing.  Unlike :func:`seed` this
    always applies: the process's :mod:`random` and :func:`numpy.random`
    generators are seeded from it, and every named stream begins again.  It is
    what a replay calls, and what a game with a "new world from this number"
    field calls.
    """
    global _seed
    _seed = _fresh() if value is None else int(value)
    _clearStreams()
    random.seed(_seed)
    # numpy's legacy global takes 32 bits, so it is given a stream of its own
    # rather than the low half of the seed -- two seeds differing only above
    # bit 32 would otherwise give numpy the same sequence.
    np.random.seed(_stream_seed('numpy-global') % (2 ** 32))
    return _seed


def forget() -> None:
    """Forget this session's seed, so the next call chooses again.

    For a process that starts a second session, and for tests.  Leaves the
    process's generators wherever they are: forgetting which number a sequence
    came from does not un-draw it.
    """
    global _seed
    _seed = None
    _clearStreams()


# -- named streams ----------------------------------------------------------

def generator(stream: str = '') -> Any:
    """The :class:`numpy.random.Generator` for a named stream.

    One generator per name, kept, so a caller asking again gets *what comes
    next* rather than the beginning again -- a bot picking somewhere to walk
    every few seconds would otherwise pick the same place for ever.
    """
    found = _generators.get(stream)
    if found is None:
        found = _generators[stream] = np.random.default_rng(
            np.random.SeedSequence([seed(), _key(stream)]))
    return found


def randomizer(stream: str = '') -> random.Random:
    """The :class:`random.Random` for a named stream.

    The same idea as :func:`generator`, for code that wants the standard
    library's flavour: a choice from a list, a shuffle, one float.
    """
    found = _randomizers.get(stream)
    if found is None:
        found = _randomizers[stream] = random.Random(_stream_seed(stream))
    return found


# -- recording it -----------------------------------------------------------

def capture() -> Dict[str, Any]:
    """This session's seed and where the ordinary generators have got to.

    The seed alone describes a session that began from one.  It does not
    describe a game that seeded itself, or one that has been drawing numbers
    since before the recording started -- for those, what matters is the state
    the generators hold, which is what :func:`restore` puts back.

    Plain data throughout, so it goes into a journal as it stands.
    """
    found: Dict[str, Any] = {'seed': seed()}
    try:
        version, keys, gauss = random.getstate()
        found['random'] = [version, list(keys), gauss]
    except (TypeError, ValueError):             # a generator we do not know
        log.debug('could not capture the state of random', exc_info=True)
    try:
        name, keys, position, has_gauss, cached = np.random.get_state()
        found['numpy'] = [name, [int(value) for value in keys], int(position),
                          int(has_gauss), float(cached)]
    except (TypeError, ValueError):
        log.debug('could not capture the state of numpy.random', exc_info=True)
    return found


def restore(record: Dict[str, Any]) -> None:
    """Put back what :func:`capture` recorded.

    Each half independently, and a half that will not go back is a debug line
    rather than an error: a journal written by another Python, or one cut off
    part-way through, still has the rest of the session in it, and a replay
    that reproduces most of a failure beats one that refuses to start.
    """
    global _seed
    if 'seed' in record:
        try:
            _seed = int(record['seed'])
            _clearStreams()
        except (TypeError, ValueError):
            log.debug('the recorded seed is not a number: %r', record['seed'])
    state = record.get('random')
    if state:
        try:
            version, keys, gauss = state
            random.setstate((int(version), tuple(int(key) for key in keys),
                             gauss))
        except (TypeError, ValueError) as error:
            log.debug('could not restore the state of random (%s)', error)
    state = record.get('numpy')
    if state:
        try:
            name, keys, position, has_gauss, cached = state
            np.random.set_state((name, np.array(keys, dtype=np.uint32),
                                 int(position), int(has_gauss), float(cached)))
        except (TypeError, ValueError) as error:
            log.debug('could not restore the state of numpy.random (%s)', error)


# -- internals --------------------------------------------------------------

def _fresh() -> int:
    """A seed from the system's entropy."""
    return int.from_bytes(os.urandom(SEED_BITS // 8), 'big')


def _configured() -> Optional[int]:
    """The seed the environment asks for, or None.

    A value that is not a number is a warning and a seed of our own: a mistyped
    diagnostic switch must not be the reason a game will not start.
    """
    asked = os.environ.get(SEED_ENV)
    if not asked:
        return None
    try:
        return int(asked, 0)
    except ValueError:
        log.warning('%s=%r is not a number; this session will choose its own '
                    'seed', SEED_ENV, asked)
        return None


def _key(stream: str) -> int:
    """A stream name as a number, the same one in every process.

    ``hash()`` is salted per process and would make a named stream reproducible
    only within one run, which is the opposite of the point.
    """
    return zlib.crc32(stream.encode('utf-8'))


def _stream_seed(stream: str) -> int:
    """A seed for one named stream, derived from the session's."""
    return int(np.random.SeedSequence(
        [seed(), _key(stream)]).generate_state(2, dtype=np.uint64).astype(
            object).prod() % (2 ** SEED_BITS))


def _clearStreams() -> None:
    _generators.clear()
    _randomizers.clear()
