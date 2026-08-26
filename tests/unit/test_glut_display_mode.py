"""The GLUT display mode a default context asks for.

Every field of :class:`~OpenGLContext.contextdefinition.ContextDefinition`
uses -1 for "choose the default", and for the optional buffers the default the
other three backends take is *not to ask*: GLFW, pygame and wx all read
``accumulationBuffer > -1`` before they request one.  GLUT asking for an
accumulation buffer nobody requested costs the whole backend on a driver that
publishes no accumulation-buffer framebuffer config -- freeglut finds no
matching config and aborts the process before any window exists, under either
profile.
"""
import pytest

pytest.importorskip('OpenGL.GLUT')

from OpenGL.GLUT import (
    GLUT_ACCUM, GLUT_DEPTH, GLUT_DOUBLE, GLUT_RGB, GLUT_STENCIL,
)

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.glutcontext import GLUTContext


def flags(**named):
    return GLUTContext.glutFlagsFromDefinition(ContextDefinition(**named))


def test_a_default_context_asks_for_no_accumulation_buffer():
    assert not (flags() & GLUT_ACCUM)


def test_asking_for_one_still_gets_one():
    assert flags(accumulationBuffer=16) & GLUT_ACCUM


def test_asking_for_none_explicitly_gets_none():
    assert not (flags(accumulationBuffer=0) & GLUT_ACCUM)


def test_the_buffers_a_default_context_does_want_are_untouched():
    default = flags()
    for bit in (GLUT_DOUBLE, GLUT_DEPTH, GLUT_RGB, GLUT_STENCIL):
        assert default & bit == bit


def test_a_compatibility_context_is_asked_for_by_name():
    """GLUT names the profile it wants, as the other backends do.

    A version hint with no profile hint leaves the profile to the driver, which
    for GL 3.2 and above may answer with a core context -- so a request for the
    fixed-function pipeline has to say so rather than say nothing.
    """
    import inspect
    source = inspect.getsource(GLUTContext.__init__)
    assert 'GLUT_COMPATIBILITY_PROFILE' in source
