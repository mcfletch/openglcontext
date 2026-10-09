"""A document's WALK viewer stands on the ground and falls under gravity.

X3D (19775-1, 23.4.4 NavigationInfo): WALK navigation should "provide some
form of terrain following and gravity". X_ITE drops a WALK viewer onto the
geometry below it before its first capture.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.move import terrainfollow

#: Two triangles making the square y = 0, x and z from -5 to 5.
FLOOR = np.array([[(-5, 0, -5), (5, 0, -5), (5, 0, 5)],
                  [(-5, 0, -5), (5, 0, 5), (-5, 0, 5)]], dtype=float)
DOWN = np.array([0.0, -1.0, 0.0])


def test_the_clearance_is_the_distance_to_the_ground_below():
    found = terrainfollow.clearance((0, 3, 0), DOWN, 0.25, [(FLOOR, np.identity(4))])
    assert found == pytest.approx(3.0)


def test_nothing_below_has_no_clearance():
    assert terrainfollow.clearance((20, 3, 0), DOWN, 0.25, [(FLOOR, np.identity(4))]) is None


def test_ground_above_is_not_below():
    assert terrainfollow.clearance((0, -1, 0), DOWN, 0.25, [(FLOOR, np.identity(4))]) is None


def test_the_ground_is_found_within_the_collision_radius():
    """A gap under the eye narrower than the avatar is stood over"""
    left = FLOOR.copy()
    left[..., 0] = np.clip(left[..., 0], -5, -0.1)
    right = FLOOR.copy()
    right[..., 0] = np.clip(right[..., 0], 0.1, 5)
    found = terrainfollow.clearance((0, 2, 0), DOWN, 0.25,
                                    [(left, np.identity(4)), (right, np.identity(4))])
    assert found == pytest.approx(2.0)


def test_the_ground_is_placed_by_its_matrix():
    """Row-vector matrices, as the scenegraph's paths give them"""
    raised = np.identity(4)
    raised[3, 1] = 1.0
    found = terrainfollow.clearance((0, 3, 0), DOWN, 0.25, [(FLOOR, raised)])
    assert found == pytest.approx(2.0)


def test_a_viewer_above_its_eye_height_falls_under_gravity():
    follower = terrainfollow.TerrainFollower(landed=True)
    moved = follower.step(clearance=10.0, dt=0.5, eye_height=1.6, step_height=0.75)
    assert follower.speed == pytest.approx(-terrainfollow.GRAVITY * 0.5)
    assert moved == pytest.approx(-terrainfollow.GRAVITY * 0.25)


def test_a_falling_viewer_stops_at_its_eye_height():
    follower = terrainfollow.TerrainFollower(landed=True)
    moved = follower.step(clearance=2.0, dt=1.0, eye_height=1.6, step_height=0.75)
    assert moved == pytest.approx(-0.4)
    assert follower.speed == 0.0


def test_a_viewer_with_nothing_below_falls():
    follower = terrainfollow.TerrainFollower(landed=True)
    assert follower.step(clearance=None, dt=0.1, eye_height=1.6, step_height=0.75) < 0


def test_a_viewer_steps_up_onto_a_low_rise():
    follower = terrainfollow.TerrainFollower(landed=True)
    assert follower.step(clearance=1.2, dt=0.1, eye_height=1.6,
                         step_height=0.75) == pytest.approx(0.4)


def test_a_rise_taller_than_a_step_is_not_climbed():
    follower = terrainfollow.TerrainFollower(landed=True)
    assert follower.step(clearance=0.5, dt=0.1, eye_height=1.6, step_height=0.75) == 0.0


def test_a_viewer_not_yet_landed_is_placed_on_the_ground():
    """Until it first has ground below it after a bind, the viewer falls, and
    is put on the ground below as soon as there is some, whatever the clock"""
    follower = terrainfollow.TerrainFollower()
    assert follower.step(clearance=None, dt=0.1, eye_height=1.6, step_height=0.75) < 0
    assert not follower.landed
    assert follower.step(clearance=5.5, dt=0.0, eye_height=1.6,
                         step_height=0.75) == pytest.approx(-3.9)
    assert follower.landed
    assert follower.speed == 0.0


@pytest.mark.parametrize('types, walks', [
    (['WALK', 'ANY'], True), (['"WALK"'], True), (['walk'], True),
    (['EXAMINE', 'WALK'], False), (['ANY', 'WALK'], False), ([], False)])
def test_walking_is_the_first_type(types, walks):
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    assert terrainfollow.walking(x3d.NavigationInfo(type=types)) is walks


def _document(navigation, ground="<Box size='10 1 10'/>", wrap=None):
    shape = ("<Transform translation='0 -0.5 0'><Shape><Appearance><Material/></Appearance>"
             "%s</Shape></Transform>" % ground)
    if wrap:
        shape = wrap % shape
    return Loader.loads(
        ("<X3D version='3.3'><Scene><NavigationInfo type='%s'/>"
         "<Viewpoint position='0 5 3'/>%s</Scene></X3D>" % (navigation, shape)).encode(),
        'scene.x3d')


def _eye_height(scene):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        drawn_image(context)
        return float(context.platform.position[1])


def test_a_walk_document_stands_its_viewer_on_the_ground():
    assert _eye_height(_document('"WALK" "ANY"')) == pytest.approx(1.6, abs=0.01)


def test_an_examine_document_leaves_its_viewer_where_the_viewpoint_puts_it():
    assert _eye_height(_document('"EXAMINE" "ANY"')) == pytest.approx(5.0)


def test_a_disabled_collision_group_is_not_ground():
    """With nothing below, the viewer falls"""
    height = _eye_height(_document('"WALK"', wrap="<Collision enabled='false'>%s</Collision>"))
    assert 1.7 < height < 5.0


def test_a_collision_proxy_is_ground_in_place_of_its_children():
    proxy = ("<Collision><Shape containerField='proxy'><Box size='10 1 10'/></Shape>"
             "<Transform translation='0 2 0'>%s</Transform></Collision>")
    assert _eye_height(_document('"WALK"', wrap=proxy)) == pytest.approx(2.1, abs=0.01)


def test_the_triangles_tested_are_those_below_the_eye_however_large_the_scene(
        check_scaling, monkeypatch):
    """The bounds of every shape are tested at once; only those reaching
    below the eye give their triangles"""
    from types import SimpleNamespace  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.basenodes import Box, Shape  # noqa: PLC0415 kept with its use
    corners = np.array([(x, y, z, 1.0) for x in (-0.5, 0.5) for y in (-0.5, 0.5)
                        for z in (-0.5, 0.5)])

    def prepare(count):
        shapes = [Shape(geometry=Box(size=(1, 1, 1))) for _ in range(count)]
        matrices = np.tile(np.identity(4), (count, 1, 1))
        matrices[:, 3, 0] = np.arange(count) * 3.0
        gathered = SimpleNamespace(
            paths=[None] * count, nodes=shapes, matrices=matrices,
            points=np.tile(corners, (count, 1, 1)),
            bounded=np.ones(count, dtype=bool), drawing=np.ones(count, dtype=bool))
        return lambda: len(list(terrainfollow.grounds_below(gathered, (0, 3, 0), DOWN, 0.25)))
    # The paths here are stand-ins: every shape is ground, placed as it is
    monkeypatch.setattr(terrainfollow, '_collision_state', lambda path: (True, None))
    monkeypatch.setattr(terrainfollow, '_matrix', lambda path: np.identity(4))
    found = check_scaling(prepare, n=500, most=1.0, measure='count')
    assert found.costs == (1.0, 1.0)
