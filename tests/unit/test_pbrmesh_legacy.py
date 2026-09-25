"""A glTF mesh drawn by the compatibility profile's fixed-function pass.

``PBRMesh`` is what a glTF primitive loads as. The fixed-function pass draws it
from its arrays, lit through the ``glMaterial`` its ``PBRMaterial`` sets, so a
glTF model is seen in either profile.
"""
import types
import numpy as np
import pytest
from OpenGL import GL
from PIL import Image
from vrml import cache

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from tests.unit.glrender import base_env, frames_of
from OpenGLContext.passes.instancing import set_cull_state

SIZE = 64


def _square(colors=None, solid=True, facing=1.0):
    positions = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], 'f')
    normals = np.array([[0, 0, facing]] * 4, 'f')
    indices = [0, 1, 2, 0, 2, 3] if facing > 0 else [0, 2, 1, 0, 3, 2]
    return PBRMesh(positions=positions, normals=normals, indices=indices,
                   colors=colors, solid=solid)


def _scene(mesh, base=(0.9, 0.1, 0.1)):
    return [
        basenodes.Background(skyColor=[(0.0, 0.0, 0.0)]),
        basenodes.DirectionalLight(direction=(0.0, 0.0, -1.0), intensity=1.0),
        basenodes.Shape(geometry=mesh, appearance=basenodes.Appearance(
            material=PBRMaterial(baseColor=base, metallic=0.0, roughness=1.0))),
    ]


@pytest.fixture
def compat(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0')
    monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')


def _centre(render_scene, scene):
    frame = frames_of(render_scene, scene, frames=2, size=(SIZE, SIZE))[-1]
    return frame[SIZE // 2, SIZE // 2].astype(int)


@pytest.mark.usefixtures('compat')
def test_the_mesh_is_drawn_in_its_base_colour(render_scene):
    red, green, blue = _centre(render_scene, _scene(_square()))
    assert red > 120 and green < 60 and blue < 60, (red, green, blue)


@pytest.mark.usefixtures('compat')
def test_vertex_colours_tint_the_mesh(render_scene):
    colours = np.array([[0.1, 1.0, 0.1, 1.0]] * 4, 'f')
    red, green, blue = _centre(render_scene, _scene(_square(colours), base=(1, 1, 1)))
    assert green > 120 and red < 60, (red, green, blue)


@pytest.mark.usefixtures('compat')
def test_a_double_sided_mesh_is_seen_from_behind(render_scene):
    red, _green, _blue = _centre(render_scene, _scene(_square(solid=False, facing=-1.0)))
    assert red > 40


@pytest.mark.usefixtures('compat')
def test_a_solid_mesh_is_not_seen_from_behind(render_scene):
    assert _centre(render_scene, _scene(_square(facing=-1.0))).max() < 10


def _textured_square():
    mesh = _square()
    mesh.texcoords = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], 'f')
    return mesh


def _chequer(first, second):
    image = Image.new('RGB', (2, 2))
    image.putdata([first, second, second, first])
    return image


@pytest.mark.usefixtures('compat')
def test_the_base_colour_map_is_drawn(render_scene):
    blue = (20, 40, 230)
    material = PBRMaterial(baseColor=(1, 1, 1), metallic=0.0, roughness=1.0,
                           textures={'baseColor': PBRTexture(_chequer(blue, blue), srgb=True)})
    scene = _scene(_textured_square())
    scene[-1].appearance.material = material
    red, green, blue_ = _centre(render_scene, scene)
    assert blue_ > 120 and red < 60, (red, green, blue_)


@pytest.mark.usefixtures('gl_context_compat')
def test_the_map_is_not_left_bound_for_the_next_shape():
    """``Appearance.renderPost`` takes back what its ``render`` bound."""

    class _Context:
        """What the texture's cache keys on: the context drawing."""

    class _Mode:
        def __init__(self):
            self.context = _Context()
            self.cache = cache.Cache()

    blue = (20, 40, 230)
    appearance = basenodes.Appearance(material=PBRMaterial(
        textures={'baseColor': PBRTexture(_chequer(blue, blue))}))
    mode = _Mode()
    lit, textured, alpha, token = appearance.render(mode=mode)
    assert textured and GL.glIsEnabled(GL.GL_TEXTURE_2D)
    appearance.renderPost(token, mode=mode)
    assert not GL.glIsEnabled(GL.GL_TEXTURE_2D)
    assert GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D) == 0


@pytest.mark.usefixtures('gl_context_compat')
def test_a_double_sided_mesh_leaves_culling_as_the_pass_records_it():
    """The pass keeps what it last set for culling and sets it again only on a
    change; a mesh that turns culling on behind it leaves the next
    double-sided mesh culled."""
    mode = types.SimpleNamespace(matrix=np.eye(4), shader_mode=False)
    set_cull_state(mode, False, GL.GL_CCW)            # a double-sided mesh before
    _square(solid=False)._render_legacy(mode)  # noqa: SLF001 the fixed-function draw is this test's subject
    assert bool(GL.glIsEnabled(GL.GL_CULL_FACE)) is bool(mode._cull_enabled)  # noqa: SLF001 the pass's face-cull memo, which must match GL's state
    _square(solid=True)._render_legacy(mode)  # noqa: SLF001 the fixed-function draw is this test's subject
    assert bool(GL.glIsEnabled(GL.GL_CULL_FACE)) is bool(mode._cull_enabled) is True  # noqa: SLF001 the pass's face-cull memo, which must match GL's state


@pytest.mark.usefixtures('compat')
def test_a_mirrored_solid_mesh_is_seen_from_the_front(render_scene):
    """A mirroring transform turns the triangles' winding over; the front face
    follows it, as it does in the core profile."""
    mirrored = basenodes.Transform(scale=(-1.0, 1.0, 1.0),
                                   children=_scene(_square())[2:])
    scene = _scene(_square())[:2] + [mirrored]
    red, _green, _blue = _centre(render_scene, scene)
    assert red > 40
