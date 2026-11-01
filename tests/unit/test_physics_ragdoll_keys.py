"""The keys of tutorials/physics/physics_ragdoll.py reach the yard's actions."""
from .test_physics_tutorials import press, running


def test_the_keys_get_up_knock_down_and_toggle_power(gl_context):
    with running('physics', 'physics_ragdoll') as run:
        yard = run.context.yard
        figure = yard.figure
        run.seconds(1.0)
        assert figure.ragdoll.mode.value == 'limp' and not figure.following   # the opening left him down

        press(run, 'g')
        assert figure.following
        assert run.until(lambda: figure.ragdoll.mode.value == 'powered', seconds=3.0)

        press(run, 'k')
        assert not figure.following
        assert run.until(lambda: figure.ragdoll.mode.value == 'limp', seconds=3.0)

        press(run, 'p')
        assert figure.following and figure.ragdoll.mode.value in ('kinematic', 'powered')
        press(run, 'p')
        assert run.until(lambda: figure.ragdoll.mode.value == 'kinematic', seconds=3.0)


def test_the_h_key_strikes_the_chest(gl_context):
    with running('physics', 'physics_ragdoll') as run:
        yard = run.context.yard
        calls = []
        hit = yard.figure.ragdoll.hit
        yard.figure.ragdoll.hit = lambda bone, impulse: (calls.append((bone, impulse)), hit(bone, impulse))[1]
        press(run, 'h')
        assert len(calls) == 1
        assert calls[0][1][2] < 0.0                        # along -z, from the front
