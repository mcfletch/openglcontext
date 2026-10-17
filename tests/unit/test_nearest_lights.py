"""When a scene has more lights than the shader has slots, the nearest bind.

A row of lamps along a corridor is the case: the lamps lighting the part in view are the
ones next to the camera, whatever order the scene lists them in.
"""
import numpy as np

from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph.basenodes import DirectionalLight, PointLight, SpotLight


class Path:
    """A path to one node, standing where its transform puts it."""

    def __init__(self, node, at=(0.0, 0.0, 0.0)):
        self.node = node
        matrix = np.eye(4)
        matrix[3, :3] = at                        # row-vector convention: translation in the last row
        self.matrix = matrix

    def __getitem__(self, index):
        return self.node

    def transformMatrix(self):
        return self.matrix


class Scene:
    def __init__(self, paths):
        self.paths = paths

    def layerPaths(self, _kind):
        return self.paths


def lamps(paths, ceiling, view=None):
    view = np.eye(4) if view is None else view
    return [light for light, _path, _matrix in
            FlatPass.sceneLamps(Scene(paths), view, ceiling)]


def point(at, **named):
    return Path(PointLight(location=(0, 0, 0), **named), at)


def test_lights_within_the_ceiling_bind_in_the_order_the_scene_lists_them():
    paths = [point((0, 0, -d)) for d in (50, 10, 30)]
    assert lamps(paths, 8) == [p.node for p in paths]


def test_past_the_ceiling_the_nearest_lights_bind():
    paths = [point((0, 0, -d)) for d in (90, 10, 70, 30, 50, 20, 80, 40, 60, 100)]
    bound = lamps(paths, 4)
    assert [round(float(-p.matrix[3, 2])) for p in paths if p.node in bound] == [10, 30, 20, 40]
    assert len(bound) == 4


def test_nearest_is_measured_from_the_camera_not_the_origin():
    paths = [point((0, 0, -d)) for d in (10, 400, 410, 420, 430)]
    view = np.eye(4)
    view[3, 2] = 410.0                            # a camera 410 m down the hill
    near = lamps(paths, 3, view)
    assert [round(float(-p.matrix[3, 2])) for p in paths if p.node in near] == [400, 410, 420]


def test_a_directional_light_is_bound_first_wherever_it_is_listed():
    sun = DirectionalLight(direction=(0, -1, 0))
    paths = [point((0, 0, -d)) for d in (5, 6, 7, 8)] + [Path(sun)]
    bound = lamps(paths, 3)
    assert sun in bound and len(bound) == 3


def test_a_light_that_is_off_is_not_bound_in_the_place_of_one_that_is_on():
    off = point((0, 0, -1))
    off.node.on = False
    paths = [off] + [point((0, 0, -d)) for d in (5, 6, 7)]
    assert off.node not in lamps(paths, 3)


def test_spot_lights_are_chosen_by_how_near_they_are_too():
    spots = [Path(SpotLight(location=(0, 0, 0)), (0, 0, -d)) for d in (90, 10, 50)]
    assert [round(float(-p.matrix[3, 2])) for p in spots if p.node in lamps(spots, 2)] == [10, 50]
