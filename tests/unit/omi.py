"""The mark for tests of the parts of the engine still built on an omi_physics world.

omi_physics is the deprecated ``omi-physics`` extra (``pip install OpenGLContext[omi-physics]``),
installed in this workspace, so these tests run here; where it is not installed
they are skipped with the reason. The parts they test are listed in
``plans/NATIVE-PHYSICS.md``, "P5 as built", and leave with the omi engine.
"""
from __future__ import annotations

import importlib

import pytest


def have_omi() -> bool:
    """Whether omi_physics can be imported."""
    try:
        importlib.import_module('omi_physics')
    except ImportError:
        return False
    return True


#: Skips a test where omi_physics is not installed.
requires_omi = pytest.mark.skipif(not have_omi(), reason='omi_physics (the omi extra) is not installed')
