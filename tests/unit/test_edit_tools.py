"""Tool modes: what the pointer does, and who gets to decide.

An editor's pointer does a different thing in each tool -- placing a point,
dragging one, measuring, painting -- and the camera wants the same pointer.
The rule is that the tool is asked first and the camera gets whatever the tool
did not want, so a tool that only cares about the left button leaves the right
one orbiting.

Headless: a tool mode is a state machine over a stream of pointer events.
"""
import numpy as np
import pytest

from OpenGLContext.edit.tools import Pointer, ToolManager, ToolMode


class Recorder(ToolMode):
    """A tool that writes down what it was offered."""

    def __init__(self, name, takes=('press', 'drag', 'release', 'move', 'key')):
        super(Recorder, self).__init__(name=name, label=name.title())
        self.seen = []
        self.takes = takes
        self.entered = 0
        self.left = 0
        self.cancelled = 0

    def enter(self):
        self.entered += 1

    def leave(self):
        self.left += 1

    def cancel(self):
        self.cancelled += 1

    def _note(self, what, *args):
        self.seen.append((what,) + args)
        return what in self.takes

    def on_press(self, pointer):
        return self._note('press', pointer.button)

    def on_drag(self, pointer):
        return self._note('drag', pointer.button)

    def on_release(self, pointer):
        return self._note('release', pointer.button)

    def on_move(self, pointer):
        return self._note('move')

    def on_key(self, name, modifiers):
        return self._note('key', name)


def _at(x=0.0, y=0.0, world=None, button=0, modifiers=(0, 0, 0)):
    return Pointer(x=x, y=y, world=world, button=button, modifiers=modifiers)


def _manager(*tools):
    return ToolManager(tools or (Recorder('place'), Recorder('drag')))


class TestChoosingATool:
    def test_the_first_declared_is_in_force(self) -> None:
        place, _drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, _drag])
        assert manager.active is place

    def test_with_no_tools_nothing_is(self) -> None:
        assert ToolManager([]).active is None

    def test_selecting_by_name_puts_it_in_force(self) -> None:
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        assert manager.select('drag') is True
        assert manager.active is drag

    def test_a_name_that_is_not_there_changes_nothing(self) -> None:
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        assert manager.select('paint') is False
        assert manager.active is place

    def test_entering_and_leaving_are_announced(self) -> None:
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        assert place.entered == 1
        manager.select('drag')
        assert place.left == 1 and drag.entered == 1

    def test_selecting_the_one_already_in_force_is_not_a_change(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.select('place')
        assert place.entered == 1 and place.left == 0

    def test_cycling_walks_the_declared_order(self) -> None:
        place, drag, paint = Recorder('place'), Recorder('drag'), Recorder('paint')
        manager = ToolManager([place, drag, paint])
        assert manager.cycle() is drag
        assert manager.cycle() is paint
        assert manager.cycle() is place, "it should come round again"

    def test_cycling_backwards_goes_the_other_way(self) -> None:
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        assert manager.cycle(-1) is drag

    def test_a_change_is_published(self) -> None:
        seen = []
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag], on_change=seen.append)
        manager.select('drag')
        assert seen == [drag]


class TestWhoGetsThePointer:
    def test_the_tool_in_force_is_asked(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at(button=1))
        assert place.seen == [('press', 1)]

    def test_a_tool_not_in_force_is_not(self) -> None:
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        manager.press(_at())
        assert drag.seen == []

    def test_what_the_tool_takes_is_reported_taken(self) -> None:
        manager = ToolManager([Recorder('place', takes=('press',))])
        assert manager.press(_at()) is True

    def test_what_it_declines_is_left_for_the_camera(self) -> None:
        manager = ToolManager([Recorder('place', takes=())])
        assert manager.press(_at()) is False
        assert manager.move(_at()) is False
        assert manager.key('w', (0, 0, 0)) is False

    def test_with_no_tool_everything_is_the_camera_s(self) -> None:
        manager = ToolManager([])
        assert manager.press(_at()) is False


class TestADrag:
    def test_a_move_after_a_taken_press_is_a_drag(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at())
        manager.move(_at(x=10.0))
        assert place.seen == [('press', 0), ('drag', 0)]

    def test_a_move_with_no_press_is_just_a_move(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.move(_at(x=10.0))
        assert place.seen == [('move',)]

    def test_the_release_ends_it(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at())
        manager.release(_at())
        manager.move(_at(x=10.0))
        assert place.seen[-1] == ('move',)

    def test_a_drag_stays_with_the_tool_that_started_it(self) -> None:
        """Switching tools mid-drag would leave the first one half-way
        through a gesture it never sees the end of."""
        place, drag = Recorder('place'), Recorder('drag')
        manager = ToolManager([place, drag])
        manager.press(_at())
        assert manager.select('drag') is False
        manager.release(_at())
        assert manager.select('drag') is True

    def test_a_press_the_tool_declined_does_not_start_one(self) -> None:
        place = Recorder('place', takes=('move',))
        manager = ToolManager([place])
        manager.press(_at())
        manager.move(_at(x=10.0))
        assert place.seen == [('press', 0), ('move',)]

    def test_the_button_that_started_it_comes_with_it(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at(button=2))
        manager.move(_at(x=10.0))
        assert place.seen[-1] == ('drag', 2)


class TestGivingUp:
    def test_escape_abandons_what_is_half_done(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at())
        assert manager.key('<escape>', (0, 0, 0)) is True
        assert place.cancelled == 1

    def test_and_ends_the_drag(self) -> None:
        place = Recorder('place')
        manager = ToolManager([place])
        manager.press(_at())
        manager.key('<escape>', (0, 0, 0))
        manager.move(_at(x=10.0))
        assert place.seen[-1] == ('move',)

    def test_escape_with_nothing_going_on_is_the_camera_s(self) -> None:
        """A tool that is not doing anything must not eat Escape: it is how a
        player leaves whatever else has hold of the window."""
        place = Recorder('place', takes=())
        manager = ToolManager([place])
        assert manager.key('<escape>', (0, 0, 0)) is False


class TestWhereThePointerIs:
    def test_it_carries_the_point_on_the_surface(self) -> None:
        pointer = _at(x=100.0, y=50.0, world=np.array([1.0, 2.0, 3.0]))
        assert pointer.on_surface
        assert tuple(pointer.world) == (1.0, 2.0, 3.0)

    def test_a_pointer_over_nothing_says_so(self) -> None:
        assert not _at(x=100.0, y=50.0).on_surface

    def test_it_knows_which_modifiers_are_down(self) -> None:
        assert _at(modifiers=(1, 0, 0)).shifted
        assert _at(modifiers=(0, 1, 0)).controlled
        assert not _at().shifted


class TestTheBaseToolIsHarmless:
    """A tool that overrides nothing declines everything, so subclassing it to
    do one thing does not accidentally take the camera's pointer away."""

    def test_it_takes_nothing(self) -> None:
        tool = ToolMode(name='bare')
        assert tool.on_press(_at()) is False
        assert tool.on_drag(_at()) is False
        assert tool.on_release(_at()) is False
        assert tool.on_move(_at()) is False
        assert tool.on_key('w', (0, 0, 0)) is False

    def test_it_has_a_label_to_show(self) -> None:
        assert ToolMode(name='place_point').label == 'Place point'

    def test_a_label_can_be_given(self) -> None:
        assert ToolMode(name='place', label='Drop a marker').label \
            == 'Drop a marker'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestTheWheel:
    """A notch over the map is the camera's, unless the tool wants it."""

    def test_the_tool_in_force_is_asked_first(self):
        class Sizing(ToolMode):
            notches = 0

            def on_wheel(self, pointer, notches):
                self.notches += notches
                return True

        tool = Sizing(name='brush')
        tools = ToolManager([tool])
        assert tools.wheel(Pointer(), 2)
        assert tool.notches == 2

    def test_what_no_tool_wants_is_left_for_the_camera(self):
        tools = ToolManager([ToolMode(name='plain')])
        assert not tools.wheel(Pointer(), 1)

    def test_a_manager_with_no_tools_wants_nothing(self):
        assert not ToolManager([]).wheel(Pointer(), 1)


class TestTakingItBack:
    """Undo belongs to the tool that did the thing."""

    class Doing(ToolMode):
        def __init__(self, **named):
            super().__init__(**named)
            self.done = []

        def undo(self):
            if not self.done:
                return False
            self.done.pop()
            return True

        def redo(self):
            self.done.append('again')
            return True

    def test_undo_goes_to_the_tool_in_force(self):
        tool = self.Doing(name='draw')
        tool.done.append('something')
        tools = ToolManager([tool])
        assert tools.undo()
        assert tool.done == []

    def test_a_tool_with_nothing_to_take_back_says_so(self):
        tools = ToolManager([self.Doing(name='draw')])
        assert not tools.undo()

    def test_redo_goes_to_the_same_tool(self):
        tool = self.Doing(name='draw')
        tools = ToolManager([tool])
        assert tools.redo()
        assert tool.done == ['again']

    def test_a_tool_that_does_nothing_undoable_says_so(self):
        tools = ToolManager([ToolMode(name='plain')])
        assert not tools.undo()
        assert not tools.redo()

    def test_a_manager_with_no_tools_says_so(self):
        assert not ToolManager([]).undo()
        assert not ToolManager([]).redo()
