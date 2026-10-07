"""A scene's bound NavigationInfo: its headlight, and the movement mode it asks for.

The scene's NavigationInfo nodes are bound as its viewpoints are
(``vrml.x3d.binding``). ``headlight`` adds the headlight to the scene's own
lights or leaves it off. A document with no NavigationInfo has X3D's default
one, and so the headlight; a scene built in code with none has the headlight
only where it has no lights. ``type`` names the movement modes the document asks
for, the first the context offers being chosen when the node is bound.
"""
import numpy as np
import pytest
from vrml.vrml97 import nodetypes

from OpenGLContext.move import navigationinfo
from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph.basenodes import NavigationInfo, sceneGraph


@pytest.mark.parametrize('types, expected', [
    (['WALK'], ['walk', 'fps']),
    (['FLY', 'EXAMINE'], ['fly', 'examine']),
    (['LOOKAT', 'EXPLORE'], ['examine']),
    (['NONE'], []),
    (['ANY'], None),
    (['EXAMINE', 'ANY'], ['examine']),
    (['"WALK"', 'fly'], ['walk', 'fps', 'fly']),
])
def test_x3ds_types_are_the_engines_modes(types, expected):
    assert navigationinfo.requested_modes(NavigationInfo(type=types)) == expected


def test_the_first_requested_mode_offered_is_chosen():
    info = NavigationInfo(type=['FLY', 'WALK'])
    assert navigationinfo.chosen_mode(info, ['walk', 'examine']) == 'walk'
    assert navigationinfo.chosen_mode(info, ['examine']) is None
    assert navigationinfo.chosen_mode(NavigationInfo(type=['ANY']), ['examine']) is None


@pytest.mark.parametrize('info, lights, document, expected', [
    (None, 0, False, True), (None, 2, False, False), (None, 2, True, True),
    (NavigationInfo(), 2, False, True), (NavigationInfo(headlight=False), 0, True, False),
])
def test_the_headlight(info, lights, document, expected):
    assert navigationinfo.headlight(info, lights, document) is expected


class Paths:
    def __init__(self, scene):
        self.paths = {nodetypes.NavigationInfo: [(scene, child) for child in scene.children]}


def test_the_pass_binds_the_first_navigation_info():
    first, second = NavigationInfo(), NavigationInfo()
    scene = sceneGraph(children=[first, second])
    holder = Paths(scene)
    assert FlatPass.currentNavigation(holder) is first
    second.set_bind = True
    assert FlatPass.currentNavigation(holder) is second
    assert FlatPass.currentNavigation(Paths(sceneGraph())) is None


class Manager:
    def __init__(self, names):
        self.names = names
        self.selected = []

    def selectable(self):
        return [type('Mode', (), {'name': name})() for name in self.names]

    def select(self, name):
        self.selected.append(name)
        return True

    def modes(self):
        return []


class Navigating:
    def __init__(self, names=('walk', 'fly', 'examine')):
        self.manager = Manager(list(names))

    def getNavigation(self):
        return self.manager


def test_binding_a_navigation_info_selects_its_mode_once():
    context = Navigating()
    walk, fly = NavigationInfo(type=['WALK']), NavigationInfo(type=['FLY'])
    _scene = sceneGraph(children=[walk, fly])
    navigationinfo.apply(context, walk)
    navigationinfo.apply(context, walk)
    assert context.manager.selected == ['walk']
    navigationinfo.apply(context, fly)
    assert context.manager.selected == ['walk', 'fly']


def test_a_context_without_declared_modes_is_left_alone():
    class Classic:
        asked = 0

        def getNavigation(self):
            self.asked += 1
            return None
    context = Classic()
    navigationinfo.apply(context, NavigationInfo(type=['FLY']))
    assert context.asked == 1


SCENE = b'''<X3D version="4.0"><Scene>
  %s
  <Background skyColor="0 0 0"/>
  <Viewpoint position="0 0 6"/>
  <Shape><Appearance><Material diffuseColor="1 1 1"/></Appearance><Box size="2 2 2"/></Shape>
</Scene></X3D>'''


def brightness(content, **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(SCENE % content, 'scene.x3d')
    with scene_context(scene, size=(64, 64), **definition) as context:
        drawn_image(context)
        image = drawn_image(context)
    return float(np.asarray(image[24:40, 24:40], dtype=float).mean())


def test_headlight_false_takes_the_headlight_from_a_scene_without_lights(gl_context):
    """What remains is the environment's light, which the headlight is added to"""
    assert brightness(b'<NavigationInfo headlight="false"/>') < brightness(b'') - 20


def test_headlight_true_adds_to_the_scenes_lights(gl_context):
    dim = b'<DirectionalLight direction="0 -1 0" intensity="0.2"/>'
    unlit = brightness(dim + b'<NavigationInfo headlight="false"/>')
    assert brightness(dim + b'<NavigationInfo/>') > unlit + 20
    assert brightness(dim) > unlit + 20, "a document's default NavigationInfo"


def test_the_fixed_function_headlight(gl_context_compat):
    compat = {'profile': 'compatibility'}
    dark = brightness(b'<NavigationInfo headlight="false"/>', **compat)
    assert dark < brightness(b'', **compat) - 30


# -- speed, avatarSize and the transitions --------------------------------------

@pytest.mark.parametrize('speed, factor', [(1.0, 1.0), (2.5, 2.5), (0.0, 0.0)])
def test_speed_scales_the_modes_relative_to_x3ds_default(speed, factor):
    assert navigationinfo.speed_factor(NavigationInfo(speed=speed)) == factor


class SpeedMode:
    def __init__(self, name):
        self.name = name
        self.walkSpeed, self.runSpeed, self.flySpeed = 3.0, 6.0, 8.0


class SpeedManager(Manager):
    def __init__(self):
        super().__init__(['walk'])
        self.declared = [SpeedMode('walk'), SpeedMode('fly')]

    def modes(self):
        return self.declared


def test_binding_scales_the_modes_without_compounding():
    context = Navigating()
    context.manager = SpeedManager()
    fast, slow = NavigationInfo(speed=2.0), NavigationInfo(speed=0.5)
    _scene = sceneGraph(children=[fast, slow])
    navigationinfo.apply(context, fast)
    walk = context.manager.declared[0]
    assert (walk.walkSpeed, walk.flySpeed) == (6.0, 16.0)
    navigationinfo.apply(context, slow)
    assert (walk.walkSpeed, walk.flySpeed) == (1.5, 4.0)


def test_the_avatar_size_is_radius_eye_height_and_step():
    assert navigationinfo.avatar_of(NavigationInfo()) == (0.25, 1.6, 0.75)
    assert navigationinfo.avatar_of(NavigationInfo(avatarSize=[0.5])) == (0.5, 1.6, 0.75)


def test_binding_gives_the_context_the_avatar_size():
    context = Navigating()
    info = NavigationInfo(avatarSize=[0.4, 1.7, 0.3])
    _scene = sceneGraph(children=[info])
    navigationinfo.apply(context, info)
    assert context.navigationAvatar == (0.4, 1.7, 0.3)


@pytest.mark.parametrize('fields, expected', [
    ({}, ('LINEAR', 1.0)),
    ({'transitionType': ['ANIMATE'], 'transitionTime': 2.0}, ('ANIMATE', 2.0)),
    ({'transitionType': ['TELEPORT']}, ('TELEPORT', 0.0)),
    ({'transitionTime': 0.0}, ('TELEPORT', 0.0)),
    ({'transitionType': ['"LINEAR"', 'ANIMATE']}, ('LINEAR', 1.0)),
])
def test_the_transition(fields, expected):
    assert navigationinfo.transition_of(NavigationInfo(**fields)) == expected
    assert navigationinfo.transition_of(None) == ('LINEAR', 1.0)


# -- a bound NavigationInfo's fields changed afterwards --------------------------

def test_a_field_changed_after_binding_is_applied():
    context = Navigating()
    context.manager = SpeedManager()
    info = NavigationInfo(type=['WALK'], speed=2.0, avatarSize=[0.4, 1.7, 0.3])
    _scene = sceneGraph(children=[info])
    navigationinfo.apply(context, info)
    walk = context.manager.declared[0]
    info.speed = 3.0
    info.avatarSize = [0.5, 1.8, 0.2]
    navigationinfo.apply(context, info)
    assert walk.walkSpeed == 9.0
    assert context.navigationAvatar == (0.5, 1.8, 0.2)
    assert context.manager.selected == ['walk'], 'a speed is not a reason to choose again'


def test_its_type_changed_chooses_the_mode_again():
    context = Navigating()
    info = NavigationInfo(type=['WALK'])
    _scene = sceneGraph(children=[info])
    navigationinfo.apply(context, info)
    info.type = ['FLY']
    navigationinfo.apply(context, info)
    assert context.manager.selected == ['walk', 'fly']


def test_a_speed_the_application_sets_is_scaled_from():
    context = Navigating()
    context.manager = SpeedManager()
    info = NavigationInfo(speed=2.0)
    _scene = sceneGraph(children=[info])
    navigationinfo.apply(context, info)
    walk = context.manager.declared[0]
    walk.walkSpeed = 10.0
    info.speed = 3.0
    navigationinfo.apply(context, info)
    assert walk.walkSpeed == 15.0


def test_a_document_with_none_has_x3ds_default_type():
    """X3D's default NavigationInfo asks for EXAMINE, then ANY"""
    context = Navigating()
    navigationinfo.apply(context, None, document=True)
    assert context.manager.selected == ['examine']
    code = Navigating()
    navigationinfo.apply(code, None)
    assert code.manager.selected == []
