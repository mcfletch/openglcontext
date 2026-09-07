"""The scenegraph outline model: rows, expansion, and what a change does to it.

No GL and no toolkit, which is the point of the model existing: the tree beside
a view is the same walk whether a `ttk.Treeview`, a `QTreeView` or a
`wx.TreeCtrl` is showing it.

See `OpenGLContext/demos/` for the three that do, and `plans/EMBEDDING-EXAMPLES.md`.
"""
import gc

import pytest
from vrml import protofunctions

from OpenGLContext.outline import SceneOutline, nodeChildren, nodeSummary
from OpenGLContext.scenegraph import basenodes


@pytest.fixture
def scene():
    """A hub with a shape under it and a light beside it"""
    return basenodes.sceneGraph(children=[
        basenodes.Transform(DEF='hub', children=[
            basenodes.Shape(
                DEF='thing',
                geometry=basenodes.Box(),
                appearance=basenodes.Appearance(),
            ),
        ]),
        basenodes.PointLight(DEF='lamp'),
    ])


def paths(outline):
    return [row.path for row in outline.rows]


def labels(outline):
    return [row.label for row in outline.rows]


class TestWhatItShows:
    def test_no_scene_has_no_rows(self):
        assert SceneOutline().rows == []

    def test_the_root_and_its_children_are_shown(self, scene):
        outline = SceneOutline(scene)
        assert paths(outline) == [(), (0,), (1,)]
        assert [row.depth for row in outline.rows] == [0, 1, 1]

    def test_a_node_is_labelled_by_its_def_name(self, scene):
        assert labels(SceneOutline(scene))[1:] == ['hub', 'lamp']

    def test_a_node_with_no_def_name_is_labelled_by_its_type(self):
        scene = basenodes.sceneGraph(children=[basenodes.Transform()])
        assert labels(SceneOutline(scene))[1] == 'Transform'

    def test_a_row_names_the_type_and_the_def_name_separately(self, scene):
        row = SceneOutline(scene).rows[1]
        assert (row.nodeType, row.defName) == ('Transform', 'hub')

    def test_a_row_names_the_field_it_hangs_from(self, scene):
        outline = SceneOutline(scene)
        assert outline.rows[0].field is None
        assert outline.rows[1].field == 'children'

    def test_a_node_with_children_is_expandable(self, scene):
        outline = SceneOutline(scene)
        assert [row.expandable for row in outline.rows] == [True, True, False]

    def test_the_scene_being_shown_can_be_asked_for(self, scene):
        assert SceneOutline(scene).root is scene


class TestWhatItTraverses:
    def test_single_valued_node_fields_are_children_too(self, scene):
        """A Shape's geometry and appearance are what an inspector is for; the
        rendering traversal does not follow them."""
        outline = SceneOutline(scene)
        outline.expand((0,))
        outline.expand((0, 0))
        assert labels(outline) == [
            'sceneGraph', 'hub', 'thing', 'Appearance', 'Box', 'lamp',
        ]

    def test_the_fields_a_node_keeps_for_itself_are_not_traversed(self, scene):
        """Every node holds a reference back to the scenegraph it belongs to,
        and following it would walk in circles."""
        outline = SceneOutline(scene)
        outline.expand((0,))
        assert 'root' not in [row.field for row in outline.rows]

    def test_one_field_that_will_not_be_read_does_not_stop_the_walk(self):
        """A tool that shows somebody else's file has to survive what is in
        it: the rest of the scene is still worth showing."""
        from vrml import node as vnode

        class Awkward(vnode.Node):
            PROTO = 'Awkward'

            class refuses(vnode.SFNode):
                def fget(self, client, *args, **named):
                    raise ValueError('this field will not be read')

            refuses = refuses('refuses')

        assert nodeChildren(Awkward()) == []

    def test_an_empty_field_contributes_no_row(self):
        scene = basenodes.sceneGraph(children=[basenodes.Shape()])
        outline = SceneOutline(scene)
        outline.expand((0,))
        assert outline.rows[1].expandable is False
        assert len(outline.rows) == 2

    def test_a_node_reached_twice_is_shown_in_both_places(self):
        """`USE` in VRML97, a shared mesh in glTF: one node, two places."""
        shared = basenodes.Shape(DEF='shared', geometry=basenodes.Box())
        scene = basenodes.sceneGraph(children=[
            basenodes.Transform(children=[shared]),
            basenodes.Transform(children=[shared]),
        ])
        outline = SceneOutline(scene)
        outline.expand((0,))
        outline.expand((1,))
        assert labels(outline).count('shared') == 2

    def test_a_node_that_leads_back_to_itself_stops_there(self):
        """A walk that hangs is no way to find out that a scene refers to
        itself.  The node is shown where it is reached and not opened again."""
        inner = basenodes.Transform(DEF='inner')
        outer = basenodes.Transform(DEF='outer', children=[inner])
        inner.children = [outer]
        outline = SceneOutline(outer, expanded=[(), (0,), (0, 0)])
        assert labels(outline) == ['outer', 'inner', 'outer']
        assert outline.rows[-1].expandable is False


class TestExpansion:
    def test_a_scene_opens_with_its_root_expanded(self, scene):
        """A tree showing one closed row says nothing about the scene."""
        assert len(SceneOutline(scene).rows) == 3

    def test_collapsing_hides_what_was_under_it(self, scene):
        outline = SceneOutline(scene)
        outline.collapse(())
        assert paths(outline) == [()]

    def test_toggle_reports_the_state_it_left(self, scene):
        outline = SceneOutline(scene)
        assert outline.toggle((0,)) is True
        assert paths(outline) == [(), (0,), (0, 0), (1,)]
        assert outline.toggle((0,)) is False
        assert paths(outline) == [(), (0,), (1,)]

    def test_expanding_a_leaf_leaves_the_rows_alone(self, scene):
        outline = SceneOutline(scene)
        outline.expand((1,))
        assert paths(outline) == [(), (0,), (1,)]


class TestSelection:
    def test_nothing_is_selected_to_begin_with(self, scene):
        outline = SceneOutline(scene)
        assert outline.selection is None
        assert outline.selected is None

    def test_selecting_a_row_names_its_node(self, scene):
        outline = SceneOutline(scene)
        outline.select((1,))
        assert outline.selected is scene.children[1]

    def test_a_selection_that_is_still_there_survives_a_rebuild(self, scene):
        outline = SceneOutline(scene)
        outline.select((0,))
        outline.refresh()
        assert outline.selected is scene.children[0]

    def test_the_selected_row_names_the_node_as_the_tree_shows_it(self, scene):
        """A panel beside the tree wants the type and the name, not just the
        node."""
        outline = SceneOutline(scene)
        outline.select((0,))
        assert (outline.selectedRow.nodeType, outline.selectedRow.defName) == (
            'Transform', 'hub')

    def test_nothing_selected_has_no_row(self, scene):
        assert SceneOutline(scene).selectedRow is None

    def test_a_selection_that_has_gone_is_let_go_of(self, scene):
        outline = SceneOutline(scene)
        outline.select((1,))
        scene.children = scene.children[:1]
        assert outline.selected is None
        assert outline.selection is None


class TestWatchingForChanges:
    def test_a_new_child_is_noticed(self, scene):
        outline = SceneOutline(scene)
        assert outline.dirty is False
        scene.children.append(basenodes.PointLight(DEF='second'))
        assert outline.dirty is True
        assert labels(outline)[-1] == 'second'

    def test_reading_the_rows_settles_the_outline(self, scene):
        outline = SceneOutline(scene)
        scene.children.append(basenodes.PointLight())
        assert outline.rows
        assert outline.dirty is False

    def test_a_replaced_field_is_noticed(self, scene):
        outline = SceneOutline(scene)
        scene.children = [basenodes.PointLight(DEF='only')]
        assert labels(outline) == ['sceneGraph', 'only']

    def test_a_change_under_a_shown_node_is_noticed(self, scene):
        outline = SceneOutline(scene)
        outline.expand((0,))
        scene.children[0].children.append(basenodes.PointLight(DEF='added'))
        assert 'added' in labels(outline)

    def test_a_def_name_changing_is_noticed(self, scene):
        outline = SceneOutline(scene)
        protofunctions.defName(scene.children[1], 'renamed')
        assert labels(outline)[-1] == 'renamed'

    def test_the_host_is_told_once_per_change(self, scene):
        told = []
        outline = SceneOutline(scene, onChange=lambda: told.append(1))
        scene.children.append(basenodes.PointLight())
        assert len(told) == 1
        assert outline.dirty is True

    def test_the_host_is_not_told_again_until_it_has_looked(self, scene):
        """A tree refills from the rows, so one notice covers every change
        that arrives before it does."""
        told = []
        outline = SceneOutline(scene, onChange=lambda: told.append(1))
        scene.children.append(basenodes.PointLight())
        scene.children.append(basenodes.PointLight())
        assert len(told) == 1
        outline.refresh()
        scene.children.append(basenodes.PointLight())
        assert len(told) == 2

    def test_a_node_no_longer_shown_is_no_longer_watched(self, scene):
        """A viewer opening model after model would otherwise accumulate a
        subscription to every node it had ever displayed."""
        outline = SceneOutline(scene)
        hub = scene.children[0]
        scene.children = scene.children[1:]
        assert outline.rows[-1].label == 'lamp'
        hub.children.append(basenodes.PointLight(DEF='unseen'))
        assert outline.dirty is False

    def test_a_closed_outline_watches_nothing(self, scene):
        outline = SceneOutline(scene)
        outline.close()
        scene.children.append(basenodes.PointLight())
        assert outline.dirty is False
        assert outline.rows == []

    def test_a_new_scene_replaces_the_old_one(self, scene):
        outline = SceneOutline(scene)
        outline.root = basenodes.sceneGraph(children=[basenodes.Transform(DEF='other')])
        assert labels(outline) == ['sceneGraph', 'other']
        scene.children.append(basenodes.PointLight())
        assert outline.dirty is False

    def test_a_closed_outline_lets_go_of_the_scene(self):
        """The rows are what hold it: a viewer that opens one model after
        another must not keep every one of them."""
        import weakref

        scene = basenodes.sceneGraph(children=[basenodes.PointLight()])
        held = weakref.ref(scene.children[0])
        outline = SceneOutline(scene)
        outline.close()
        del scene
        gc.collect()
        assert held() is None
        assert outline.rows == []

    def test_a_host_handler_that_raises_does_not_break_the_outline(self):
        """The handler belongs to a toolkit; what it does with the notice is
        its own business, and the scene keeps changing either way."""
        def unhappy():
            raise RuntimeError('the tree is not ready')

        scene = basenodes.sceneGraph(children=[])
        outline = SceneOutline(scene, onChange=unhappy)
        scene.children.append(basenodes.PointLight(DEF='regardless'))
        assert labels(outline) == ['sceneGraph', 'regardless']


class TestSummarisingANode:
    def test_a_nodes_own_values_are_reported(self):
        node = basenodes.Transform(translation=(1, 2, 3))
        assert dict(nodeSummary(node))['translation'] == '[1. 2. 3.]'

    def test_the_nodes_under_it_are_left_to_the_tree(self):
        """They are rows of their own; a panel beside the tree says what this
        one node is."""
        node = basenodes.Transform(children=[basenodes.PointLight()])
        assert 'children' not in dict(nodeSummary(node))

    def test_the_fields_a_node_keeps_for_itself_are_not_reported(self):
        assert [name for name, _ in nodeSummary(basenodes.Transform())
                if name.startswith(' ')] == []

    def test_it_reads_in_name_order(self):
        names = [name for name, _ in nodeSummary(basenodes.Transform())]
        assert names == sorted(names)

    def test_a_long_value_is_cut_to_length(self):
        node = basenodes.Coordinate(point=[(index, 0, 0) for index in range(500)])
        assert all(len(value) <= 60 for _, value in nodeSummary(node, width=60))

    def test_a_value_that_will_not_be_read_is_reported_as_such(self):
        from vrml import fieldtypes, node as vnode

        class Awkward(vnode.Node):
            PROTO = 'Awkward'

            class refuses(fieldtypes.SFFloat):
                def fget(self, client, *args, **named):
                    raise ValueError('this field will not be read')

            refuses = refuses('refuses')

        assert dict(nodeSummary(Awkward()))['refuses'] == '?'

    def test_nothing_summarises_as_nothing(self):
        assert nodeSummary(None) == []
