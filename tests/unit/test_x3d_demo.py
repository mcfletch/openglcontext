"""``oglc-x3d``: the X3D gallery, with no window.

The scene the demo and its tutorial draw is :class:`Gallery`, read from the
shipped document; what the document builds and what the keys do are tested
here, and ``tests/x3d_demo.py`` is the rendered form, in the visual suite.
"""
import os

import pytest
from vrml import x3d
from vrml.vrml97 import nodetypes

from OpenGLContext.bin import x3d_demo
from OpenGLContext.loaders import background
from OpenGLContext.passes import lightscope
from OpenGLContext.scenegraph import basenodes, meshgeometry
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.scenegraph import X3DScene


@pytest.fixture(scope='module')
def gallery(tmp_path_factory):
    found = x3d_demo.Gallery(str(tmp_path_factory.mktemp('gallery')))
    assert background.wait_for_idle(20.0)
    return found


def nodes(scene, kind):
    found, stack = [], list(scene.children)
    while stack:
        current = stack.pop()
        if isinstance(current, kind):
            found.append(current)
        for name in ('children', 'inlined'):
            stack.extend(getattr(current, name, None) or ())
        for name in ('geometry', 'appearance', 'material'):
            child = getattr(current, name, None)
            if child:
                stack.append(child)
    return found


class TestTheDocument:
    def test_it_reads_without_errors(self, gallery):
        assert isinstance(gallery.scene, X3DScene)
        assert not [problem for problem in gallery.scene.problems if problem.severity == 'error']

    def test_the_files_it_names_are_written_beside_it(self, gallery):
        written = set(os.listdir(gallery.directory))
        assert {'x3d_gallery.x3d', 'vase.glb', 'marble_base.png', 'brick_normal.png',
                'sandstone_mr.png'} <= written

    def test_its_materials_are_the_engines(self, gallery):
        metals = [found for found in nodes(gallery.scene, PhysicalMaterial) if found.metallic == 1]
        assert len(metals) >= 4

    def test_its_geometry_is_drawn_by_the_engine(self, gallery):
        kinds = {type(found) for found in nodes(gallery.scene, nodetypes.Geometry)
                 if type(found).__module__.startswith('OpenGLContext')}
        assert {meshgeometry.IndexedTriangleSet, meshgeometry.IndexedTriangleStripSet,
                meshgeometry.TriangleFanSet, meshgeometry.TriangleSet, meshgeometry.LineSet,
                meshgeometry.ElevationGrid} <= kinds

    def test_the_alcove_lamp_is_scoped_and_the_sun_global(self, gallery):
        assert not lightscope.is_global(gallery.alcove_lamp)
        assert lightscope.is_global(gallery.scene.getDEF('Sun'))
        assert gallery.scene.getDEF('Sun').shadows

    def test_the_vase_is_inlined(self, gallery):
        inline, = nodes(gallery.scene, basenodes.Inline)
        assert inline.renderedChildren()


class TestTheKeys:
    def test_the_lamp_goes_off_and_on(self, gallery):
        assert gallery.press('l') == 'alcove lamp off'
        assert not gallery.alcove_lamp.on
        assert gallery.press('l') == 'alcove lamp on'

    def test_the_medallion_hides_and_shows(self, gallery):
        assert gallery.press('m') == 'medallion hidden'
        assert not gallery.medallion.visible
        gallery.press('m')
        assert gallery.medallion.visible

    def test_the_scene_is_written_in_each_encoding_and_reads_back(self, gallery):
        said = gallery.press('w')
        assert said.startswith('wrote ')
        for name in ('written.x3d', 'written.x3dv', 'written.x3dj'):
            again = x3d.load(os.path.join(gallery.directory, name))
            assert not [p for p in again.problems if p.severity == 'error'], name

    def test_another_key_does_nothing(self, gallery):
        assert gallery.press('q') == ''
