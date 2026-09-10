"""What the wxPython backend makes of a wx mouse event.

OpenGLContext numbers mouse buttons in the X11 order -- 0 left, 1 right, 2
middle, with the wheel as 3 and 4 -- because that is the order the wheel
buttons force (see :mod:`OpenGLContext.events.mouseevents`).  wx numbers them
left, middle, right, so every wx event has to be translated, and a press and a
drag with the same finger have to come out as the same number: a handler
registered for ``buttons=(1,)`` is asking about the button whose press reports
``1``.

wxPython is not installed in every environment this suite runs in, and none of
what is under test is wx's own behaviour -- it is the translation table beside
it -- so the toolkit is stood in for by a module of its documented constants.
"""

import sys
import types

import pytest

#: wx's own numbering, from ``wx.MouseEvent``.
WX_LEFT, WX_MIDDLE, WX_RIGHT, WX_NONE = 1, 2, 3, 0


def _fake_wx():
    """A module offering wx's constants, and a distinct value for any other.

    ``wxevents`` builds its key table out of several dozen ``wx.WXK_*``
    constants at import time and only ever uses them as dictionary keys, so any
    distinct value will do.  They start above 255 so that they cannot collide
    with the character codes the table fills in around them.
    """
    module = types.ModuleType('wx')
    module.MOUSE_BTN_NONE = WX_NONE
    module.MOUSE_BTN_LEFT = WX_LEFT
    module.MOUSE_BTN_MIDDLE = WX_MIDDLE
    module.MOUSE_BTN_RIGHT = WX_RIGHT
    module.MOUSE_WHEEL_VERTICAL = 0
    made = {}

    def __getattr__(name):
        return made.setdefault(name, 256 + len(made))
    module.__getattr__ = __getattr__
    return module


@pytest.fixture
def wxevents(monkeypatch):
    """``OpenGLContext.events.wxevents``, imported against the stand-in.

    The module is taken back out again afterwards -- from the package object as
    well as from ``sys.modules``, since the import puts it in both -- so that
    nothing else in the run reaches a module built on a wx that is not there.
    """
    import OpenGLContext.events as package
    monkeypatch.setitem(sys.modules, 'wx', _fake_wx())
    monkeypatch.delitem(sys.modules, 'OpenGLContext.events.wxevents',
                        raising=False)
    from OpenGLContext.events import wxevents as module
    yield module
    sys.modules.pop('OpenGLContext.events.wxevents', None)
    if getattr(package, 'wxevents', None) is module:
        del package.wxevents


class Canvas(object):
    """The little of a wx context the event classes reach for."""

    def getViewPort(self):
        return (400, 300)


class MouseEvent(object):
    """A wx mouse event, with the accessors the translation calls.

    ``Button`` is a property in wxPython Phoenix -- the button whose state this
    event reports, or ``MOUSE_BTN_NONE`` for a movement.
    """

    def __init__(self, button=WX_NONE, down=False, held=()):
        self._button = button
        self._down = down
        self._held = frozenset(held)

    @property
    def Button(self):
        return self._button

    def GetButton(self):
        return self._button

    def ButtonDown(self, but=None):
        return self._down and (but is None or but == self._button)

    def ButtonIsDown(self, but):
        return but in self._held

    def LeftIsDown(self):
        return WX_LEFT in self._held

    def MiddleIsDown(self):
        return WX_MIDDLE in self._held

    def RightIsDown(self):
        return WX_RIGHT in self._held

    def GetX(self):
        return 10

    def GetY(self):
        return 20

    def ShiftDown(self):
        return False

    def ControlDown(self):
        return False

    def AltDown(self):
        return False


class KeyEvent(object):
    """A wx key event, with the accessors the translation calls."""

    def __init__(self, code):
        self._code = code

    def GetKeyCode(self):
        return self._code

    def ShiftDown(self):
        return False

    def ControlDown(self):
        return False

    def AltDown(self):
        return False


PRESSES = [
    ('left', WX_LEFT, 0),
    ('right', WX_RIGHT, 1),
    ('middle', WX_MIDDLE, 2),
]


class TestOneFingerIsOneNumber:
    """A press and a drag with the same button must agree about which it is."""

    @pytest.mark.parametrize('name,wxButton,expected',
                             PRESSES, ids=[case[0] for case in PRESSES])
    def test_a_press_reports_the_x11_number(self, wxevents, name, wxButton,
                                            expected):
        event = wxevents.wxMouseButtonEvent(
            Canvas(), MouseEvent(button=wxButton, down=True, held=(wxButton,)))
        assert event.button == expected
        assert event.state == 1

    @pytest.mark.parametrize('name,wxButton,expected',
                             PRESSES, ids=[case[0] for case in PRESSES])
    def test_a_drag_reports_the_number_its_press_did(self, wxevents, name,
                                                    wxButton, expected):
        move = wxevents.wxMouseMoveEvent(Canvas(),
                                         MouseEvent(held=(wxButton,)))
        assert move.getButtons() == (expected,)

    def test_a_two_button_drag_is_in_ascending_order(self, wxevents):
        move = wxevents.wxMouseMoveEvent(
            Canvas(), MouseEvent(held=(WX_LEFT, WX_RIGHT)))
        assert move.getButtons() == (0, 1)


class TestAnEventNamingNoButton:
    """wx reports ``MOUSE_BTN_NONE`` for anything that is not a button change."""

    def test_it_resolves_without_raising(self, wxevents):
        event = wxevents.wxMouseButtonEvent(Canvas(), MouseEvent())
        assert event.button == -1
        assert event.state == 0

    def test_a_release_reports_the_button_and_the_up_state(self, wxevents):
        event = wxevents.wxMouseButtonEvent(
            Canvas(), MouseEvent(button=WX_RIGHT, down=False))
        assert event.button == 1
        assert event.state == 0


class TestAKeyTheTableDoesNotName:
    """wx has more key codes than the table lists -- keypad Enter among them.

    A key with no name of its own still has to be told apart from the next one,
    or every unnamed key answers to one binding.  GLFW spells the fallback
    ``<unknown-N>``, and this is the same key travelling the same handlers.
    """

    def test_it_is_named_by_its_code(self, wxevents):
        code = 4242
        assert code not in wxevents.keyboardMapping
        event = wxevents.wxKeyboardEvent(Canvas(), KeyEvent(code), 1)
        assert event.name == '<unknown-4242>'

    def test_two_of_them_are_not_the_same_key(self, wxevents):
        first = wxevents.wxKeyboardEvent(Canvas(), KeyEvent(4242), 1)
        second = wxevents.wxKeyboardEvent(Canvas(), KeyEvent(4243), 1)
        assert first.getKey() != second.getKey()

    def test_a_named_key_keeps_its_name(self, wxevents):
        event = wxevents.wxKeyboardEvent(Canvas(), KeyEvent(ord('a')), 1)
        assert event.name == 'a'

    def test_a_synthetic_release_is_named_the_same_way(self, wxevents):
        """The release focus loss never delivered has to match its press."""
        sent = []

        class Canvas_(wxevents.EventHandlerMixin):
            def ProcessEvent(self, event):
                sent.append(event)

        Canvas_().emitKey(4242, 0, (0, 0, 0))
        assert [event.name for event in sent] == ['<unknown-4242>']


def test_the_pick_point_counts_up_from_the_bottom(wxevents):
    event = wxevents.wxMouseButtonEvent(
        Canvas(), MouseEvent(button=WX_LEFT, down=True))
    assert event.getPickPoint() == (10, 280)
