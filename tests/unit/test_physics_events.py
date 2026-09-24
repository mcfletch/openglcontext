"""Collision subscriptions (:mod:`OpenGLContext.physics.events`).

A game registers a callback for a body, several bodies or every body, and is
called once per collision on the main thread, with the scenegraph objects
already in hand and the normal turned to face the body it subscribed to. These
tests drive real ``omi_physics`` worlds through a :class:`PhysicsManager`.
"""
import logging

import numpy as np
import pytest

from omi_physics import model
from omi_physics.contactevents import BodyRef
from omi_physics.raycast import raycast

from OpenGLContext.physics import events
from OpenGLContext.physics.manager import PhysicsManager
from OpenGLContext.physics.threaded import ThreadedPhysicsManager
from OpenGLContext.scenegraph.physicsbody import PhysicsBody
from OpenGLContext.scenegraph.transform import Transform

STEP = 1.0 / 120.0
GRAVITY = model.Gravity(gravity=9.81, direction=(0, -1, 0))


def manager(cls=PhysicsManager, **kw):
    return cls(gravity=GRAVITY, fixed_dt=STEP, sleep_enabled=False, **kw)


def add_floor(mgr, restitution=0.0):
    world = mgr.world
    material = world.add_material(model.Material(restitution=restitution,
                                                 restitutionCombine=model.MAXIMUM))
    shape = world.add_shape(model.Shape.box((40, 1, 40)))
    return mgr.add(PhysicsBody(Transform(translation=(0, -0.5, 0)),
                               model.Motion(type=model.STATIC),
                               model.Collider(shape=shape, physicsMaterial=material)))


def add_crate(mgr, position=(0, 0.8, 0), size=(1, 1, 1), shape=None, mass=1.0):
    world = mgr.world
    index = world.add_shape(shape or model.Shape.box(size))
    return mgr.add(PhysicsBody(Transform(translation=position),
                               model.Motion(type=model.DYNAMIC, mass=mass),
                               model.Collider(shape=index)))


def run(mgr, seconds, frame=1.0 / 60.0):
    for _ in range(round(seconds / frame)):
        mgr.advance(frame)


class TestOneBody:
    @pytest.mark.parametrize('floor_first', [True, False])
    def test_a_crate_hears_its_landing_once_pushed_up(self, floor_first) -> None:
        mgr = manager()
        if floor_first:
            floor = add_floor(mgr)
            crate = add_crate(mgr)
        else:
            crate = add_crate(mgr)
            floor = add_floor(mgr)
        heard = []
        mgr.events.subscribe(heard.append, body=crate)
        run(mgr, 1.0)
        assert len(heard) == 1
        hit = heard[0]
        assert (hit.kind, hit.phase) == ('contact', 'begin')
        assert hit.body is crate and hit.other is floor
        assert hit.node is crate.transform and hit.other_node is floor.transform
        assert np.allclose(hit.normal, (0, 1, 0), atol=1e-6)
        assert hit.approach > 1.0
        assert hit.impulse > 0.0

    def test_the_transform_names_its_body(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)
        heard = []
        mgr.events.subscribe(heard.append, body=crate.transform)
        run(mgr, 1.0)
        assert [hit.body for hit in heard] == [crate]

    def test_a_resting_body_only_hears_blows_above_the_threshold(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, phases=('begin', 'persist'),
                             above=0.5)
        run(mgr, 0.5)
        assert heard == []
        mgr.world.linear_velocity[crate.index] = (0, 3, 0)
        run(mgr, 1.0)
        assert [hit.phase for hit in heard] == ['begin']

    def test_an_end_always_passes_the_threshold(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, phases=('begin', 'end'),
                             above=100.0)
        run(mgr, 0.2)
        mgr.world.linear_velocity[crate.index] = (0, 3, 0)
        run(mgr, 0.1)
        assert [hit.phase for hit in heard] == ['end']

    def test_among_narrows_the_other_side(self) -> None:
        mgr = manager()
        floor = add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        ball = add_crate(mgr, position=(0, 2.0, 0), shape=model.Shape.sphere(0.2))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, among=[ball])
        run(mgr, 1.0)
        assert [hit.other for hit in heard] == [ball]
        assert floor not in [hit.other for hit in heard]

    def test_skip_static_leaves_out_the_ground(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        ball = add_crate(mgr, position=(0, 2.0, 0), shape=model.Shape.sphere(0.2))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, skip_static=True)
        run(mgr, 1.0)
        assert [hit.other for hit in heard] == [ball]
        # The ball lands on top, so the crate is pushed down.
        assert heard[0].normal[1] == pytest.approx(-1.0, abs=1e-6)


class TestManyBodies:
    def test_everything_hears_each_pair_once(self) -> None:
        mgr = manager()
        add_floor(mgr)
        add_crate(mgr, position=(0, 0.5, 0))
        add_crate(mgr, position=(0, 2.0, 0), shape=model.Shape.sphere(0.2))
        heard = []
        mgr.events.subscribe(heard.append)
        run(mgr, 1.0)
        pairs = [(hit.body, hit.other) for hit in heard]
        assert len(pairs) == 2
        assert len({frozenset(pair) for pair in pairs}) == 2
        # Oriented to the lower index of the two.
        for hit in heard:
            assert hit.body.index < hit.other.index

    def test_a_set_of_bodies_hears_their_meeting_once(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        ball = add_crate(mgr, position=(0, 2.0, 0), shape=model.Shape.sphere(0.2))
        heard = []
        mgr.events.subscribe(heard.append, body=[crate, ball], skip_static=True)
        run(mgr, 1.0)
        assert [(hit.body, hit.other) for hit in heard] == [(crate, ball)]

    def test_no_bounce_is_lost_at_a_low_frame_rate(self) -> None:
        def bounces(frame):
            mgr = manager()
            add_floor(mgr, restitution=0.6)
            ball = add_crate(mgr, position=(0, 2, 0), shape=model.Shape.sphere(0.2))
            heard = []
            mgr.events.subscribe(heard.append, body=ball)
            run(mgr, 3.0, frame)
            return [round(hit.time, 6) for hit in heard]

        at_120 = bounces(1.0 / 120.0)
        assert len(at_120) >= 3
        assert bounces(1.0 / 20.0) == at_120


class TestTriggers:
    def pad(self, mgr):
        shape = mgr.world.add_shape(model.Shape.box((4, 1, 4)))
        return mgr.add(PhysicsBody(Transform(translation=(0, 0.5, 0)),
                                   model.Motion(type=model.STATIC),
                                   trigger=model.Trigger(shape=shape)))

    def test_a_pressure_plate_hears_what_steps_on_and_off(self) -> None:
        mgr = manager()
        add_floor(mgr)
        pad = self.pad(mgr)
        crate = add_crate(mgr, position=(0, 2, 0))
        heard = []
        mgr.events.subscribe(heard.append, body=pad, kinds=('trigger',),
                             phases=('enter', 'exit'))
        run(mgr, 1.0)
        mgr.world.linear_velocity[crate.index] = (0, 8, 0)
        run(mgr, 0.3)
        assert [(hit.kind, hit.phase, hit.other) for hit in heard] == [
            ('trigger', 'enter', crate), ('trigger', 'exit', crate)]
        assert heard[0].body is pad and heard[0].node is pad.transform

    def test_the_default_phase_of_a_trigger_is_enter(self) -> None:
        mgr = manager()
        pad = self.pad(mgr)
        crate = add_crate(mgr, position=(0, 2, 0))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, kinds=('trigger',))
        run(mgr, 1.0)
        assert [(hit.phase, hit.body, hit.other) for hit in heard] == [
            ('enter', crate, pad)]


class TestLifetime:
    def test_cancelling_stops_the_callbacks(self) -> None:
        mgr = manager()
        add_floor(mgr, restitution=0.6)
        ball = add_crate(mgr, position=(0, 2, 0), shape=model.Shape.sphere(0.2))
        heard = []
        subscription = mgr.events.subscribe(heard.append, body=ball)
        run(mgr, 0.7)
        assert len(heard) == 1
        subscription.cancel()
        assert not subscription.active
        run(mgr, 2.0)
        assert len(heard) == 1

    def test_a_removed_body_hears_its_end_and_then_nothing(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.5, 0))
        heard = []
        subscription = mgr.events.subscribe(heard.append, body=crate,
                                            phases=('begin', 'end'))
        run(mgr, 0.2)
        mgr.remove(crate)
        assert crate.index is None
        run(mgr, 0.1)
        assert [(hit.phase, hit.reason) for hit in heard] == [
            ('begin', None), ('end', 'removed')]
        assert heard[1].body is crate
        assert not subscription.active
        # The slot's next tenant is not the removed crate's subscriber's business.
        add_crate(mgr, position=(0, 0.5, 0))
        run(mgr, 0.2)
        assert len(heard) == 2

    def test_a_failing_callback_does_not_stop_the_others(self, caplog) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)

        def broken(hit):
            raise RuntimeError('broken handler')

        heard = []
        mgr.events.subscribe(broken, body=crate)
        mgr.events.subscribe(heard.append, body=crate)
        with caplog.at_level(logging.ERROR):
            run(mgr, 1.0)
        assert len(heard) == 1
        assert 'broken handler' in caplog.text

    def test_a_lambda_is_kept_alive(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)
        heard = []
        mgr.events.subscribe(lambda hit: heard.append(hit), body=crate)
        import gc
        gc.collect()
        run(mgr, 1.0)
        assert len(heard) == 1


class TestImmediate:
    def test_it_runs_inside_the_step(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)
        seen = []
        mgr.events.subscribe(lambda hit: seen.append((hit, mgr.world.step_count)),
                             body=crate, immediate=True)
        run(mgr, 1.0)
        assert len(seen) == 1
        hit, step_count = seen[0]
        assert step_count == hit.event.step
        assert hit.body is crate

    def test_it_records_only_the_body_asked_about(self) -> None:
        mgr = manager()
        crate = add_crate(mgr)
        mgr.events.subscribe(print, body=crate, immediate=True)
        assert mgr.world.contact_reporting == 'flagged'

    def test_it_is_refused_on_a_threaded_manager(self) -> None:
        mgr = manager(ThreadedPhysicsManager)
        crate = add_crate(mgr)
        with pytest.raises(ValueError, match='physics thread'):
            mgr.events.subscribe(print, body=crate, immediate=True)
        assert mgr.world.contact_reporting == 'off'


class TestHits:
    def test_a_shot_arrives_in_order_with_the_landing(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr, position=(0, 0.52, 0))
        shooter = add_crate(mgr, position=(-5, 0.5, 0), size=(0.5, 1, 0.5))
        heard = []
        mgr.events.subscribe(heard.append, body=crate, kinds=('contact', 'hit'))
        hit = raycast(mgr.world, (-4, 0.5, 0), (1, 0, 0), skip=[shooter.index])
        assert hit.body == crate.index
        mgr.events.report_hit(hit, source=shooter, direction=(1, 0, 0),
                              impulse=2.0, speed=400.0, payload='rifle')
        # The round pushed the 1 kg crate along the shot, at once.
        assert mgr.world.linear_velocity[crate.index][0] == pytest.approx(2.0)
        assert heard == []
        run(mgr, 0.2)
        assert [(h.kind, h.phase) for h in heard] == [('hit', 'begin'), ('contact', 'begin')]
        shot = heard[0]
        assert shot.body is crate and shot.other is shooter
        assert shot.payload == 'rifle'
        assert shot.approach == 400.0 and shot.impulse == 2.0
        assert np.allclose(shot.normal, (1, 0, 0))

    def test_a_hit_on_an_unsubscribed_body_is_dropped_quietly(self) -> None:
        mgr = manager()
        crate = add_crate(mgr, position=(0, 5, 0))
        hit = raycast(mgr.world, (-4, 5, 0), (1, 0, 0))
        assert hit.body == crate.index
        mgr.events.report_hit(hit)
        run(mgr, 1 / 60)


class TestThreaded:
    def test_it_delivers_what_the_unthreaded_manager_delivers(self) -> None:
        def landing(cls):
            mgr = manager(cls)
            add_floor(mgr, restitution=0.6)
            ball = add_crate(mgr, position=(0, 1, 0), shape=model.Shape.sphere(0.2))
            heard = []
            mgr.events.subscribe(heard.append, body=ball, phases=('begin', 'end'))
            return mgr, heard

        plain, plain_heard = landing(PhysicsManager)
        threaded, threaded_heard = landing(ThreadedPhysicsManager)
        for _ in range(60):
            plain.advance(4 * STEP)
            sim = threaded._sim
            with sim.with_world():
                for _ in range(4):
                    threaded.world.step(STEP)
                    sim._publish()
            threaded.advance(4 * STEP)
        assert [(h.phase, round(h.time, 6)) for h in threaded_heard] == [
            (h.phase, round(h.time, 6)) for h in plain_heard]
        assert len(plain_heard) >= 4


def test_body_refs_resolve_without_a_manager_handle() -> None:
    mgr = manager()
    add_floor(mgr)
    world = mgr.world
    shape = world.add_shape(model.Shape.sphere(0.2))
    raw = world.add_body(model.Motion(type=model.DYNAMIC),
                         model.Collider(shape=shape), position=(0, 1, 0))
    heard = []
    mgr.events.subscribe(heard.append, body=raw)
    run(mgr, 1.0)
    assert heard[0].body == BodyRef(raw, 0)
    assert heard[0].node is None


class TestAsking:
    def test_an_unknown_kind_is_refused(self) -> None:
        mgr = manager()
        with pytest.raises(ValueError, match='unknown collision kinds'):
            mgr.events.subscribe(print, kinds=('contacts',))

    def test_phases_that_belong_to_no_kind_asked_for_are_refused(self) -> None:
        mgr = manager()
        with pytest.raises(ValueError, match='none of the phases'):
            mgr.events.subscribe(print, kinds=('contact',), phases=('enter',))

    def test_something_that_is_not_a_body_is_refused(self) -> None:
        mgr = manager()
        with pytest.raises(TypeError, match='names no body'):
            mgr.events.subscribe(print, body=Transform())

    def test_an_immediate_trigger_subscription_is_refused(self) -> None:
        mgr = manager()
        crate = add_crate(mgr)
        with pytest.raises(ValueError, match='contacts only'):
            mgr.events.subscribe(print, body=crate, kinds=('trigger',), immediate=True)

    def test_a_body_ref_names_its_body(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)
        heard = []
        mgr.events.subscribe(heard.append, body=mgr.world.ref(crate.index))
        run(mgr, 1.0)
        assert [hit.body for hit in heard] == [crate]

    def test_asking_for_persist_records_it(self) -> None:
        mgr = manager()
        crate = add_crate(mgr)
        assert not mgr.world.report_persist
        mgr.events.subscribe(print, body=crate, phases=('persist',))
        assert mgr.world.report_persist
        assert mgr.world.contact_reporting == 'flagged'

    def test_every_body_records_every_pair(self) -> None:
        mgr = manager()
        mgr.events.subscribe(print)
        assert mgr.world.contact_reporting == 'all'

    def test_a_world_wide_subscription_can_be_cancelled(self) -> None:
        mgr = manager()
        add_floor(mgr)
        add_crate(mgr)
        heard = []
        mgr.events.subscribe(heard.append).cancel()
        run(mgr, 1.0)
        assert heard == []

    def test_an_immediate_subscription_can_be_cancelled(self) -> None:
        mgr = manager()
        add_floor(mgr)
        crate = add_crate(mgr)
        heard = []
        subscription = mgr.events.subscribe(heard.append, body=crate, immediate=True)
        subscription.cancel()
        subscription.cancel()
        run(mgr, 1.0)
        assert heard == []
        assert mgr.world.contact_listeners == []


class TestRemoving:
    def test_removing_twice_is_harmless(self) -> None:
        mgr = manager()
        crate = add_crate(mgr)
        mgr.remove(crate)
        mgr.remove(crate)
        assert crate not in mgr.bodies

    def test_only_recent_removals_are_remembered(self, monkeypatch) -> None:
        mgr = manager()
        monkeypatch.setattr(PhysicsManager, 'RETIRED_KEPT', 2)
        crates = [add_crate(mgr, position=(3 * k, 5, 0)) for k in range(3)]
        refs = [mgr.world.ref(crate.index) for crate in crates]
        for crate in crates:
            mgr.remove(crate)
        assert mgr.handle(refs[0]) == refs[0]
        assert mgr.handle(refs[2]) is crates[2]

    def test_a_threaded_manager_removes_between_ticks(self) -> None:
        mgr = manager(ThreadedPhysicsManager)
        crate = add_crate(mgr)
        mgr.start()
        try:
            mgr.remove(crate)
        finally:
            mgr.stop()
        assert mgr.world.live_body_count == 0
