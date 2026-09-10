"""Every input GLUT can report reaches a handler on the context.

GLUT delivers input by calling a function the program registered for it, so a
registration that does not happen is an input the engine never hears about --
a key that never arrives, a resize that leaves the viewport where it was, a
close button that does nothing.  Nothing fails when one is missed: the window
opens and renders, and only that one kind of event is silently absent.

Registering needs no window, so this asks the backend to do it against a
recording stand-in for GLUT.
"""
import pytest

pytest.importorskip('OpenGL.GLUT')

from OpenGLContext import glutcontext                     # noqa: E402
from OpenGLContext.glutcontext import GLUTContext         # noqa: E402

#: The registration call for each kind of input, and the handler it must be
#: given.  A name missing from here is one nothing holds the backend to.
REGISTRATIONS = (
    ('glutReshapeFunc', 'OnResize'),
    ('glutDisplayFunc', 'OnRedisplay'),
    ('glutKeyboardFunc', 'glutOnCharacter'),
    ('glutKeyboardUpFunc', 'glutOnKeyUp'),
    ('glutSpecialFunc', 'glutOnKeyDown'),
    ('glutSpecialUpFunc', 'glutOnKeyUp'),
    ('glutMouseFunc', 'glutOnMouseButton'),
    ('glutMotionFunc', 'glutOnMouseMove'),
    ('glutPassiveMotionFunc', 'glutOnMouseMove'),
    ('glutEntryFunc', 'glutOnEntry'),
)


@pytest.fixture
def registered(monkeypatch):
    """Ask a context to register its callbacks; answer what GLUT was told."""
    told = {}

    def recorder(name):
        def record(handler):
            told[name] = handler
        return record

    for name, _handler in REGISTRATIONS:
        monkeypatch.setattr(glutcontext, name, recorder(name))
    monkeypatch.setattr(glutcontext, 'glutSetWindow', lambda windowID: None)

    context = GLUTContext.__new__(GLUTContext)
    context.windowID = 1
    context.setupCallbacks()
    return context, told


@pytest.mark.parametrize('name,handler', REGISTRATIONS,
                         ids=[entry[0] for entry in REGISTRATIONS])
def test_the_callback_is_registered(registered, name, handler):
    context, told = registered
    assert name in told, '%s was never registered' % (name,)
    assert told[name] == getattr(context, handler)


def test_a_context_whose_window_has_gone_registers_nothing(monkeypatch):
    """`releaseWindow` clears the id, and GLUT has no window to name then."""
    named = []
    monkeypatch.setattr(glutcontext, 'glutSetWindow', lambda windowID: named.append(windowID))

    context = GLUTContext.__new__(GLUTContext)
    context.windowID = None
    context.setupCallbacks()
    assert named == []
