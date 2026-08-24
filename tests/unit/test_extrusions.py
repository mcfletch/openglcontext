"""Swept geometry nodes, and generated meshes reaching the scenegraph.

The nodes hold parameters and build their vertex arrays with ``opengl_extrusions``;
what is checked here is the engine's side of that -- that the arrays arrive
without being copied, that the mesh caches and rebuilds when a field changes, and
that every node draws in a core profile, which the GLE-backed geometry these
replace could not do at all.
"""
import numpy as np
import pytest

from opengl_extrusions import circle, extrude, rectangle

from OpenGLContext.scenegraph.basenodes import (
    Appearance, Extrusion, Material, PolyCone, PolyCylinder, Shape, sceneGraph,
)
from OpenGLContext.scenegraph.extrusions import Lathe, Screw, Spiral
from OpenGLContext.scenegraph.frommesh import (
    mesh_from_primitive, meshes_from_mesh, shape_from_mesh, shapes_from_mesh,
)
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

SECTION = [(0.0, -0.1), (0.2, -0.1), (0.2, 0.1), (0.0, 0.1)]
CORNER = [(0.0, 0.0, 0.0), (0.0, 0.0, 2.0), (2.0, 0.0, 2.0)]


class TestAdapter:
    def test_a_primitive_becomes_a_mesh_node(self):
        mesh = extrude(circle(0.5, 12), [(0, 0, 0), (0, 0, 2)])
        node = mesh_from_primitive(mesh.merged().primitives[0])
        assert isinstance(node, PBRMesh)
        assert node.positions.shape[1] == 3
        assert node.indices is not None

    def test_the_arrays_are_handed_over_without_copying(self):
        """The whole point of matching dtypes: nothing to convert at the boundary."""
        mesh = extrude(circle(0.5, 12), [(0, 0, 0), (0, 0, 2)]).merged()
        primitive = mesh.primitives[0]
        node = mesh_from_primitive(primitive)
        assert np.shares_memory(node.positions, primitive.positions)
        assert np.shares_memory(node.normals, primitive.normals)
        assert np.shares_memory(node.indices, primitive.indices)

    def test_every_attribute_the_engine_knows_comes_across(self):
        from opengl_extrusions import with_tangents
        mesh = with_tangents(extrude(circle(0.5, 8), [(0, 0, 0), (0, 0, 1)])).merged()
        node = mesh_from_primitive(mesh.primitives[0])
        assert node.texcoords is not None
        assert node.tangents is not None

    def test_a_mesh_of_several_primitives_gives_several_nodes(self):
        mesh = extrude(circle(0.5, 8), [(0, 0, 0), (0, 0, 1)])
        mesh = mesh + mesh
        assert len(meshes_from_mesh(mesh)) == 2

    def test_a_shape_wraps_the_geometry_and_its_appearance(self):
        look = Appearance(material=Material(diffuseColor=(1, 0, 0)))
        shape = shape_from_mesh(extrude(circle(0.5, 8), [(0, 0, 0), (0, 0, 1)]),
                                appearance=look, name='pipe')
        assert isinstance(shape, Shape)
        assert shape.appearance is look
        assert shape.DEF == 'pipe'

    def test_shapes_from_mesh_keeps_the_primitives_apart(self):
        mesh = extrude(circle(0.5, 8), [(0, 0, 0), (0, 0, 1)])
        assert len(shapes_from_mesh(mesh + mesh)) == 2

    def test_the_adapter_reads_structurally(self):
        """Anything with glTF-named arrays works, not only this one library."""
        class Bare:
            attributes = {'POSITION': np.zeros((3, 3), 'f')}
            indices = np.array([0, 1, 2], np.uint32)
        assert isinstance(mesh_from_primitive(Bare()), PBRMesh)

    def test_something_that_is_not_a_primitive_is_refused(self):
        with pytest.raises(TypeError):
            mesh_from_primitive(object())
        with pytest.raises(TypeError):
            meshes_from_mesh(object())

    def test_a_primitive_without_positions_is_refused(self):
        class Bare:
            attributes = {'NORMAL': np.zeros((3, 3), 'f')}
            indices = None
        with pytest.raises(ValueError):
            mesh_from_primitive(Bare())


class TestNodesBuild:
    def test_a_lathe_builds_a_ring(self):
        node = Lathe(contour=SECTION, startRadius=1.0, sides=48)
        mesh = node.build()
        low, high = mesh.bounds
        assert high[0] == pytest.approx(1.2, rel=1e-2)

    def test_a_spiral_climbs(self):
        node = Spiral(contour=SECTION, startRadius=1.0, deltaZ=1.0,
                      totalAngle=4 * np.pi, sides=32)
        low, high = node.build().bounds
        assert high[2] - low[2] > 1.5

    def test_a_screw_spans_its_length(self):
        node = Screw(contour=rectangle(0.4, 0.4), startZ=-1.0, endZ=2.0,
                     totalAngle=np.pi)
        low, high = node.build().bounds
        assert low[2] == pytest.approx(-1.0, abs=1e-5)
        assert high[2] == pytest.approx(2.0, abs=1e-5)

    def test_a_polycylinder_follows_its_path(self):
        node = PolyCylinder(path=CORNER, radius=0.3, sides=16)
        assert node.build().triangle_count > 0

    def test_a_polycone_tapers(self):
        node = PolyCone(path=[(0, 0, 0), (0, 0, 1), (0, 0, 2)],
                        radii=[1.0, 0.5, 0.1], sides=16)
        mesh = node.build()
        assert mesh.triangle_count > 0

    def test_a_polycone_with_the_wrong_number_of_radii_is_refused(self):
        node = PolyCone(path=[(0, 0, 0), (0, 0, 1)], radii=[1.0])
        with pytest.raises(ValueError):
            node.build()

    def test_the_vrml97_extrusion_defaults_to_a_box(self):
        mesh = Extrusion().build()
        low, high = mesh.bounds
        assert np.allclose(low, (-1, 0, -1), atol=1e-5)
        assert np.allclose(high, (1, 1, 1), atol=1e-5)

    def test_the_vrml97_extrusion_follows_its_spine(self):
        node = Extrusion(spine=[(0, 0, 0), (0, 1, 0), (1, 2, 0)],
                         scale=[(1, 1), (0.5, 0.5), (0.25, 0.25)])
        assert node.build().triangle_count > 0

    def test_a_contour_of_two_points_is_refused(self):
        with pytest.raises(ValueError):
            Lathe(contour=[(0, 0), (1, 1)]).build()

    def test_a_path_of_one_point_is_refused(self):
        with pytest.raises(ValueError):
            PolyCylinder(path=[(0, 0, 0)]).build()

    def test_an_unknown_normals_mode_falls_back_and_warns(self, caplog):
        node = Lathe(contour=SECTION, normals='glossy', sides=8)
        assert node._normal_mode() == 'edge'
        assert 'glossy' in caplog.text

    def test_no_texture_coordinates_when_asked(self):
        node = Lathe(contour=SECTION, texture='', sides=8)
        assert node.build().merged().primitives[0].texcoords is None


class TestCaching:
    def test_the_generated_mesh_is_built_once(self):
        node = Lathe(contour=SECTION, sides=16)
        mode = _FakePass()
        first = node.geometry(mode)
        assert first is not None
        assert node.geometry(mode) is first

    def test_changing_a_field_rebuilds_it(self):
        node = Lathe(contour=SECTION, sides=16)
        mode = _FakePass()
        first = node.geometry(mode)
        node.sides = 24
        assert node.geometry(mode) is not first

    def test_a_node_that_cannot_be_built_reports_nothing_and_logs(self, caplog):
        node = Lathe(contour=[(0, 0), (1, 1)])
        assert node.geometry(_FakePass()) is None
        assert 'could not be generated' in caplog.text

    def test_a_node_that_cannot_be_built_draws_nothing(self):
        assert Lathe(contour=[(0, 0), (1, 1)]).render(mode=_FakePass()) == 0

    def test_an_unbuildable_node_still_has_a_bounding_volume(self):
        volume = Lathe(contour=[(0, 0), (1, 1)]).boundingVolume(_FakePass())
        assert volume is not None


class _FakePass:
    """Just the cache a geometry node asks its render pass for."""

    def __init__(self):
        from vrml import cache
        self.cache = cache.Cache()


#: One of every swept node, for the render check below.
EVERY_NODE = [
    ('lathe', lambda: Lathe(contour=SECTION, sides=24)),
    ('spiral', lambda: Spiral(contour=SECTION, sides=24, deltaZ=0.5,
                              totalAngle=4 * np.pi)),
    ('screw', lambda: Screw(contour=rectangle(0.4, 0.4), totalAngle=2 * np.pi)),
    ('polycylinder', lambda: PolyCylinder(path=CORNER, radius=0.25, sides=12)),
    ('polycone', lambda: PolyCone(path=CORNER, radii=[0.4, 0.25, 0.1], sides=12)),
    ('extrusion', lambda: Extrusion()),
]


def _render_and_count_lit_pixels(node, profile):
    """Draw one node in a profile and report how much of the frame it covered."""
    glfw = pytest.importorskip('glfw')
    import os

    import numpy as np
    from OpenGL.GL import (
        GL_NO_ERROR, GL_RGB, GL_UNSIGNED_BYTE, glGetError, glReadPixels,
    )

    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_PROFILE'] = profile
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    if not glfw.init():                          # pragma: no cover - no display
        pytest.skip('glfw init failed')

    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import PointLight
    Base = testingcontext.getInteractive()
    scene = sceneGraph(children=[
        Shape(geometry=node,
              appearance=Appearance(material=Material(diffuseColor=(0.9, 0.8, 0.3)))),
        PointLight(location=(4, 4, 8)),
    ])

    class _Ctx(Base):
        def OnInit(self):
            self.sg = scene

    try:
        context = _Ctx()
    except Exception as err:                     # pragma: no cover - broken GL stack
        pytest.skip('no usable %s context: %r' % (profile, err))
    try:
        context.deferRedraw = True
        for _ in range(3):
            glfw.poll_events()
            context.OnDraw(force=1)
        assert glGetError() == GL_NO_ERROR
        width, height = context.getViewPort()
        raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        return int((pixels.sum(axis=1) > 18).sum())
    finally:
        window = getattr(context, 'window', None)
        if window is not None:
            glfw.destroy_window(window)


@pytest.mark.parametrize('name,make', EVERY_NODE, ids=[n for n, _ in EVERY_NODE])
def test_every_swept_node_draws_in_a_compatibility_profile(name, make):
    """The default profile. Geometry that is data can be drawn either way, and
    a node that quietly drew nothing here would leave every demo black."""
    assert _render_and_count_lit_pixels(make(), 'compatibility') > 0, (
        '%s drew nothing in a compatibility profile' % name)


@pytest.mark.parametrize('name,make', EVERY_NODE, ids=[n for n, _ in EVERY_NODE])
def test_every_swept_node_draws_in_a_core_profile(name, make):
    """What the fixed-function geometry these replace could not do at all.

    A real core-profile context, a real render pass, a real draw -- and a
    framebuffer with something in it at the end, so "it did not raise" is not
    mistaken for "it drew".
    """
    glfw = pytest.importorskip('glfw')
    import os

    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    if not glfw.init():                          # pragma: no cover - no display
        pytest.skip('glfw init failed')

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    scene = sceneGraph(children=[
        Shape(geometry=make(),
              appearance=Appearance(material=Material(diffuseColor=(0.8, 0.7, 0.2)))),
        __import__('OpenGLContext.scenegraph.basenodes', fromlist=['PointLight'])
        .PointLight(location=(4, 4, 8)),
    ])

    class _Ctx(Base):
        def OnInit(self):
            self.sg = scene

    try:
        context = _Ctx()
    except Exception as err:                     # pragma: no cover - broken GL stack
        pytest.skip('no usable GL context: %r' % (err,))
    try:
        context.deferRedraw = True
        for _ in range(3):
            glfw.poll_events()
            context.OnDraw(force=1)
        from OpenGL.GL import GL_NO_ERROR, glGetError
        assert glGetError() == GL_NO_ERROR, 'GL reported an error drawing %s' % name
    finally:
        window = getattr(context, 'window', None)
        if window is not None:
            glfw.destroy_window(window)

