"""A framed character takes the same fixed steps as the world, whatever the frame rate.

The service steps each framed character once for each fixed step the frame owes,
with the fixed time step, so a walk or a jump traces the same path at 30, 60 and
144 frames a second, and the character is stepped as often as the world.
"""
import numpy as np
import pytest

from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

pytestmark = pytest.mark.engines('omi', 'jolt')

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
#: Seconds at which every frame rate below has a frame boundary: multiples of 1/6.
SAMPLES = (0.5, 1.0, 1.5, 2.0, 2.5)


def make() -> Physics:
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0))
    service.add_static(surfaces.shape(surfaces.block((60, 1, 60)), LOOK,
                                      translation=(0, -0.5, 0)), proxy='box')
    return service


def script(character, now):
    """The input a player gives at ``now`` seconds: walk, jump at 1 s, turn at 1.5 s."""
    if now < 0.5:
        character.set_move((0, 0, 0))
    elif now < 1.5:
        character.set_move((1, 0, 0), mode='run')
    else:
        character.set_move((0, 0, -1), mode='walk')
    if abs(now - 1.0) < 1e-9 and character.grounded:
        character.jump()


def trajectory(rate):
    """Where the feet are at each of :data:`SAMPLES`, stepping at ``rate`` frames a second."""
    physics = make()
    try:
        me = physics.add_character(position=(0, 0.05, 0))
        frames = int(round(SAMPLES[-1] * rate))
        seen = {}
        for frame in range(frames + 1):
            now = frame / rate
            script(me, now)
            for sample in SAMPLES:
                if abs(now - sample) < 1e-9:
                    seen[sample] = me.position.copy()
            physics.frame(1.0 / rate)
        return seen
    finally:
        physics.close()


def test_a_walk_and_a_jump_trace_the_same_path_at_30_60_and_144_frames_a_second():
    at_60 = trajectory(60)
    assert at_60[2.5][0] > 3.0                                    # it ran
    for rate in (30, 144):
        other = trajectory(rate)
        for sample in SAMPLES:
            assert np.allclose(other[sample], at_60[sample], rtol=0.0, atol=1e-9), (rate, sample)


def test_a_character_takes_the_same_steps_as_a_busy_world():
    physics = make()
    try:
        ball = surfaces.shape(surfaces.sphere(0.3), LOOK, translation=(5, 4, 5))
        physics.add_dynamic(ball, restitution=0.9)
        me = physics.add_character(position=(0, 0.05, 0))
        world_steps = []

        @physics_callback
        def stepped(step):
            world_steps.append(step)

        physics.addEventHandler('before-step', function=stepped)
        taken = []
        # The omi frame steps the character's controller; the Jolt frame runs the
        # character's code around each tick the world runs.
        name = '_after_tick' if physics.engine.name == 'jolt' else 'update'
        owner = me if name == '_after_tick' else me._controller
        update = getattr(owner, name)

        def counted(dt):
            taken.append(dt)
            return update(dt)

        setattr(owner, name, counted)
        me.set_move((1, 0, 0))
        for rate in (30, 144, 60, 45):
            for _ in range(rate // 3):
                before_world, before_me = len(world_steps), len(taken)
                physics.frame(1.0 / rate)
                assert len(taken) - before_me == len(world_steps) - before_world
        assert len(taken) > 100
        assert all(dt == pytest.approx(1.0 / 120.0) for dt in taken)
    finally:
        physics.close()


def test_a_frame_shorter_than_a_step_leaves_the_character_where_it_was():
    physics = make()
    try:
        me = physics.add_character(position=(0, 0.05, 0))
        for _ in range(60):
            physics.frame(1 / 60)
        me.set_move((1, 0, 0), mode='run')
        here = me.position.copy()
        physics.frame(0.004)                                      # under the 1/120 s step
        assert np.array_equal(me.position, here)
        physics.frame(0.0045)                                     # the remainder makes a step
        assert me.position[0] > here[0]
    finally:
        physics.close()


def test_drop_remainder_forgets_the_characters_part_step_too():
    physics = make()
    try:
        me = physics.add_character(position=(0, 0.05, 0))
        for _ in range(60):
            physics.frame(1 / 60)
        me.set_move((1, 0, 0), mode='run')
        physics.frame(0.006)
        here = me.position.copy()
        physics.drop_remainder()
        physics.frame(0.004)                                      # 0.010 s with the remainder kept
        assert np.array_equal(me.position, here)
    finally:
        physics.close()


def test_the_node_is_drawn_between_the_last_two_steps():
    from OpenGLContext.scenegraph import basenodes
    physics = make()
    try:
        node = basenodes.Transform()
        me = physics.add_character(node=node, position=(0, 0.05, 0))
        for _ in range(60):
            physics.frame(1 / 60)
        me.set_move((1, 0, 0), mode='run')
        for _ in range(30):
            physics.frame(1 / 60)
        before = me.position.copy()
        physics.frame(1 / 120 + 1 / 240)                          # one step and half of the next
        after = me.position.copy()
        drawn = np.asarray(node.translation)
        assert drawn[0] == pytest.approx(before[0] + 0.5 * (after[0] - before[0]), abs=1e-6)
        assert me.drawn_position[0] == pytest.approx(drawn[0])
    finally:
        physics.close()


def test_a_correction_that_takes_a_step_back_is_drawn_without_the_step():
    physics = make()
    try:
        me = physics.add_character(position=(0, 0.05, 0))
        for _ in range(60):
            physics.frame(1 / 60)
        me.set_move((1, 0, 0), mode='run')
        physics.frame(1 / 120 + 1 / 240)                          # one step and half the next
        assert me.drawn_position[0] < me.position[0]              # drawn half a step behind
        me._controller.position[0] -= 1.0                          # a host pushes it back a metre
        assert me.drawn_position[0] == pytest.approx(me.position[0])
    finally:
        physics.close()


def test_a_characters_step_handlers_run_around_each_of_its_steps():
    """A rule that sets the move before each step drives that step, and one after it sees where
    the step left the character: the order holds for every step of a frame."""
    physics = make()
    try:
        me = physics.add_character(position=(0, 0.05, 0))
        for _ in range(60):
            physics.frame(1 / 60)
        order = []

        def before(step):
            assert step.character is me
            order.append(('before', step.dt, float(me.position[0])))
            me.set_move((1, 0, 0), mode='run', speed=6.0 * (1 + len(order) // 2))

        def after(step):
            order.append(('after', step.dt, float(me.position[0])))

        me.addEventHandler('before-step', before)
        me.addEventHandler('after-step', after)
        physics.frame(1 / 30)                                     # four steps of 1/120 s
        assert [name for name, _dt, _x in order] == ['before', 'after'] * 4
        assert all(dt == pytest.approx(1 / 120) for _name, dt, _x in order)
        moved = [after_x - before_x for (_b, _d, before_x), (_a, _e, after_x)
                 in zip(order[::2], order[1::2], strict=True)]
        assert moved == sorted(moved) and moved[0] > 0.0          # each step's own speed
        assert all(order[2 * n + 2][2] == order[2 * n + 1][2] for n in range(3))
        me.step(0.01)                                             # a step taken by hand too
        assert [name for name, _dt, _x in order[-2:]] == ['before', 'after']
        assert order[-1][1] == pytest.approx(0.01)
        me.addEventHandler('before-step', None)
        me.step(0.01)
        assert order[-1][0] == 'after'
    finally:
        physics.close()
