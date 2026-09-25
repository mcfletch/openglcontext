"""What the per-frame gather hands the rest of the frame.

`FlatPass.renderSet` is the first thing a frame does and the widest: every
renderable path in the scene passes through it, and what it produces is read
again by the shadow pass, by the level-of-detail selection and by the draw
itself.  These drive it with a real scenegraph and no GL context -- the gather
is arithmetic over the scenegraph's own caches, and nothing in it touches a
driver.
"""
import numpy as np
import pytest

from OpenGLContext import frustum
from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph import basenodes


def _shape(size=(2, 2, 2)):
    return basenodes.Shape(geometry=basenodes.Box(size=size))


def _scene(count=3, spacing=4.0):
    """A scenegraph of `count` boxes, each under its own Transform."""
    moves = [basenodes.Transform(translation=(index * spacing, 0, 0),
                                 children=[_shape()])
             for index in range(count)]
    return basenodes.sceneGraph(children=moves), moves


@pytest.fixture
def gather():
    """A pass over a three-box scene, with a frustum that keeps everything."""
    scene, moves = _scene()
    passing = FlatPass(scene, [])
    passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
    return passing, moves


class TestTheGatherKeepsTransformIdentity:
    """A record's transform matrix is the scenegraph's own cached object.

    Everything downstream that remembers a per-object answer between frames --
    the shadow pass's caster geometry above all -- tells "this has not moved"
    from the matrix being the *same object* it was handed last frame.  The
    scenegraph's transform cache provides exactly that: one object while a node
    is still, a fresh one the moment it moves.  A gather that handed out rows of
    a buffer it refills each frame would give every object a new identity every
    frame, and every such memo would miss every time.
    """

    def test_a_records_matrix_is_the_paths_own(self, gather):
        passing, _moves = gather
        for record in passing.renderSet(np.eye(4, dtype='f')):
            assert record[2] is record[4].transformMatrix()

    def test_an_unmoved_path_keeps_the_same_matrix_between_frames(self, gather):
        passing, _moves = gather
        first = {id(r[4]): r[2] for r in passing.renderSet(np.eye(4, dtype='f'))}
        second = passing.renderSet(np.eye(4, dtype='f'))
        assert second
        for record in second:
            assert record[2] is first[id(record[4])]

    def test_a_moved_path_gets_a_fresh_matrix(self, gather):
        passing, moves = gather
        before = {id(r[4]): r[2] for r in passing.renderSet(np.eye(4, dtype='f'))}
        moves[1].translation = (0, 9, 0)
        moved = still = 0
        for record in passing.renderSet(np.eye(4, dtype='f')):
            if record[2] is before[id(record[4])]:
                still += 1
            else:
                moved += 1
                assert record[2][3][1] == pytest.approx(9.0)
        assert (moved, still) == (1, 2)

    def test_every_records_matrix_places_its_own_node(self, gather):
        """Identity is not enough: the values have to be each path's own."""
        passing, _moves = gather
        found = sorted(float(r[2][3][0])
                       for r in passing.renderSet(np.eye(4, dtype='f')))
        assert found == pytest.approx([0.0, 4.0, 8.0])

    def test_the_modelview_still_carries_the_camera(self, gather):
        """Slot 1 is the record's matrix through the camera, and stays so."""
        passing, _moves = gather
        camera = np.eye(4, dtype='f')
        camera[3, 2] = -10.0
        for record in passing.renderSet(camera):
            assert np.allclose(record[1], np.asarray(record[2]) @ camera)


class TestOneTableForTheWholeFrame:
    """Everything the frame knows about a path, worked out once.

    A path's node, its world matrix and its bounding volume are asked for by
    the gather, by the shadow pass's caster pool and by the draw, and each
    answer is the same for all of them. They come off one table.
    """

    def test_every_renderable_path_is_in_the_table(self, gather):
        passing, _moves = gather
        table = passing.gatherPaths()
        assert len(table.paths) == 3
        assert table.nodes == [path[-1] for path in table.paths]

    def test_the_table_holds_each_paths_own_matrix_and_volume(self, gather):
        passing, _moves = gather
        table = passing.gatherPaths()
        for index, path in enumerate(table.paths):
            assert table.own[index] is path.transformMatrix()
            assert table.volumes[index] is path[-1].boundingVolume(passing)
            assert np.allclose(table.matrices[index], table.own[index])

    def test_a_node_that_draws_nothing_is_marked_and_left_unbounded(self):
        """An instanced set with every copy taken is the resting state of a pool."""
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        scene, _moves = _scene(2)
        empty = InstancedShape(geometry=basenodes.Box(size=(1, 1, 1)),
                               placements=[])
        scene.children.append(basenodes.Transform(children=[empty]))
        passing = FlatPass(scene, [])
        passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))

        table = passing.gatherPaths()

        at = table.nodes.index(empty)
        assert not table.drawing[at]
        assert not table.bounded[at]
        assert table.volumes[at] is None
        assert all(table.drawing[other] for other in range(3) if other != at)
        drawn = [r[4][-1] for r in passing.renderSet(np.eye(4, dtype='f'))]
        assert len(drawn) == 2 and empty not in drawn

    def test_a_scene_with_nothing_in_it_gathers_nothing(self):
        passing = FlatPass(basenodes.sceneGraph(children=[]), [])
        passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
        assert passing.gatherPaths().paths == []


class TestTheShadowPoolReadsTheGather:
    """The caster pool is the same scene the gather just walked.

    It is not the same *set* -- a caster behind the camera still casts into
    view, so the pool is the whole scene while the render set is what survived
    the frustum -- but every question it asks of a path has been asked and
    answered a moment earlier in the same frame.
    """

    def _pass(self, count=4):
        from OpenGLContext.passes import _flat, flatcore
        moves = [basenodes.Transform(translation=(index * 3.0, 0, 0),
                                     children=[_shape()])
                 for index in range(count)]
        scene = basenodes.sceneGraph(children=moves)
        passing = flatcore.FlatPass.__new__(flatcore.FlatPass)
        _flat.SGObserver.__init__(passing, scene, [])
        passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
        return passing, moves

    def _counting(self, monkeypatch):
        from vrml.vrml97 import nodepath as vrml_nodepath
        seen = []
        real = vrml_nodepath._NodePath.transformMatrix

        def counted(path, *args, **named):
            seen.append(id(path))
            return real(path, *args, **named)

        monkeypatch.setattr(vrml_nodepath._NodePath, 'transformMatrix', counted)
        return seen

    def test_a_path_is_asked_where_it_is_once_a_frame(self, monkeypatch):
        passing, _moves = self._pass(4)
        seen = self._counting(monkeypatch)

        with passing.drawingFrame():
            toRender = passing.renderSet(np.eye(4, dtype='f'))
            passing._shadowCasterRecords()

        assert len(toRender) == 4
        assert len(seen) == 4

    def test_the_pool_is_the_whole_scene_and_not_the_visible_set(self):
        passing, _moves = self._pass(4)
        # A frustum that rejects everything: nothing is drawn, and everything
        # still casts.
        behind = np.zeros((1, 4), 'f')
        behind[0] = (0.0, 0.0, 1.0, -1000.0)
        passing.frustum = frustum.Frustum(planes=behind)

        assert passing.renderSet(np.eye(4, dtype='f')) == []
        assert len(passing._shadowCasterRecords()) == 4

    def test_a_node_that_opts_out_of_casting_is_left_out(self):
        passing, _moves = self._pass(3)
        passing.renderSet(np.eye(4, dtype='f'))
        passing.gatherPaths().nodes[1].castsShadow = False

        records = passing._shadowCasterRecords()

        assert len(records) == 2

    def test_a_pool_asked_before_any_gather_works_the_scene_out_itself(self):
        passing, _moves = self._pass(3)
        records = passing._shadowCasterRecords()
        assert len(records) == 3
        for record in records:
            assert record[2] is record[4].transformMatrix()

    def test_the_pool_carries_the_paths_own_matrix(self, monkeypatch):
        """Which is what lets the caster memo tell a still scene from a moved one."""
        passing, _moves = self._pass(3)
        passing.renderSet(np.eye(4, dtype='f'))
        for record in passing._shadowCasterRecords():
            assert record[2] is record[4].transformMatrix()


class TestTheRecordCarriesItsNode:
    """A record holds the node it draws, so nothing has to walk back for it.

    Almost everything that reads a render record wants the node at the end of
    its path -- to key an instanced batch on, to ask whether it casts a shadow,
    to sort its material, to draw it. The gather already knows that node, so
    the record carries it and the walk happens once rather than once per
    reader. `path[-1]` is a Python ``__getitem__`` on a list subclass, and a
    frame of a few thousand objects was making tens of thousands of them.
    """

    def test_a_record_carries_the_node_it_draws(self, gather):
        passing, _moves = gather
        records = passing.renderSet(np.eye(4, dtype='f'))
        assert records
        for record in records:
            assert record[5] is record[4][-1]

    def test_the_caster_pool_carries_it_too(self):
        from OpenGLContext.passes import _flat, flatcore
        scene, _moves = _scene(3)
        passing = flatcore.FlatPass.__new__(flatcore.FlatPass)
        _flat.SGObserver.__init__(passing, scene, [])
        passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))

        for record in passing._shadowCasterRecords():
            assert record[5] is record[4][-1]

    def test_grouping_a_frame_walks_no_paths(self, gather, monkeypatch):
        """What the record carrying its node is for: the readers stop asking."""
        from vrml.nodepath import NodePath
        from OpenGLContext.passes import instancing
        passing, _moves = gather
        records = passing.renderSet(np.eye(4, dtype='f'))

        walks = []
        real = NodePath.__getitem__
        monkeypatch.setattr(
            NodePath, '__getitem__',
            lambda self, index: (walks.append(index), real(self, index))[1])

        groups, singles = instancing.build_instance_groups(records)
        instancing.instance_counts(records)
        for record in records:
            instancing.record_placements(record)

        assert len(groups) + len(singles) >= 1
        assert walks == []


class TestTheFrustumTest:
    """The cull rejects exactly the shapes with all eight corners behind a plane.

    That is the decision
    :meth:`OpenGLContext.scenegraph.boundingvolume.BoundingBox.visible` makes
    one shape at a time; the pass makes it for the whole scene at once, from
    each box's centre and half-axes.
    """

    @staticmethod
    def _corners(low, high):
        corners = np.ones((8, 4), 'f')
        for index in range(8):
            for axis in range(3):
                corners[index, axis] = (high if index >> axis & 1 else low)[axis]
        return corners

    @staticmethod
    def _eight_corner_decision(matrices, points, planes):
        world = np.array([p @ m for p, m in zip(points, matrices)])
        distances = world @ planes.T
        return ~(distances < 0).all(axis=1).any(axis=1)

    def test_it_matches_the_eight_corner_test_under_any_transform(self):
        rng = np.random.default_rng(7)
        count = 400
        points = np.empty((count, 8, 4), 'f')
        matrices = np.empty((count, 4, 4), 'f')
        for index in range(count):
            low = rng.uniform(-3, 1, 3)
            points[index] = self._corners(low, low + rng.uniform(0.1, 4, 3))
            matrix = np.eye(4)
            matrix[:3, :3] = rng.normal(size=(3, 3))
            matrix[3, :3] = rng.uniform(-30, 30, 3)
            matrices[index] = matrix
        planes = rng.normal(size=(6, 4)).astype('f')
        planes[:, 3] = rng.uniform(-10, 10, 6)
        passing = FlatPass(basenodes.sceneGraph(), [])
        passing.frustum = frustum.Frustum(planes=planes)
        everything = np.ones(count, bool)

        kept = passing._frustumSurvivors(matrices, points, everything, everything)

        expected = np.flatnonzero(self._eight_corner_decision(matrices, points, planes))
        assert 0 < len(expected) < count
        assert list(kept) == list(expected)

    def test_an_unbounded_or_empty_path_is_never_culled_nor_drawn(self):
        points = np.zeros((2, 8, 4), 'f')
        matrices = np.tile(np.eye(4, dtype='f'), (2, 1, 1))
        passing = FlatPass(basenodes.sceneGraph(), [])
        passing.frustum = frustum.Frustum(
            planes=np.array([(0, 0, 1, -1000)], 'f'))

        kept = passing._frustumSurvivors(matrices, points, np.array([False, False]),
                                         np.array([True, False]))

        assert list(kept) == [0]


class TestBoxesOutside:
    """``frustum.boxes_outside``: the one plane test every cull shares."""

    def test_it_is_the_eight_corner_decision(self):
        from OpenGLContext.frustum import boxes_outside
        rng = np.random.default_rng(11)
        count = 300
        low = rng.uniform(-3, 1, (count, 3))
        high = low + rng.uniform(0.1, 4, (count, 3))
        matrices = np.tile(np.eye(4), (count, 1, 1))
        matrices[:, :3, :3] = rng.normal(size=(count, 3, 3))
        matrices[:, 3, :3] = rng.uniform(-30, 30, (count, 3))
        planes = rng.normal(size=(6, 4))
        planes[:, 3] = rng.uniform(-10, 10, 6)
        corners = np.ones((count, 8, 4))
        for index in range(8):
            for axis in range(3):
                corners[:, index, axis] = np.where(index >> axis & 1, high[:, axis], low[:, axis])
        world = np.einsum('nci,nij->ncj', corners, matrices)
        expected = ((world @ planes.T) < 0).all(axis=1).any(axis=1)

        found = boxes_outside((low + high) / 2, (high - low) / 2, matrices, planes)

        assert 0 < expected.sum() < count
        assert list(found) == list(expected)

    def test_one_box_under_many_matrices(self):
        from OpenGLContext.frustum import boxes_outside
        matrices = np.tile(np.eye(4), (3, 1, 1))
        matrices[:, 3, 0] = (0.0, 50.0, -50.0)
        planes = np.array([(1.0, 0.0, 0.0, 10.0), (-1.0, 0.0, 0.0, 10.0)])
        found = boxes_outside(np.zeros(3), np.ones(3), matrices, planes)
        assert list(found) == [False, True, True]
