"""A character with a model: placed, turned to where it goes, and animated by what it is doing."""
import math

import numpy as np
import pytest

from OpenGLContext.character import CharacterModel
from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

from ._character_assets import character_glb
from ._locomotion_assets import marching, striding, walker_glb, waving

pytestmark = pytest.mark.engines('omi', 'jolt')

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def walker():
    """A rig with an idle, a walk and a run, whose feet plant for 0.6 of each cycle."""
    return CharacterModel.load(walker_glb({
        'idle': marching(2.0), 'walk': striding(1.0), 'run': striding(0.5),
        'wave': waving(1.0)}))


CLIPS = dict(idle='idle', walk=('walk', 3.0), run=('run', 6.0))   # the character's walk and run speeds


def make() -> Physics:
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0))
    service.add_static(surfaces.shape(surfaces.block((80, 1, 80)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box')
    return service


def run_for(physics, seconds, frame=1 / 60, setup=None):
    for _ in range(int(round(seconds / frame))):
        if setup is not None:
            setup()
        physics.frame(frame)


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


def test_a_character_with_a_model_gets_a_node_that_holds_it(physics):
    model = walker()
    me = physics.add_character(model=model, animations=ClipMap(**CLIPS), position=(1, 0.05, 2))
    assert me.model is model
    assert me.node is not None
    assert tuple(me.node.translation) == pytest.approx(tuple(me.position))
    holders = [me.node, *me.node.children]
    assert any(model.group in getattr(node, 'children', ()) for node in holders)


def test_the_model_a_character_wears_is_not_scenery_for_the_world_to_collide_with(physics):
    scene = basenodes.sceneGraph(children=[])
    worn = CharacterModel.load(character_glb())
    worn.group.children.append(surfaces.shape(surfaces.block((0.5, 1.8, 0.5)), LOOK))
    physics.add_character(model=worn, position=(0, 0.05, 0), parent=scene)
    assert physics.scenery_changed(scene, 1) == 0
    assert physics.scenery.derived == {}


def test_the_node_is_added_to_the_parent_given(physics):
    parent = basenodes.Group(children=[])
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), parent=parent)
    assert me.node in parent.children


def test_a_model_may_be_given_as_the_bytes_of_a_glb(physics):
    me = physics.add_character(model=walker_glb({'idle': marching(1.0)}),
                               animations=ClipMap(idle='idle'))
    assert isinstance(me.model, CharacterModel)


def test_animations_may_be_the_library_by_name(physics):
    me = physics.add_character(model=walker(), animations='ual')
    assert set(me.locomotion.missing) >= {'walk', 'run'}
    run_for(physics, 0.2)


def test_animations_may_be_found_by_guessing(physics):
    me = physics.add_character(model=walker(), animations='guess')
    assert me.locomotion.clip_map.spec('walk').clip == 'walk'


def test_an_unknown_animation_name_is_refused(physics):
    with pytest.raises(ValueError, match='ual'):
        physics.add_character(model=walker(), animations='dancing')


def test_standing_plays_the_idle_and_walking_plays_the_walk(physics):
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    run_for(physics, 0.6)
    assert me.settled.role == 'idle'
    run_for(physics, 1.0, setup=lambda: me.set_move((1, 0, 0), mode='walk'))
    assert me.settled.role == 'walk'
    run_for(physics, 1.0, setup=lambda: me.set_move((1, 0, 0), mode='run'))
    assert me.settled.role in ('walk', 'run')
    assert me.settled.clips.get('run', 0.0) > 0.0


def test_jumping_plays_a_jump_role_when_the_map_has_one(physics):
    clips = dict(CLIPS, jump_up='wave', jump_down='wave')
    me = physics.add_character(model=walker(), animations=ClipMap(**clips), position=(0, 0.05, 0))
    run_for(physics, 0.5)
    me.jump()
    run_for(physics, 0.15)
    assert me.settled.role in ('jump_up', 'jump_down')


def test_footsteps_are_events_with_the_foot_and_where_it_landed(physics):
    heard = []
    keep = heard.append
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    me.addEventHandler('footstep', function=keep)
    run_for(physics, 0.5)
    run_for(physics, 2.0, setup=lambda: me.set_move((1, 0, 0), mode='walk'))
    assert len(heard) >= 2
    assert {step.foot for step in heard} == {'left', 'right'}
    assert all(step.character is me for step in heard)
    assert heard[-1].point[0] > heard[0].point[0]


def test_a_material_footstep_sound_plays_where_the_foot_lands():
    from OpenGLContext.testing.audio import RecordingAudio

    audio = RecordingAudio()
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      audio=lambda: audio)
    service.materials.define('gravel', friction=0.8, footstep='crunch.ogg')
    service.add_static(surfaces.shape(surfaces.block((80, 1, 80)), LOOK, translation=(0, -0.5, 0)),
                       proxy='box', material='gravel')
    me = service.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    run_for(service, 0.5)
    run_for(service, 2.0, setup=lambda: me.set_move((1, 0, 0), mode='walk'))
    assert len(audio.played('crunch.ogg')) >= 2
    service.close()


def test_the_character_turns_toward_where_it_goes(physics):
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    run_for(physics, 0.5)
    run_for(physics, 1.0, setup=lambda: me.set_move((1, 0, 0)))
    assert me.heading == pytest.approx(math.pi / 2, abs=0.05)
    assert me.turn_node.rotation[3] == pytest.approx(math.pi / 2, abs=0.05)
    run_for(physics, 1.5, setup=lambda: me.set_move((0, 0, -1)))
    assert abs(me.heading) == pytest.approx(math.pi, abs=0.05)


def test_the_character_may_face_where_it_aims_instead(physics):
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    me.aim = (0, 0, 1)
    run_for(physics, 1.0, setup=lambda: me.set_move((1, 0, 0)))
    assert me.heading == pytest.approx(0.0, abs=0.05)


def test_an_action_is_played_on_the_upper_layer(physics):
    me = physics.add_character(model=walker(), animations=ClipMap(**CLIPS), position=(0, 0.05, 0))
    track = me.play_action('wave')
    assert track is not None


def test_a_character_with_no_model_has_no_animation(physics):
    me = physics.add_character(position=(0, 0.05, 0))
    run_for(physics, 0.2)
    assert me.model is None and me.locomotion is None and me.settled is None
    with pytest.raises(RuntimeError, match='model'):
        me.play_action('wave')


def test_the_model_is_fitted_to_the_capsule_when_it_has_a_mesh(physics):
    class Model:
        group = surfaces.shape(surfaces.block((1.0, 3.0, 1.0)), LOOK)
        clips: dict = {}

    me = physics.add_character(model=Model(), position=(0, 0.05, 0))
    assert tuple(Model.group.scale) == pytest.approx((0.6, 0.6, 0.6), abs=1e-6)
    assert me.node is not None


def test_a_model_is_left_as_it_is_when_fit_is_off(physics):
    class Model:
        group = surfaces.shape(surfaces.block((1.0, 3.0, 1.0)), LOOK)
        clips: dict = {}

    physics.add_character(model=Model(), fit=False, position=(0, 0.05, 0))
    assert tuple(Model.group.scale) == pytest.approx((1.0, 1.0, 1.0))
