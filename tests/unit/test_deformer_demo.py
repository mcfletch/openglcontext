"""``oglc-deformer``: the CoordinateDeformer scene, with no window."""
import os

import numpy as np
import pytest

from OpenGLContext.bin import deformer_demo
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph.coordinatedeformer import CoordinateDeformer, Lattice, lattice_of
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.fixture
def demo(tmp_path):
    found = deformer_demo.DeformerScene(str(tmp_path))
    assert background.wait_for_idle(20.0)
    return found


def points(node):
    return np.asarray(node.point, np.float64).reshape(-1, 3)


def test_it_reads_without_a_problem(demo):
    assert isinstance(demo.scene, X3DScene)
    assert [str(problem) for problem in demo.scene.problems
            if problem.severity != 'info'] == []


def test_the_maps_it_names_are_written_beside_it(demo):
    assert {'deformer.x3dv', 'marble_base.png', 'brass_normal.png', 'sandstone_mr.png'} <= set(
        os.listdir(demo.directory))


def test_it_is_x3d_with_physical_materials(demo):
    from OpenGLContext.scenegraph import basenodes
    assert demo.scene.version == '4.0'
    shape = demo.scene.getDEF('Column').children[0]
    assert type(shape.appearance.material) is basenodes.PhysicalMaterial
    assert shape.appearance.material.normalTexture.url == ['marble_normal.png']


def test_it_is_valid_and_is_written_as_it_was_read(demo):
    from vrml import x3d as documents
    assert documents.validate(demo.scene) == []
    text = documents.dumps(demo.scene, encoding='xml')
    again = documents.loads(text, prototypes=None)
    assert [str(p) for p in again.problems if p.severity == 'error'] == []
    assert type(again.getDEF('Column')) is CoordinateDeformer


def test_both_deformers_describe_a_volume(demo):
    for name in ('Column', 'Nozzle'):
        node = demo.scene.getDEF(name)
        assert type(node) is CoordinateDeformer
        assert isinstance(lattice_of(node), Lattice)


def test_the_column_stands_straight_at_the_start(demo):
    demo.advance(0.0)
    column = demo.scene.getDEF('Column')
    assert np.allclose(points(column.outputCoord[0]), points(column.inputCoord[0]), atol=1e-5)


def test_the_column_bends_and_its_foot_stays(demo):
    demo.advance(0.0)
    column = demo.scene.getDEF('Column')
    rest = points(column.outputCoord[0]).copy()
    demo.advance(0.25)
    bent = points(column.outputCoord[0])
    top, foot = rest[:, 1] > 2.9, rest[:, 1] < 0.01
    assert (bent[top, 0] - rest[top, 0]).min() > 0.5
    assert np.allclose(bent[foot], rest[foot], atol=1e-5)


def test_the_column_twists_about_its_axis(demo):
    demo.advance(0.0)
    column = demo.scene.getDEF('Column')
    rest = points(column.outputCoord[0]).copy()
    demo.advance(0.5)
    twisted = points(column.outputCoord[0])
    top = rest[:, 1] > 2.9
    assert np.allclose(twisted[:, 1], rest[:, 1], atol=1e-5)
    assert np.abs(twisted[top] - rest[top]).max() > 0.2
    assert np.allclose(np.hypot(twisted[top, 0], twisted[top, 2]),
                       np.hypot(rest[top, 0], rest[top, 2]), atol=1e-5)


def test_the_lattice_drawn_is_the_lattice_deforming(demo):
    demo.advance(0.25)
    column = demo.scene.getDEF('Column')
    assert np.allclose(points(demo.scene.getDEF('ColumnGrid')),
                       np.asarray(column.controlPoint).reshape(-1, 3), atol=1e-5)


def test_the_capsule_is_squeezed_in_the_nozzles_neck(demo):
    capsule = demo.scene.getDEF('Nozzle').outputCoord[0]
    demo.advance(0.0)
    entering = np.ptp(points(capsule)[:, 2])
    demo.advance(0.25)
    squeezed = np.ptp(points(capsule)[:, 2])
    assert squeezed < 0.6 * entering
    assert points(capsule)[:, 0].mean() > -0.2      # it is carried along x as well


def test_each_deformer_moves_a_nurbs_surfaces_control_points(demo):
    from OpenGLContext.scenegraph import nurbsx3d
    for name in ('Column', 'Nozzle'):
        node = demo.scene.getDEF(name)
        surface = node.children[0].geometry
        assert type(surface) is nurbsx3d.NurbsPatchSurface
        assert surface.controlPoint is node.outputCoord[0]
        assert len(surface.mesh().positions) > 1000


def test_the_columns_surface_follows_its_lattice(demo):
    surface = demo.scene.getDEF('Column').children[0].geometry
    demo.advance(0.0)
    straight = np.asarray(surface.mesh().positions)[:, 0].max()
    demo.advance(0.25)
    assert np.asarray(surface.mesh().positions)[:, 0].max() > straight + 0.5


def test_advancing_stops_the_documents_clock(demo):
    clock = demo.scene.getDEF('Clock')
    assert clock.enabled and clock.loop
    demo.advance(0.5)
    assert not clock.enabled


def test_the_g_key_shows_and_hides_the_lattices(demo):
    lattices = demo.scene.getDEF('Lattices')
    assert lattices.whichChoice == 0
    assert demo.press('g') == 'lattices hidden'
    assert lattices.whichChoice == -1
    assert demo.press('g') == 'lattices shown'
    assert lattices.whichChoice == 0
    assert demo.press('x') == ''


def test_it_draws_and_the_picture_follows_the_lattice(gl_context, demo):
    with scene_context(demo.scene, size=(160, 90)) as context:
        demo.advance(0.0)
        for _ in range(3):
            context.OnDraw(force=1)
        straight = drawn_image(context).astype(int)
        demo.advance(0.25)
        for _ in range(3):
            context.OnDraw(force=1)
        bent = drawn_image(context).astype(int)
    assert np.isfinite(straight).all()
    assert (np.abs(straight - bent).max(axis=2) > 30).mean() > 0.01


def test_a_moving_surface_is_tessellated_once_a_frame(gl_context, demo, monkeypatch):
    """Its shadow is drawn from the mesh the view draws"""
    from OpenGLContext.scenegraph import nurbsx3d
    built = []
    original = nurbsx3d.SurfaceDrawn.buildMesh
    monkeypatch.setattr(nurbsx3d.SurfaceDrawn, 'buildMesh',
                        lambda self, level=0: built.append(level) or original(self, level))
    with scene_context(demo.scene, size=(160, 90), renderer='pbr') as context:
        for step in range(4):
            demo.advance(step / 100.0)
            context.OnDraw(force=1)
        built.clear()
        for step in range(4, 10):
            demo.advance(step / 100.0)
            context.OnDraw(force=1)
    assert len(built) == 2 * 6
