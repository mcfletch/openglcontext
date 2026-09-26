"""What the pygame window system asks SDL for, from a context definition.

Two vocabularies meet in :mod:`OpenGLContext.windowsystem.pygame`: SDL's GL
attributes, which are small indices into the attribute table, and OpenGL's own
enumerants.  Several names appear in both -- ``GL_STEREO`` is 12 to SDL and
0x0C33 to OpenGL -- so which one a request carries decides whether SDL
recognises it at all.

The counterpart for GLUT is `test_glut_display_mode.py`.
"""
import pytest

pygame = pytest.importorskip('pygame')

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.windowsystem.pygame import setGLAttributes, windowFlags


@pytest.fixture
def display(monkeypatch):
    """An initialised SDL video subsystem; ``gl_set_attribute`` needs one.

    The dummy driver, because what is under test is which attributes SDL is
    asked for rather than what a window looks like.  It validates an attribute
    name exactly as a real driver does, and it needs no display to attach to.
    """
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    pygame.display.init()
    yield
    pygame.display.quit()


@pytest.mark.usefixtures('display')
def test_the_buffers_a_definition_asks_for_reach_sdl(monkeypatch):
    """Every attribute this window system sets is one SDL knows.

    An attribute SDL does not recognise raises, so the window is never opened
    at all -- the definition's fields have to be spelled in SDL's vocabulary.
    """
    definition = ContextDefinition(
        depthBuffer=24, stencilBuffer=8, accumulationBuffer=16,
        multisampleBuffer=1, multisampleSamples=4, stereo=1,
    )
    asked = {}
    real = pygame.display.gl_set_attribute

    def passing_through(attribute, value):
        real(attribute, value)                   # SDL still validates the name
        asked[attribute] = value
    monkeypatch.setattr(pygame.display, 'gl_set_attribute', passing_through)
    setGLAttributes(definition)
    assert asked[pygame.GL_DEPTH_SIZE] == 24
    assert asked[pygame.GL_STENCIL_SIZE] == 8
    for channel in (pygame.GL_ACCUM_RED_SIZE, pygame.GL_ACCUM_GREEN_SIZE,
                    pygame.GL_ACCUM_BLUE_SIZE, pygame.GL_ACCUM_ALPHA_SIZE):
        assert asked[channel] == 16
    assert asked[pygame.GL_MULTISAMPLEBUFFERS] == 1
    assert asked[pygame.GL_MULTISAMPLESAMPLES] == 4
    assert asked[pygame.GL_STEREO] == 1


@pytest.mark.usefixtures('display')
def test_a_default_definition_asks_for_no_optional_buffers():
    """-1 means "choose", so nothing is requested for those buffers."""
    asked = []
    original = pygame.display.gl_set_attribute
    pygame.display.gl_set_attribute = lambda attribute, _value: asked.append(attribute)
    try:
        setGLAttributes(ContextDefinition())
    finally:
        pygame.display.gl_set_attribute = original
    assert pygame.GL_ACCUM_RED_SIZE not in asked
    assert pygame.GL_STEREO not in asked
    assert pygame.GL_MULTISAMPLESAMPLES not in asked


@pytest.mark.usefixtures('display')
def test_a_window_is_resizable_and_double_buffered():
    flags = windowFlags(ContextDefinition())
    assert flags & pygame.RESIZABLE
    assert flags & pygame.DOUBLEBUF


@pytest.mark.usefixtures('display')
def test_single_buffering_is_asked_for_by_leaving_it_out():
    flags = windowFlags(ContextDefinition(doubleBuffer=False))
    assert not (flags & pygame.DOUBLEBUF)
    assert flags & pygame.RESIZABLE
