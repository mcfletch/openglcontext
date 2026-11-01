#! /usr/bin/env python
"""``oglc-gait`` -- how fast a model's locomotion clips carry it.

A walk or run clip is authored for one ground speed, and a character played at
any other speed slides its feet. This measures the speed of each locomotion
clip in a glTF file, the length of its cycle and the times its feet land, with
:func:`~OpenGLContext.character.gaitmeasure.measure`::

    oglc-gait marine.glb
    oglc-gait marine.glb --clips Walk_Loop,Jog_Fwd_Loop
    oglc-gait marine.glb --all

Speeds are in the model's own units a second at playback rate 1.0. The default
is the clips :meth:`~OpenGLContext.character.locomotion.ClipMap.guess` gives to
the walk, run, sprint, crouch-walk and swim roles; ``--all`` measures every
clip. The table is followed by a ``ClipMap`` built from the numbers, to paste
into a program, and by the roles and clips the names left unmatched.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from OpenGLContext.character import CharacterModel
from OpenGLContext.character.gaitmeasure import Stride, measure
from OpenGLContext.character.locomotion import ClipMap

__all__ = ['main']

#: The roles whose clips carry a character along the ground.
LOCOMOTION_ROLES = ('walk', 'run', 'sprint', 'crouch_walk', 'swim')


def build_parser(prog: str = 'oglc-gait') -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog, description='Measure how fast a model\'s locomotion clips '
        'carry it, and when their feet land.')
    parser.add_argument('source', help='a .glb or .gltf character')
    parser.add_argument('--clips', help='comma-separated clips to measure')
    parser.add_argument('--all', action='store_true',
                        help='measure every clip')
    parser.add_argument('--samples', type=int, default=64,
                        help='poses sampled over each clip (default 64)')
    return parser


def _row(found: Stride) -> str:
    contacts = ', '.join('%s %.2f' % (foot, at) for foot, at in found.contacts)
    return '%-24s %8.2f %8.3f  %-4s  %s' % (
        found.clip, found.speed, found.duration,
        'yes' if found.root_motion else 'no', contacts)


def _paste(guessed: ClipMap, found: dict[str, Stride]) -> str:
    """A ``ClipMap(...)`` for the roles that matched, with the measured numbers."""
    parts = []
    for role in ('idle', 'walk', 'run', 'sprint', 'crouch_idle', 'crouch_walk',
                 'jump_up', 'jump_down', 'land', 'slide', 'fall', 'swim',
                 'down', 'get_up', 'death'):
        spec = guessed.spec(role)
        if spec is None:
            continue
        measured = found.get(spec.clip)
        if measured is None or measured.speed <= 0.0:
            parts.append('%s=%r' % (role, spec.clip))
            continue
        contacts = ', '.join('(%r, %.3f)' % item for item in measured.contacts)
        parts.append('%s=ClipSpec(%r, speed=%.2f%s)' % (
            role, spec.clip, measured.speed,
            ', contacts=(%s)' % contacts if contacts else ''))
    return 'ClipMap(%s)' % ', '.join(parts)


def main(argv: Optional[list[str]] = None, prog: str = 'oglc-gait') -> int:
    options = build_parser(prog).parse_args(argv)
    try:
        model = CharacterModel.load(options.source)
    except (OSError, ValueError) as error:
        print('%s: %s: %s' % (prog, options.source, error), file=sys.stderr)
        return 2
    if model.humanoid is None:
        print('%s: %s has no humanoid skeleton to measure' % (
            prog, options.source), file=sys.stderr)
        return 2
    guessed = ClipMap.guess(model)
    if options.clips:
        names = options.clips.split(',')
    elif options.all:
        names = list(model.clips)
    else:
        names = [spec.clip for role in LOCOMOTION_ROLES
                 if (spec := guessed.spec(role)) is not None]
    absent = [name for name in names if name not in model.clips]
    if absent:
        print('%s: no clip %s in %s' % (prog, ', '.join(absent), options.source),
              file=sys.stderr)
        return 2
    found: dict[str, Any] = {}
    print('%-24s %8s %8s  %-4s  %s' % (
        'clip', 'm/s', 'cycle s', 'root', 'foot lands at (s)'))
    for name in dict.fromkeys(names):
        found[name] = measure(model, name, options.samples)
        print(_row(found[name]))
    print()
    print(_paste(guessed, found))
    if guessed.unmatched:
        print('no clip for: %s' % ', '.join(guessed.unmatched))
    if guessed.leftover:
        print('no role for: %s' % ', '.join(guessed.leftover))
    return 0


if __name__ == '__main__':   # pragma: no cover - the console script's entry
    sys.exit(main())
