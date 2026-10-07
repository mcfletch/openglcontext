"""A scene's bound NavigationInfo: its headlight, and the movement mode it asks for.

The scene's NavigationInfo nodes are bound as its viewpoints are
(``vrml.x3d.binding``). ``headlight`` adds the headlight to the scene's own
lights or leaves it off; a scene with no NavigationInfo has the headlight only
where it has no lights. ``type`` names the movement modes the document asks
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


@pytest.mark.parametrize('info, lights, expected', [
    (None, 0, True), (None, 2, False),
    (NavigationInfo(), 2, True), (NavigationInfo(headlight=False), 0, False),
])
def test_the_headlight(info, lights, expected):
    assert navigationinfo.headlight(info, lights) is expected


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
    assert brightness(dim + b'<NavigationInfo/>') > brightness(dim) + 20


def test_the_fixed_function_headlight(gl_context_compat):
    compat = {'profile': 'compatibility'}
    dark = brightness(b'<NavigationInfo headlight="false"/>', **compat)
    assert dark < brightness(b'', **compat) - 30
