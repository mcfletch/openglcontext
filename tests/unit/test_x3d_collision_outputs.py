"""X3D's Collision: collideTime and isActive as the walker touches its children.

Each shape inside an enabled Collision group is a scenery body of the physics
service (``x3dcollision.collision_group_bodies``); a ``CollisionReporter``
turns the walker's touches of those bodies into the group's ``isActive`` and
``collideTime``, and those of the enabled groups around it. Walking into one
is in ``test_physicswalk.TestCollisionGroups``.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.x3dcollision import CollisionReporter, collision_group_bodies
from OpenGLContext.scenegraph.basenodes import Collision, Shape, Transform
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


def wall(x=0.0):
    """A wall across the x axis at `x`, two units square"""
    points = np.array([(x, -1, -1), (x, 1, -1), (x, 1, 1), (x, -1, 1)], 'f')
    return Shape(geometry=PBRMesh(positions=points, indices=np.array([0, 1, 2, 0, 2, 3], 'u4')))


def floor():
    points = np.array([(-50, 0, -50), (50, 0, -50), (50, 0, 50), (-50, 0, 50)], 'f')
    return Shape(geometry=PBRMesh(positions=points, indices=np.array([0, 2, 1, 0, 3, 2], 'u4')))


@pytest.fixture
def physics():
    made = Physics(PhysicsDefinition(mode='inline'))
    yield made
    made.close()


def test_each_shape_in_a_group_is_a_body_with_its_groups(physics):
    inner_wall, outer_wall, ground = wall(5.0), wall(-5.0), floor()
    inner = Collision(children=[inner_wall])
    outer = Collision(children=[inner, outer_wall])
    scene = Transform(children=[ground, outer])
    physics.scenery_changed(scene, 1)
    physics.wait_cooked()
    found = collision_group_bodies(physics, scene)
    assert found == {physics.body_for(inner_wall): [inner, outer],
                     physics.body_for(outer_wall): [outer]}


def test_a_scene_without_collision_groups_has_no_bodies_to_report(physics):
    scene = Transform(children=[floor()])
    physics.scenery_changed(scene, 1)
    assert collision_group_bodies(physics, scene) == {}


def test_a_disabled_group_is_not_reported(physics):
    scene = Transform(children=[floor(), Collision(enabled=False, children=[wall()])])
    physics.scenery_changed(scene, 1)
    assert collision_group_bodies(physics, scene) == {}


class Reporter(CollisionReporter):
    """A reporter told what the walker touches rather than asking the world"""

    def __init__(self, groups):
        super().__init__(groups, SimpleNamespace(alive=True))
        self.now_touching = set()

    def touched(self):
        return set(self.now_touching)


def test_a_touch_activates_the_group_and_those_around_it():
    inner, outer = Collision(), Collision()
    reporter = Reporter({'wall': [inner, outer]})
    reporter.now_touching = {'wall'}
    reporter.update(now=12.5)
    assert inner.isActive is True and outer.isActive is True
    assert inner.collideTime == 12.5 and outer.collideTime == 12.5
    reporter.now_touching = set()
    reporter.update(now=13.0)
    assert inner.isActive is False and outer.isActive is False


def test_a_touch_held_sends_no_second_collide_time():
    group = Collision()
    reporter = Reporter({'wall': [group]})
    reporter.now_touching = {'wall'}
    reporter.update(now=1.0)
    reporter.update(now=2.0)
    assert group.collideTime == 1.0


def test_a_group_stays_active_while_another_of_its_bodies_is_touched():
    inner, outer = Collision(), Collision()
    reporter = Reporter({'inner': [inner, outer], 'outer': [outer]})
    reporter.now_touching = {'inner', 'outer'}
    reporter.update(now=1.0)
    reporter.now_touching = {'outer'}
    reporter.update(now=2.0)
    assert inner.isActive is False
    assert outer.isActive is True


def test_a_removed_walker_reports_nothing():
    group = Collision()
    reporter = Reporter({'wall': [group]})
    reporter.walker.alive = False
    reporter.now_touching = {'wall'}
    reporter.update(now=1.0)
    assert 'isActive' not in group.__dict__
