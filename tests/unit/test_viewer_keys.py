"""The keys the viewer binds, and which modifier each one wants.

A modifier is a three-tuple in the order **(shift, control, alt)**, and the two
that are not shift look identical at a glance. Ctrl+PageUp and Ctrl+PageDown --
the pair that steps along the shelf a model was chosen from -- asked for the
third slot, so they were bound to *Alt* and pressing Ctrl did nothing at all.

Nothing about that is visible at the call site, so the bindings are a table and
this drives real events through a real manager to see which method runs.
"""
import pytest

from OpenGLContext.events.keyboardevents import (
    KeyboardEvent, KeyboardEventManager,
)
from OpenGLContext.viewer.sceneviewer import CONTROL, NO_MODIFIERS, SceneViewerMixin


class _Viewer:
    """Records which bound method a keypress reached."""

    viewerKeys = SceneViewerMixin.viewerKeys

    def __init__(self):
        self.called = []
        for name in {binding.method for binding in self.viewerKeys}:
            setattr(self, name, self._recorder(name))

    def _recorder(self, name):
        def called(event):
            self.called.append(name)
        return called


@pytest.fixture
def keyboard():
    """A real manager with the viewer's real bindings on it."""
    viewer = _Viewer()
    manager = KeyboardEventManager()
    for binding in viewer.viewerKeys:
        manager.registerCallback(name=binding.name, state=binding.state,
                                 modifiers=binding.modifiers,
                                 function=getattr(viewer, binding.method))
    return manager, viewer


def _press(manager, name, modifiers=NO_MODIFIERS, state=0):
    """A key going up, which is when a discrete action fires."""
    event = KeyboardEvent()
    event.name = name
    event.state = state
    event.modifiers = modifiers
    manager.ProcessEvent(event)


class TestSteppingAlongTheShelf:
    """Ctrl with the page keys: the next model in the list this one came from."""

    def test_control_pagedown_goes_to_the_next_one(self, keyboard):
        manager, viewer = keyboard
        _press(manager, '<pagedown>', CONTROL)
        assert viewer.called == ['nextInLibrary']

    def test_control_pageup_goes_back(self, keyboard):
        manager, viewer = keyboard
        _press(manager, '<pageup>', CONTROL)
        assert viewer.called == ['previousInLibrary']

    def test_it_is_control_and_not_alt(self):
        """The whole bug: (shift, control, alt), and alt is not control."""
        assert CONTROL == (False, True, False)
        shelf = [binding for binding in SceneViewerMixin.viewerKeys
                 if binding.method.endswith('InLibrary')]
        assert shelf, 'nothing steps the shelf'
        for binding in shelf:
            assert binding.modifiers == CONTROL, binding.name


class TestTheScenesOwnCameras:
    """Bare page keys stay with the world: inside one scene that is what they mean."""

    def test_pagedown_is_the_next_camera(self, keyboard):
        manager, viewer = keyboard
        _press(manager, '<pagedown>')
        assert viewer.called == ['nextCamera']

    def test_pageup_is_the_previous_camera(self, keyboard):
        manager, viewer = keyboard
        _press(manager, '<pageup>')
        assert viewer.called == ['previousCamera']

    def test_control_does_not_also_move_the_camera(self, keyboard):
        """One key press, one action."""
        manager, viewer = keyboard
        _press(manager, '<pagedown>', CONTROL)
        assert 'nextCamera' not in viewer.called


class TestTheRestOfTheKeys:
    @pytest.mark.parametrize('name, method', [
        ('n', 'nextCamera'),
        ('p', 'previousCamera'),
        ('k', 'toggleAnimation'),
        (']', 'nextAnimation'),
        ('[', 'previousAnimation'),
        ('t', 'toggleTurntable'),
        ('m', 'cycleMovementMode'),
    ])
    def test_a_bare_key_runs_its_method(self, keyboard, name, method):
        manager, viewer = keyboard
        _press(manager, name)
        assert viewer.called == [method]


class TestTheTableItself:
    def test_every_binding_names_a_method_the_viewer_has(self):
        for binding in SceneViewerMixin.viewerKeys:
            assert hasattr(SceneViewerMixin, binding.method), binding.method

    def test_no_two_bindings_want_the_same_press(self):
        seen = [(binding.name, binding.modifiers)
                for binding in SceneViewerMixin.viewerKeys]
        assert len(seen) == len(set(seen))

    def test_each_one_says_what_it_does(self):
        """A key nobody can describe is a key nobody can list."""
        for binding in SceneViewerMixin.viewerKeys:
            assert binding.description

    def test_they_all_fire_on_the_release(self):
        """A held key repeats about twenty times a second; the release does not."""
        for binding in SceneViewerMixin.viewerKeys:
            assert binding.state == 0, binding.name

    def test_holding_a_key_down_does_nothing_until_it_comes_up(self, keyboard):
        manager, viewer = keyboard
        for _ in range(20):
            _press(manager, '<pagedown>', CONTROL, state=1)
        assert viewer.called == []
        _press(manager, '<pagedown>', CONTROL)
        assert viewer.called == ['nextInLibrary']
