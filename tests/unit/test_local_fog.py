"""X3D's LocalFog: fog for the siblings of a group and their descendants alone.

A draw inside the group of an enabled LocalFog is fogged by it, the deepest
such fog where groups nest; any other draw has the scene's bound Fog, or none
(``passes.localfog``).
"""
import pytest

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.passes import localfog
from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import Group, Shape, sceneGraph
from OpenGLContext.scenegraph.fog import FOG_LINEAR, LocalFog


def test_it_is_the_engines():
    assert prototypes()['LocalFog'] is LocalFog


def test_its_parameters_are_a_fogs():
    mode, density, colour = LocalFog(visibilityRange=50.0, color=(1, 0, 0)).fogParameters(
        [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1]])
    assert mode == FOG_LINEAR
    assert density == pytest.approx(1 / 100.0)
    assert colour == (1.0, 0.0, 0.0)


def paths():
    near, far = LocalFog(DEF='NEAR'), LocalFog(DEF='FAR')
    inner_shape, outer_shape, outside = Shape(), Shape(), Shape()
    inner = Group(children=[near, inner_shape])
    outer = Group(children=[far, inner, outer_shape])
    graph = sceneGraph(children=[outer, outside])
    root = nodepath.NodePath([]) + graph
    fogs = [root + outer + far, root + outer + inner + near]
    draws = {'inner': root + outer + inner + inner_shape,
             'outer': root + outer + outer_shape, 'outside': root + outside}
    return fogs, draws, near, far


def test_the_deepest_enclosing_fog_is_the_draws():
    fogs, draws, near, far = paths()
    found = localfog.local_fogs(fogs)
    assert localfog.fog_for(found, draws['inner'])[-1] is near
    assert localfog.fog_for(found, draws['outer'])[-1] is far
    assert localfog.fog_for(found, draws['outside']) is None


def test_a_disabled_fog_fogs_nothing():
    fogs, draws, near, far = paths()
    near.enabled = False
    assert localfog.fog_for(localfog.local_fogs(fogs), draws['inner'])[-1] is far


def test_a_local_fog_tints_only_its_group(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    box = b'<Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance><Box/></Shape>'
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="0 0 8"/>
      <Transform translation="-2 0 0"><LocalFog color="1 0 0" visibilityRange="9"/>'''
                         + box + b'''</Transform>
      <Transform translation="2 0 0">''' + box + b'''</Transform>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(64, 32)) as context:
        image = drawn_image(context).astype(int)
    fogged, clear = image[16, 16], image[16, 48]
    assert fogged[0] > fogged[1] + 100
    assert abs(clear[0] - clear[1]) < 10 and clear[1] > 200
