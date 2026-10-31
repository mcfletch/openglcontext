"""Every input GLUT can report reaches a handler.

GLUT delivers input by calling a function the program registered for it, so a
registration that does not happen is an input the engine never hears about --
a key that never arrives, a resize that leaves the viewport where it was, a
close button that does nothing.  Nothing fails when one is missed: the window
opens and renders, and only that one kind of event is silently absent.

Registering needs no window, so this asks the GLUT window system to do it
against a recording stand-in for GLUT.
"""
import pytest

pytest.importorskip('OpenGL.GLUT')

from OpenGLContext.context import Context
from OpenGLContext.windowsystem import glut as glutwindowsystem
from OpenGLContext.windowsystem.glut import GLUTWindowSystem

#: The registration call for each kind of input, what owns the handler it must
#: be given, and the handler's name.  A name missing from here is one nothing
#: holds the window system to.
REGISTRATIONS = (
    ('glutReshapeFunc', 'context', 'OnResize'),
    ('glutDisplayFunc', 'windowsystem', 'onDisplay'),
    ('glutKeyboardFunc', 'windowsystem', 'onCharacter'),
    ('glutKeyboardUpFunc', 'windowsystem', 'onKeyUp'),
    ('glutSpecialFunc', 'windowsystem', 'onKeyDown'),
    ('glutSpecialUpFunc', 'windowsystem', 'onKeyUp'),
    ('glutMouseFunc', 'windowsystem', 'onMouseButton'),
    ('glutMotionFunc', 'windowsystem', 'onMouseMove'),
    ('glutPassiveMotionFunc', 'windowsystem', 'onMouseMove'),
    ('glutEntryFunc', 'windowsystem', 'onEntry'),
)


def _windowSystem(window):
    context = Context.__new__(Context)
    system = GLUTWindowSystem(context)
    context.windowsystem = system
    system.window = window
    return system


@pytest.fixture
def registered(monkeypatch):
    """Ask a window system to bind its callbacks; answer what GLUT was told."""
    told = {}

    def recorder(name):
        def record(handler):
            told[name] = handler
        return record

    for name, _owner, _handler in REGISTRATIONS:
        monkeypatch.setattr(glutwindowsystem, name, recorder(name))
    monkeypatch.setattr(glutwindowsystem, 'glutSetWindow', lambda _window: None)

    system = _windowSystem(1)
    system.bindCallbacks()
    return system, told


@pytest.mark.parametrize('name,owner,handler', REGISTRATIONS,
                         ids=[entry[0] for entry in REGISTRATIONS])
def test_the_callback_is_registered(registered, name, owner, handler):
    system, told = registered
    target = system.context if owner == 'context' else system
    assert name in told, '%s was never registered' % (name,)
    assert told[name] == getattr(target, handler)


def test_a_window_system_whose_window_has_gone_registers_nothing(monkeypatch):
    """`release` clears the window, and GLUT has no window to name then."""
    named = []
    monkeypatch.setattr(glutwindowsystem, 'glutSetWindow', lambda window: named.append(window))

    system = _windowSystem(None)
    system.bindCallbacks()
    assert named == []


def test_the_world_menu_lists_the_worlds_and_urls_it_is_given(monkeypatch, tmp_path):
    entries = []
    monkeypatch.setattr(glutwindowsystem, 'glutCreateMenu', lambda handler: len(entries))
    monkeypatch.setattr(glutwindowsystem, 'glutAddMenuEntry',
                        lambda label, value: entries.append((label, value)))
    monkeypatch.setattr(glutwindowsystem, 'glutAddSubMenu', lambda label, menu: None)
    monkeypatch.setattr(glutwindowsystem, 'glutAttachMenu', lambda button: None)
    worlds = tmp_path / 'wrls'
    worlds.mkdir()
    (worlds / 'box.wrl').write_text('#VRML V2.0 utf8\n', encoding='utf-8')
    urls = tmp_path / 'set.txt'
    urls.write_text('# a comment\nhttp://example.com/a.wrl\n\n', encoding='utf-8')

    system = _windowSystem(1)
    system.createWorldMenu(str(worlds), str(urls))
    assert system.worldPaths == [str(worlds / 'box.wrl'), 'http://example.com/a.wrl']
    assert [label for label, _value in entries] == ['box.wrl', 'http://example.com/a.wrl']
    system.createWorldMenu(str(tmp_path / 'nowhere'))
    assert system.worldPaths == []
