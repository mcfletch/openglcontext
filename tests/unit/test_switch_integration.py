"""A Switch turned off, as seen by the pass that watches the scenegraph.

The pass keeps a path to every node it might draw and re-walks the subtree
whenever a Switch changes choice, so a node that appears is found without the
whole graph being rebuilt. A Switch set to draw *nothing* -- ``whichChoice`` of
-1, which is how VRML97 spells "hide this" -- is the same event with no new
subtree at the end of it: the old paths go and nothing replaces them.
"""
import pytest
from pydispatch import dispatcher
from OpenGLContext.scenegraph import switch as switch_module
from OpenGLContext.scenegraph.box import Box
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.switch import Switch


@pytest.fixture
def watched():
    """A pass watching a graph with one Switch in it."""
    from OpenGLContext.passes.flatcore import FlatPass
    shape = Shape(geometry=Box())
    switch = Switch(choice=[Group(children=[shape])], whichChoice=0)
    scene = Group(children=[switch])
    watcher = FlatPass.__new__(FlatPass)
    watcher.nodePaths = {}
    watcher.paths = {}
    watcher.contexts = []
    watcher.integrate(scene)
    dispatcher.connect(watcher.onSwitchChange,
                       signal=switch_module.SWITCH_CHANGE_SIGNAL)
    yield watcher, switch, shape
    dispatcher.disconnect(watcher.onSwitchChange,
                          signal=switch_module.SWITCH_CHANGE_SIGNAL)


class TestSwitchingItOff:
    def test_a_switch_can_be_turned_off(self, watched) -> None:
        watcher, switch, shape = watched
        switch.whichChoice = -1
        assert switch.renderedChildren() == []

    def test_what_it_was_showing_is_no_longer_drawn(self, watched) -> None:
        watcher, switch, shape = watched
        assert any(path.broken is False for path in watcher.npFor(shape))
        switch.whichChoice = -1
        assert all(path.broken for path in watcher.npFor(shape))

    def test_it_can_be_turned_back_on(self, watched) -> None:
        watcher, switch, shape = watched
        switch.whichChoice = -1
        switch.whichChoice = 0
        assert any(not path.broken for path in watcher.npFor(shape))

    def test_a_choice_past_the_end_is_off_as_well(self, watched) -> None:
        watcher, switch, shape = watched
        switch.whichChoice = 7
        assert switch.renderedChildren() == []


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestBeingToldTheSameChoiceRepeatedly:
    """A Switch is told its choice every frame, whether or not it changed.

    Level-of-detail assigns ``whichChoice`` each frame from the viewer's
    distance, so the pass hears about a choice that has not moved. Rebuilding
    the subtree each time it hears would leave a second path to the same node,
    and a third, each holding its own cached transform -- a cost that grows
    with the length of the session rather than with the scene.
    """

    def held(self, watcher):
        return (sum(len(v) for v in watcher.paths.values()),
                sum(len(v) for v in watcher.nodePaths.values()))

    def test_the_records_do_not_grow(self, watched) -> None:
        watcher, switch, shape = watched
        before = self.held(watcher)
        for _ in range(5):
            switch.whichChoice = 0
        assert self.held(watcher) == before

    def test_a_real_change_is_still_followed(self, watched) -> None:
        watcher, switch, shape = watched
        second = Group(children=[Shape(geometry=Box())])
        switch.choice = list(switch.choice) + [second]
        switch.whichChoice = 1
        assert watcher.nodePaths.get(id(second)), (
            'switching to a new choice did not integrate it'
        )

    def test_the_old_choice_is_let_go(self, watched) -> None:
        watcher, switch, shape = watched
        second = Group(children=[Shape(geometry=Box())])
        switch.choice = list(switch.choice) + [second]
        switch.whichChoice = 1
        drawn = [p for paths in watcher.paths.values() for p in paths]
        assert [p for p in drawn if p.broken] == [], (
            'the path to the choice that was switched away from is still drawn'
        )


class TestTheSignalItself:
    def test_assigning_the_same_choice_says_nothing(self) -> None:
        """The signal reports a change of child, not an assignment."""
        shape = Shape(geometry=Box())
        switch = Switch(choice=[Group(children=[shape])], whichChoice=0)
        heard = []

        def listener(value=None):
            heard.append(value)

        dispatcher.connect(listener, signal=switch_module.SWITCH_CHANGE_SIGNAL,
                           sender=switch)
        try:
            switch.whichChoice = 0
            switch.whichChoice = 0
        finally:
            dispatcher.disconnect(listener,
                                  signal=switch_module.SWITCH_CHANGE_SIGNAL,
                                  sender=switch)
        assert heard == []
