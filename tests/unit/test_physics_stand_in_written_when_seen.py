"""A character's stand-in is written to the world when something can see it, and the world goes
exactly as it goes when the stand-in is written at every step.

Something sees the stand-in when a dynamic body, a trigger or a sensor is within reach of it in a
step, when a ray, a sweep or an overlap reaches it, and when another character's controller looks
near it. The twin of each service here writes its stand-ins at every step.
"""
import math

import numpy as np
import pytest
from omi_physics.character import CharacterCapabilities

from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition

FRAME = 1.0 / 60.0
EVENTS = ('hit', 'touching', 'separate', 'enter', 'stay', 'exit')


class Commands:
    """The place and velocity commands a service sends for its stand-ins, counted."""

    def __init__(self, service: Physics) -> None:
        self.sent: list[str] = []
        stand_ins = {character.body.uid for character in service.characters}
        original = service._send                          # noqa: SLF001 the commands, counted

        def send(command):
            if command.uid in stand_ins and command.op in ('place', 'velocity'):
                self.sent.append(command.op)
            return original(command)
        service._send = send                              # noqa: SLF001 the commands, counted


def service_of(seed: int, written: bool, framed: bool = True, walkers_made: int = 1
               ) -> tuple[Physics, list, dict]:
    """A floor with posts, crates light and heavy, triggers and walkers, made the same for a seed.

    ``written`` makes a twin that writes its stand-ins at every step.
    """
    rng = np.random.default_rng(seed)
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=1.0,
                                        colliders='explicit'))
    if written:
        service._defers_stand_ins = lambda: False         # noqa: SLF001 the twin under comparison
    service.add_static(None, proxy=Proxy.box((80, 1, 80)), translation=(0, -0.5, 0))
    for _ in range(int(rng.integers(3, 10))):
        x, z = rng.uniform(-20, 20, 2)
        service.add_static(None, proxy=Proxy.box(tuple(rng.uniform(0.4, 2.0, 3))),
                           translation=(float(x), 0.6, float(z)))
    crates = []
    for _ in range(int(rng.integers(1, 6))):
        x, z = rng.uniform(-15, 15, 2)
        crates.append(service.add_dynamic(None, proxy=Proxy.box((0.6, 0.6, 0.6)),
                                          translation=(float(x), 0.3, float(z)),
                                          mass=float(rng.choice([15.0, 3000.0]))))
    for _ in range(int(rng.integers(1, 5))):
        x, z = rng.uniform(-15, 15, 2)
        service.add_trigger(None, proxy=Proxy.box((2.0, 2.0, 2.0)),
                            translation=(float(x), 1.0, float(z)))
    caps = CharacterCapabilities(radius=0.3, standHeight=1.7, runSpeed=6.0)
    walkers = []
    for _ in range(walkers_made):
        x, z = rng.uniform(-10, 10, 2)
        walker = service.add_character(capabilities=caps, position=(float(x), 0.05, float(z)))
        walker.framed = framed
        walkers.append(walker)
    heard: dict = {'events': []}
    for event in EVENTS:
        service.addEventHandler(event, function=heard.setdefault(event, _listener(heard, event)))
    if not framed:
        @physics_callback
        def before(step):
            for walker in walkers:
                walker.step(step.dt)
        heard['before'] = before
        service.addEventHandler('before-step', function=before)
    return service, walkers, heard


def _listener(heard: dict, event: str):
    def listen(collision):
        heard['events'].append((event, getattr(collision.body, 'uid', None),
                                getattr(collision.other, 'uid', None),
                                tuple(np.round(np.asarray(collision.normal, dtype='d'), 12))))
    return listen


def steer(rng: np.random.Generator, walkers: list, frame: int) -> None:
    if frame % 40 == 0:
        for walker in walkers:
            angle = float(rng.uniform(0.0, 2.0 * math.pi))
            walker.set_move((math.cos(angle), 0.0, math.sin(angle)),
                            str(rng.choice(['walk', 'run'])))


def looks(service: Physics, walkers: list, rng: np.random.Generator) -> list:
    """Rays, sweeps and overlaps at the walkers and away from them, as numbers to compare."""
    seen = []
    for walker in walkers:
        feet = walker.position
        hit = service.raycast(feet + (0.0, 5.0, 0.0), (0.0, -1.0, 0.0), 10.0)
        seen.append(None if hit is None else (hit.body.uid, hit.distance))
        seen.append(service.sweep_sphere(feet + (-1.5, 1.0, 0.0), (1.0, 0.0, 0.0), 2.5, 0.3))
        seen.append(sorted(body.uid for body in service.overlap(Proxy.sphere(0.5),
                                                                 feet + (0.0, 1.0, 0.0))))
    far = rng.uniform(-30, 30, 3)
    hit = service.raycast((float(far[0]), 10.0, float(far[2])), (0.0, -1.0, 0.0), 20.0)
    seen.append(None if hit is None else (hit.body.uid, hit.distance))
    return seen


def state(service: Physics, walkers: list) -> list:
    # The runtime's world as it stands: physics.world would write the stand-ins first.
    world = service.worker.runtime.world
    return [walker.position.tolist() for walker in walkers] + [
        world.position[i].tolist() for i in range(len(world.position))
        if world.motion_type[i] == 2]


def throw(service: Physics, walkers: list, rng: np.random.Generator) -> None:
    """A crate thrown at the first walker."""
    target = walkers[0].position + (0.0, 1.0, 0.0)
    start = target + (3.0, 0.5, 0.0)
    crate = service.add_dynamic(None, proxy=Proxy.box((0.4, 0.4, 0.4)),
                                translation=tuple(float(v) for v in start), mass=10.0)
    crate.set_velocity((-9.0, 0.0, 0.0))


@pytest.mark.parametrize(('framed', 'walkers_made'), [(True, 1), (False, 1), (True, 2)],
                         ids=['framed', 'stepped in the step', 'two walkers'])
@pytest.mark.parametrize('seed', range(5))
def test_the_world_goes_as_when_the_stand_in_is_written_every_step(seed, framed, walkers_made):
    lazy, lazy_walkers, lazy_heard = service_of(seed, False, framed, walkers_made)
    eager, eager_walkers, eager_heard = service_of(seed, True, framed, walkers_made)
    counted = [Commands(lazy), Commands(eager)]
    rngs = [np.random.default_rng(100 + seed) for _ in range(2)]
    looked = [np.random.default_rng(200 + seed) for _ in range(2)]
    try:
        for frame in range(300):
            seen = []
            for service, walkers, rng, eye in ((lazy, lazy_walkers, rngs[0], looked[0]),
                                               (eager, eager_walkers, rngs[1], looked[1])):
                steer(rng, walkers, frame)
                if frame == 200:
                    throw(service, walkers, rng)
                service.frame(FRAME)
                seen.append(looks(service, walkers, eye) if frame % 10 == 0 else None)
            assert state(lazy, lazy_walkers) == state(eager, eager_walkers), frame
            assert seen[0] == seen[1], frame
            assert lazy_heard['events'] == eager_heard['events'], frame
        if walkers_made == 1:
            assert len(counted[0].sent) < len(counted[1].sent) / 2
        else:
            assert counted[0].sent == counted[1].sent
    finally:
        lazy.close()
        eager.close()


def test_a_walker_with_nothing_near_writes_its_stand_in_once_and_then_not_again():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=1.0))
    service.add_static(None, proxy=Proxy.box((200, 1, 200)), translation=(0, -0.5, 0))
    walker = service.add_character(position=(0.0, 0.05, 0.0))
    for _ in range(30):
        service.frame(FRAME)
    commands = Commands(service)
    walker.set_move((1.0, 0.0, 0.2), 'run')
    for _ in range(120):
        service.frame(FRAME)
    assert walker.position[0] > 5.0
    # It stood still before it ran, so the world's stand-in waits where it stood, at rest.
    assert commands.sent == []
    service.close()


def test_a_ray_at_the_walker_finds_the_stand_in_where_the_walker_is():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=1.0))
    service.add_static(None, proxy=Proxy.box((200, 1, 200)), translation=(0, -0.5, 0))
    walker = service.add_character(position=(0.0, 0.05, 0.0))
    walker.set_move((1.0, 0.0, 0.0), 'run')
    for _ in range(90):
        service.frame(FRAME)
    feet = walker.position
    hit = service.raycast(feet + (0.0, 5.0, 0.0), (0.0, -1.0, 0.0), 10.0)
    assert hit is not None and hit.body is walker.body
    top = walker.controller.position[1] + 0.5 * walker.capabilities.standHeight
    assert hit.point[1] == pytest.approx(top, abs=0.06)
    service.close()


def test_a_crate_in_reach_writes_the_stand_in_and_is_pushed():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=1.0))
    service.add_static(None, proxy=Proxy.box((200, 1, 200)), translation=(0, -0.5, 0))
    crate = service.add_dynamic(None, proxy=Proxy.box((0.8, 0.8, 0.8)), translation=(6.0, 0.4, 0.0),
                                mass=20.0)
    walker = service.add_character(position=(0.0, 0.05, 0.0))
    for _ in range(30):
        service.frame(FRAME)
    commands = Commands(service)
    walker.set_move((1.0, 0.0, 0.0), 'walk')
    for _ in range(240):
        service.frame(FRAME)
    assert crate.position[0] > 7.0
    assert 'place' in commands.sent
    service.close()


def runner() -> tuple[Physics, object]:
    """A lone walker that has run 5 metres or so, its stand-in waiting where it stood."""
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0, maxCatchUp=1.0))
    service.add_static(None, proxy=Proxy.box((200, 1, 200)), translation=(0, -0.5, 0))
    walker = service.add_character(position=(0.0, 0.05, 0.0))
    for _ in range(30):
        service.frame(FRAME)
    walker.set_move((1.0, 0.0, 0.0), 'run')
    for _ in range(90):
        service.frame(FRAME)
    return service, walker


def test_the_raw_world_holds_the_stand_in_where_the_walker_is():
    service, walker = runner()
    x = float(walker.controller.position[0])
    assert float(service.world.position[service.slot_of(walker.body)][0]) == pytest.approx(x, abs=0.05)
    service.close()


def test_run_and_body_at_see_the_stand_in_where_the_walker_is():
    service, walker = runner()
    x = float(walker.controller.position[0])
    found = service.run(lambda world: float(world.position[service.index_of(walker.body)][0]))
    assert found.result(1.0) == pytest.approx(x, abs=0.05)
    service.close()
