"""The scatter a ground cover's child process is built from, for ``test_cover_process``."""
import time

import numpy as np

from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.vegetation.cover import CoverSpecies, GroundCover
from OpenGLContext.scenegraph.vegetation.coverprocess import CoverScatterMaker

EXTENT = 2048.0


def species():
    return [CoverSpecies(name='grass', card='grass.png', density=2.0),
            CoverSpecies(name='fern', card='fern.png', density=0.5)]


def cover(**named):
    """The cover a test makes both in its own process and in a child."""
    field = HeightField(np.zeros((65, 65)), EXTENT, 10.0)
    return GroundCover(field, species(), clump_radius=30.0, card_radius=90.0, **named)


def maker():
    return CoverScatterMaker(cover())


def broken():
    raise RuntimeError('cannot build the scatter')


class Faulty:
    """Starts, and answers nothing."""

    def make(self, key):
        if key[0] == 'process':
            return 0
        raise ValueError('no scatter today')


def faulty():
    return Faulty()


class Slow:
    """Takes its time over ground to make ahead, as a long road does."""

    def __init__(self):
        self.inner = CoverScatterMaker(cover())

    def make(self, key):
        if key[0] == 'warm':
            time.sleep(0.15 * (len(key[1]) if isinstance(key[1], list) else 1))
        return self.inner.make(key)


def slow():
    return Slow()
