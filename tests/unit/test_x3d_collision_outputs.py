"""X3D's Collision: collideTime and isActive as the walker touches its children.

Each enabled Collision group's geometry is a static body of its own in the
walk's world (``gltf_world.collision_groups``), reported when the walker's
capsule touches it; a ``CollisionReporter`` turns those touches into the
group's ``isActive`` and ``collideTime``, and those of the enabled groups
around it.
"""
from types import SimpleNamespace

import numpy as np

from OpenGLContext.physics import gltf_world
from OpenGLContext.physics.x3dcollision import CollisionReporter
from OpenGLContext.scenegraph.basenodes import Collision, Shape, Transform
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


def wall(x=0.0):
    """A wall across the x axis at `x`, two units square"""
    points = np.array([(x, -1, -1), (x, 1, -1), (x, 1, 1), (x, -1, 1)], 'f')
    return Shape(geometry=PBRMesh(positions=points, indices=np.array([0, 1, 2, 0, 2, 3], 'u4')))


def floor():
    points = np.array([(-50, 0, -50), (50, 0, -50), (50, 0, 50), (-50, 0, 50)], 'f')
    return Shape(geometry=PBRMesh(positions=points, indices=np.array([0, 2, 1, 0, 3, 2], 'u4')))


def test_a_collision_group_is_a_body_of_its_own():
    inner = Collision(children=[wall(5.0)])
    outer = Collision(children=[inner, wall(-5.0)])
    scene = Transform(children=[floor(), outer])
    world, bounds = gltf_world.collision_world_from_scene(scene)
    groups = gltf_world.collision_groups(world)
    assert sorted(len(nodes) for nodes in groups.values()) == [1, 2]
    assert [inner, outer] in groups.values()
    assert world.contact_reporting == 'flagged'
    assert bounds is not None


def test_a_scene_without_collision_groups_reports_nothing():
    world, _bounds = gltf_world.collision_world_from_scene(Transform(children=[floor()]))
    assert gltf_world.collision_groups(world) == {}
    assert world.contact_reporting == 'off'


class Ref(SimpleNamespace):
    pass


def event(phase, a, b):
    return SimpleNamespace(phase=phase, a=Ref(index=a), b=Ref(index=b))


def test_a_touch_activates_the_group_and_those_around_it():
    inner, outer = Collision(), Collision()
    reporter = CollisionReporter({3: [inner, outer]}, walker=7)
    reporter.heard(event('begin', 3, 7), now=12.5)
    assert inner.isActive is True and outer.isActive is True
    assert inner.collideTime == 12.5 and outer.collideTime == 12.5
    reporter.heard(event('end', 3, 7), now=13.0)
    assert inner.isActive is False


def test_touches_of_other_bodies_are_not_reported():
    group = Collision()
    reporter = CollisionReporter({3: [group]}, walker=7)
    reporter.heard(event('begin', 3, 9), now=1.0)
    reporter.heard(event('begin', 2, 7), now=1.0)
    assert 'isActive' not in group.__dict__


def test_the_walker_touching_a_wall_sets_collide_time():
    from OpenGLContext.move.physicsplatform import PhysicsViewPlatform  # noqa: PLC0415 kept with its use
    group = Collision(children=[wall(1.0)])
    world, _bounds = gltf_world.collision_world_from_scene(Transform(children=[floor(), group]))
    platform = PhysicsViewPlatform(world, position=(0.75, 0.0, 0.0), body=True)
    reporter = CollisionReporter(gltf_world.collision_groups(world), platform.character.body)
    world.add_contact_listener(lambda found: reporter.heard(found, now=4.0))
    platform.update(1 / 60.0)
    assert group.isActive is True
    assert group.collideTime == 4.0
