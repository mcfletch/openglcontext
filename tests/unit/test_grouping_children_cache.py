"""The typed view of a grouping node's children agrees with the children.

:meth:`~OpenGLContext.scenegraph.grouping.Grouping.renderedChildren` is a
type-filtered copy of the ``children`` field, kept so that the render pass does
not re-filter a scene's every node on every traversal. A copy is only as good as
its agreement with the thing it copies, and this is what says the two agree.

The agreement matters well beyond a stale read. The flat render pass builds one
node-path per child it is handed, so a copy that names a child twice gives that
child two paths, and everything charged per path -- a world matrix, a sort key, a
bounding volume, a frustum test, and a draw -- is charged for it twice, for as
long as the node is in the scene.
"""

from OpenGLContext.scenegraph import grouping
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform


def typed_view(node):
    """What the render traversal would be handed for ``node``."""
    return list(node.renderedChildren())


class TestTheTypedViewFollowsTheField:
    """Whatever is done to ``children``, the filtered copy says the same."""

    def test_a_fresh_group_reports_what_it_was_given(self):
        group = Group(children=[Shape(), Shape()])
        assert len(typed_view(group)) == 2

    def test_an_appended_child_appears(self):
        group = Group(children=[Shape()])
        typed_view(group)                       # build the copy first
        group.children.append(Shape())
        assert len(typed_view(group)) == 2

    def test_a_removed_child_goes(self):
        keep, drop = Shape(), Shape()
        group = Group(children=[keep, drop])
        typed_view(group)
        group.children.remove(drop)
        assert typed_view(group) == [keep]

    def test_reassigning_the_field_replaces_the_view(self):
        group = Group(children=[Shape(), Shape()])
        typed_view(group)
        fresh = [Shape()]
        group.children = fresh
        assert typed_view(group) == fresh

    def test_a_child_that_is_not_rendered_is_left_out(self):
        """The copy is a *filter*, and a filter that passes everything is not one."""
        shape = Shape()
        group = Group(children=[shape, grouping.node.Node()])
        assert typed_view(group) == [shape]


class TestNotificationsThatDescribeAnotherList:
    """A change notification is a hint, not an authority on what the field holds.

    An ``OList`` carries the node it was set on as the sender of its change
    notifications, and it goes on carrying it after the node's field has moved
    on to a different list -- which the glTF loader does when it builds a node's
    children a second time. The notifications from the list left behind then
    arrive describing children this node already has, and a copy that believes
    them holds each of those children twice.
    """

    def signal_new(self, node, child):
        """The notification a list sends when it gains ``child``."""
        field = type(node).children
        grouping._cacheClear(('set', field), node, subsignal='new',
                             subvalue=child)

    def signal_del(self, node, child):
        field = type(node).children
        grouping._cacheClear(('set', field), node, subsignal='del',
                             subvalue=child)

    def test_being_told_twice_about_one_child_does_not_double_it(self):
        child = Shape()
        group = Group(children=[child])
        assert typed_view(group) == [child]
        self.signal_new(group, child)
        assert typed_view(group) == [child], \
            'the copy holds a child the field holds once'

    def test_being_told_about_a_removal_that_did_not_happen_keeps_it(self):
        child = Shape()
        group = Group(children=[child])
        typed_view(group)
        self.signal_del(group, child)
        assert typed_view(group) == [child], \
            'the copy dropped a child the field still holds'

    def test_a_whole_subtree_rebuilt_over_itself_stays_one_deep(self):
        """The shape of the glTF loader's second pass over a node it has built.

        Every child is announced again while the field already holds it, and
        none is announced as leaving.
        """
        kids = [Transform() for _ in range(8)]
        parent = Transform(children=kids)
        assert len(typed_view(parent)) == 8
        for kid in kids[1:]:
            self.signal_new(parent, kid)
        assert len(typed_view(parent)) == 8, \
            'a rebuilt subtree is counted more than once per route to it'
