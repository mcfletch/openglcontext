"""Where a streamed dataset opens the camera
(:mod:`OpenGLContext.viewer.adapters.tiles`).

Fitting a bounding sphere is right for a model: back off until all of it is in
frame. A city-sized tileset framed that way puts the camera kilometres out,
where the whole dataset is a smudge on the horizon and every tile is at its
coarsest. A dataset is somewhere to *be*, so it opens above its content, close
enough that buildings are buildings.
"""
import math

import numpy as np
import pytest

from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.viewer.adapters.tiles import TilesAdapter, opening_pose
from OpenGLContext.viewer.framing import fit_sphere


CENTRE = (100.0, 20.0, -50.0)
RADIUS = 7854.0            # the framed radius of a city-sized tileset


class TestOpeningOverTheContent:
    def test_the_camera_opens_within_a_fraction_of_the_dataset(self):
        pose = opening_pose(CENTRE, RADIUS)
        distance = np.linalg.norm(np.asarray(pose.position) - np.asarray(CENTRE))
        assert distance < RADIUS / 2, distance

    def test_it_is_far_closer_in_than_fitting_the_whole_sphere(self):
        fitted = fit_sphere(RADIUS)
        pose = opening_pose(CENTRE, RADIUS)
        near = np.linalg.norm(np.asarray(pose.position) - np.asarray(CENTRE))
        far = np.linalg.norm(np.asarray(fitted.position))
        assert near < far / 4, (near, far)

    def test_the_camera_is_above_the_content_it_looks_at(self):
        pose = opening_pose(CENTRE, RADIUS)
        assert pose.position[1] > CENTRE[1]

    def test_the_near_plane_is_close_enough_for_a_building(self):
        """A near plane scaled off the whole dataset would clip everything
        within a hundred metres -- which at this height is all of it."""
        pose = opening_pose(CENTRE, RADIUS)
        assert pose.near < 5.0, pose.near
        assert pose.far > RADIUS, pose.far

    def test_a_small_dataset_is_opened_the_same_way(self):
        pose = opening_pose((0.0, 0.0, 0.0), 40.0)
        assert 0.0 < pose.position[1] < 40.0


class TestTheViewerUsesIt:
    def test_the_scene_carries_the_pose_for_the_viewer_to_apply(self):
        adapter = TilesAdapter()
        adapter.center, adapter.radius = np.asarray(CENTRE), RADIUS
        scene = adapter.sceneFor(object())
        assert scene.pose is not None
        assert scene.pose.position[1] > CENTRE[1]

    def test_a_scene_that_offers_no_pose_still_gets_the_fit(self):
        """Every other adapter is unchanged: no pose means frame the sphere."""
        from OpenGLContext.viewer.adapters.base import ViewerScene
        assert ViewerScene(group=None).pose is None


class TestFrameModelPrefersTheScenesOwnPose:
    def _viewer(self, scene):
        from OpenGLContext.viewer.sceneviewer import ViewerContext
        viewer = ViewerContext.__new__(ViewerContext)
        viewer.options = ViewerOptions(source='tileset.json')
        viewer.scene = scene
        applied = []
        viewer.applyCameraPose = applied.append
        return viewer, applied

    def _scene(self, pose):
        from OpenGLContext.viewer.adapters.base import ViewerScene
        return ViewerScene(group=None, center=CENTRE, radius=RADIUS, pose=pose)

    def test_the_scenes_pose_is_what_the_camera_takes(self):
        pose = opening_pose(CENTRE, RADIUS)
        viewer, applied = self._viewer(self._scene(pose))
        viewer.frameModel(RADIUS)
        assert applied == [pose]

    def test_an_explicit_eye_and_target_still_win(self):
        """`--eye`/`--look-at` are the user saying where to stand."""
        viewer, applied = self._viewer(self._scene(opening_pose(CENTRE, RADIUS)))
        viewer.options.eye = (0.0, 10.0, 0.0)
        viewer.options.look_at = (0.0, 0.0, -10.0)
        viewer.frameModel(RADIUS)
        assert applied[0].position == pytest.approx((0.0, 10.0, 0.0))

    def test_asking_for_a_fit_still_fits(self):
        """`--margin` and friends are a request for the whole-scene fit."""
        viewer, applied = self._viewer(self._scene(opening_pose(CENTRE, RADIUS)))
        viewer.options.margin = 1.5
        viewer.frameModel(RADIUS)
        assert applied[0].position == pytest.approx(fit_sphere(RADIUS, 1.5).position)

    def test_a_scene_without_a_pose_is_framed_as_before(self):
        viewer, applied = self._viewer(self._scene(None))
        viewer.frameModel(RADIUS)
        assert applied[0].position == pytest.approx(fit_sphere(RADIUS).position)


class TestWhereOverTheDatasetItOpens:
    """The camera opens over the middle of the content, not over whichever
    tile happens to come first: in a city-sized dataset that one is a corner,
    and a corner of a city is a park."""

    def _tileset(self):
        """A root spanning 2 km with content tiles across it."""
        import types

        def tile(x, z, children=()):
            bv = types.SimpleNamespace(
                center=np.array([x, 150.0, z]),
                bounding_sphere=lambda c=np.array([x, 150.0, z]): (c, 1000.0))
            return types.SimpleNamespace(
                bounding_volume=bv, children=list(children),
                content_uri='t.b3dm' if not children else None,
                content_uris=[] if children else ['t.b3dm'],
                has_content=not children,
                iter_tiles=None)

        leaves = [tile(x, z) for x in (-900.0, 0.0, 900.0)
                  for z in (-900.0, 0.0, 900.0)]
        root = tile(0.0, 0.0, children=leaves)
        root.has_content = False

        def walk(node=root):
            yield node
            for child in node.children:
                yield from walk(child)
        root.iter_tiles = walk
        return root

    def test_the_aim_is_the_content_tile_nearest_the_middle(self):
        from OpenGLContext.viewer.adapters.tiles import opening_aim
        aim = opening_aim(self._tileset())
        assert aim[0] == pytest.approx(0.0)
        assert aim[2] == pytest.approx(0.0)
        assert aim[1] == pytest.approx(150.0)   # at the content, not below it

    def test_a_tileset_with_no_content_falls_back_to_its_extent(self):
        import types
        bv = types.SimpleNamespace(center=np.array([5.0, 6.0, 7.0]),
                                   bounding_sphere=lambda: (np.array([5.0, 6.0, 7.0]), 10.0))
        empty = types.SimpleNamespace(bounding_volume=bv, children=[],
                                      content_uri=None, content_uris=[],
                                      has_content=False)
        empty.iter_tiles = lambda: iter([empty])
        from OpenGLContext.viewer.adapters.tiles import opening_aim
        assert opening_aim(empty) == pytest.approx((5.0, 6.0, 7.0))
