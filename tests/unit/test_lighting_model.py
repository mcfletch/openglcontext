"""Which rules light a scene: X3D's, or the engine's.

`ContextDefinition.lighting` is 'auto' (a scene read from a VRML97 or X3D
document is lit by X3D's rules and one built in code by the engine's), 'x3d'
or 'engine' for every scene. X3D's rules: Material by the Phong equation, an
appearance with no material unlit, the headlight unless a NavigationInfo turns
it off, no built-in studio environment and no flat fill.
"""
import pytest

from OpenGLContext import lighting
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes.pbrpass import PHONG_BIT, pack_material_block
from OpenGLContext.scenegraph.basenodes import Appearance, Material
from OpenGLContext.scenegraph.physicalmaterial import pbr_material
from OpenGLContext.scenegraph.scenegraph import X3DScene


@pytest.fixture(autouse=True)
def restore():
    yield
    lighting.use('auto')


@pytest.mark.parametrize('model, document, expected', [
    ('auto', True, True), ('auto', False, False),
    ('x3d', False, True), ('engine', True, False),
])
def test_which_rules(model, document, expected):
    lighting.use(model)
    appearance = Appearance(material=Material())
    scene = X3DScene(children=[]) if document else None
    if scene is not None:
        from vrml import protofunctions  # noqa: PLC0415 kept with its use
        protofunctions.root(appearance, scene)
    assert lighting.x3d_lit(appearance) is expected
    flags = int(pack_material_block(pbr_material(appearance)).view('int32')[29])
    assert bool(flags & PHONG_BIT) is expected


def test_an_unknown_model_is_refused():
    with pytest.raises(ValueError):
        lighting.use('phong')


def test_the_definition_names_it():
    assert ContextDefinition().lighting == 'auto'
    assert ContextDefinition(lighting='x3d').lighting == 'x3d'


def test_the_pass_follows_the_definition():
    from OpenGLContext.passes._flat import FlatPass  # noqa: PLC0415 kept with its use

    class Context:
        contextDefinition = ContextDefinition(lighting='x3d')
    passing = FlatPass.__new__(FlatPass)
    passing.context = Context()
    passing.scene = None
    assert passing.x3dLighting()
    Context.contextDefinition = ContextDefinition(lighting='engine')
    passing.scene = X3DScene()
    assert not passing.x3dLighting()
