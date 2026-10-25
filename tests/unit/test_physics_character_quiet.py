"""A character that has not moved sends the world nothing.

The stand-in is placed by command each time its character is stepped. A walker
standing in a forest is stepped every frame, and a command per frame keeps the
world's thread stepping 230,000 trunks to find out that nothing moved.
"""
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


@pytest.fixture
def service():
    made = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0))
    made.add_static(None, proxy=Proxy.box((40, 1, 40)), translation=(0, -0.5, 0))
    yield made
    made.close()


class Sent:
    """The commands a service sends its world, counted."""

    def __init__(self, service):
        self.commands = []
        original = service._send

        def send(command):
            self.commands.append(command.op)
            return original(command)

        service._send = send


def test_a_standing_character_sends_no_commands(service):
    me = service.add_character(position=(0, 0.05, 0))
    for _ in range(60):
        service.frame(1 / 60)
    sent = Sent(service)
    for _ in range(30):
        service.frame(1 / 60)
    assert sent.commands == []
    assert me.grounded


def test_a_character_that_moves_places_its_stand_in_each_frame(service):
    me = service.add_character(position=(0, 0.05, 0))
    for _ in range(60):
        service.frame(1 / 60)
    sent = Sent(service)
    me.set_move((1, 0, 0))
    for _ in range(10):
        service.frame(1 / 60)
    assert sent.commands.count('place') == 10
    assert sent.commands.count('velocity') == 10


def test_a_character_that_stops_sends_nothing_once_it_has_rested(service):
    me = service.add_character(position=(0, 0.05, 0))
    me.set_move((1, 0, 0))
    for _ in range(30):
        service.frame(1 / 60)
    me.set_move((0, 0, 0))
    for _ in range(30):
        service.frame(1 / 60)
    sent = Sent(service)
    for _ in range(30):
        service.frame(1 / 60)
    assert sent.commands == []
    assert service.worker.runtime.world.linear_velocity[service.index_of(me.body)] \
        == pytest.approx((0.0, 0.0, 0.0))
