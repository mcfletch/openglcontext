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
