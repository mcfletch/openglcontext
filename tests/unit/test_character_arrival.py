"""A character sent along a route of points, and told when it reaches the end."""
import numpy as np
import pytest

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.roadcourse import RoadCourse

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
FRAME = 1 / 60
ROUTE = [(0.0, 0.0, 0.0), (0.0, 0.0, -4.0), (3.0, 0.0, -4.0)]


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=120.0))
    service.add_static(surfaces.shape(surfaces.block((60, 1, 60)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box')
    yield service
    service.close()


def run_for(physics, seconds):
    for _ in range(int(round(seconds / FRAME))):
        physics.frame(FRAME)


class Ears:
    def __init__(self):
        self.heard = []

    def arrived(self, character):
        self.heard.append(character)


def test_a_list_of_points_is_a_route_the_character_walks_to_its_end(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    run_for(physics, 0.3)
    me.run_along(ROUTE, speed=2.0, mode='walk')
    run_for(physics, 6.0)
    assert np.allclose(me.position[[0, 2]], (3.0, -4.0), atol=0.4)
    assert np.hypot(me.velocity[0], me.velocity[2]) < 0.2


def test_arriving_is_told_once_and_the_character_stops(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    ears = Ears()
    me.addEventHandler('arrived', ears.arrived)
    me.run_along(ROUTE, speed=3.0, mode='walk')
    run_for(physics, 1.0)
    assert ears.heard == []
    assert not me.arrived
    run_for(physics, 5.0)
    assert ears.heard == [me]
    assert me.arrived


def test_a_new_route_is_told_again_when_it_ends(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    ears = Ears()
    me.addEventHandler('arrived', ears.arrived)
    me.run_along(ROUTE, speed=3.0, mode='walk')
    run_for(physics, 5.0)
    me.run_along([tuple(me.position), (3.0, 0.0, 0.0)], speed=3.0, mode='walk')
    assert not me.arrived
    run_for(physics, 4.0)
    assert ears.heard == [me, me]


def test_a_closed_course_is_never_arrived_at(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    ears = Ears()
    me.addEventHandler('arrived', ears.arrived)
    loop = RoadCourse([(0, 0, 0), (0, 0, -4), (4, 0, -4), (4, 0, 0)], closed=True)
    me.run_along(loop, speed=4.0)
    run_for(physics, 8.0)
    assert ears.heard == []
    assert not me.arrived


def test_a_character_on_no_route_has_not_arrived(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    run_for(physics, 0.2)
    assert not me.arrived
