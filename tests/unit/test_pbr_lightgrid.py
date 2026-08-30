"""Lighting an object from a baked irradiance grid, in the PBR pass.

A lightmap reaches only the surfaces that were there when the world was built.
The grid is the same baked solution sampled for everything else -- a character,
a pickup, a door -- so a level that bakes its own lighting and places no lamps
draws those as lit objects rather than as silhouettes.

The pass does the lookup and hands the shader the light at this object: an
ambient term and a directional one.  Which of the two records a surface is lit
by is the shader's choice, because whether a material has a lightmap is not
known until it binds one.
"""
import os
import re
import subprocess
import sys

import pytest

from OpenGLContext.passes.shaderpass import SHADER_DIR
from OpenGLContext.testing.paths import tests_root

TESTS_DIR = str(tests_root(__file__))
CAPTURE = os.path.join(TESTS_DIR, "helpers", "_pbr_capture.py")


def _frag():
    with open(os.path.join(SHADER_DIR, 'pbr.frag')) as handle:
        return handle.read()


class TestShaderSource:
    """The contract between the pass and the fragment shader, with no GL."""

    def test_declares_what_the_pass_hands_down(self):
        source = _frag()
        assert 'uniform bool hasLightGrid' in source
        assert 'uniform vec3 lightGridAmbient' in source
        assert 'uniform vec3 lightGridDirectional' in source
        assert 'uniform vec3 lightGridDirection' in source

    def test_shades_the_directional_term_by_the_normal(self):
        """Without this a figure is a silhouette in one flat colour."""
        assert re.search(
            r'lightGridDirectional\s*\*\s*max\(\s*dot\(\s*Nw\s*,\s*'
            r'lightGridDirection\s*\)\s*,\s*0\.0\s*\)', _frag())

    def test_a_lightmapped_surface_is_left_alone(self):
        """Both are the same solve; taking both would light the world twice."""
        assert re.search(r'if\s*\(\s*hasLightGrid\s*&&\s*!hasLightmap\s*\)',
                         _frag())

    def test_feeds_the_ambient_terms_like_a_lightmap_does(self):
        source = _frag()
        assert re.search(r'ambDiffuse\s*\+=\s*gridLight\s*\*\s*albedo', source)
        assert re.search(r'ambSpecular\s*\+=\s*gridLight', source)


class TestTheProgramAPI:
    """``set_light_grid`` with nothing means "no grid", not "a black one"."""

    def _program(self):
        from OpenGLContext.passes.pbrpass import PBRShaderProgram
        program = PBRShaderProgram.__new__(PBRShaderProgram)
        program.program = 7
        uploaded = []
        program._set_uniform1i = lambda name, value, prog=None: uploaded.append(
            (name, int(value)))
        program._set_uniform3f = lambda name, value, prog=None: uploaded.append(
            (name, tuple(float(v) for v in value)))
        return program, uploaded

    def test_no_arguments_clears_the_flag_and_uploads_nothing_else(self):
        program, uploaded = self._program()
        program.set_light_grid()
        assert uploaded == [('hasLightGrid', 0)]

    def test_a_sample_is_uploaded_whole(self):
        program, uploaded = self._program()
        program.set_light_grid((0.1, 0.2, 0.3), (1.0, 0.9, 0.8), (0.0, 1.0, 0.0))
        assert uploaded == [
            ('hasLightGrid', 1),
            ('lightGridAmbient', (0.1, 0.2, 0.3)),
            ('lightGridDirectional', (1.0, 0.9, 0.8)),
            ('lightGridDirection', (0.0, 1.0, 0.0)),
        ]


class TestWhichObjectsAreLookedUp:
    """Who pays for the lookup, and who is skipped before it happens.

    A baked world is mostly lightmapped surface by count, and the shader
    ignores the grid for those. Sampling them anyway would put a lookup on
    every surface in the level, every frame, for a value nothing reads.
    """

    def _pass(self, grid):
        import numpy as np
        from OpenGLContext.passes._flat import FlatPass
        pass_ = FlatPass.__new__(FlatPass)
        pass_._lightGrid = grid
        self.sampled = []

        class Shader:
            def set_light_grid(inner, *args, **named):
                self.sampled.append(args)
        return pass_, Shader(), np.identity(4, dtype='d')

    def _shape(self, lightmap=False):
        from OpenGLContext.scenegraph.basenodes import Appearance, Shape
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        textures = {'lightmap': object()} if lightmap else {}
        return Shape(appearance=Appearance(
            material=PBRMaterial(textures=textures)))

    def _grid(self):
        import numpy as np
        from OpenGLContext.scenegraph.lightgrid import LightGrid
        return LightGrid(counts=[2, 2, 2], ambient=np.ones((8, 3), dtype='f'),
                         directional=np.zeros((8, 3), dtype='f'),
                         direction=np.tile((0.0, 1.0, 0.0), (8, 1)).astype('f'))

    def test_an_object_with_no_lightmap_is_sampled(self):
        pass_, shader, matrix = self._pass(self._grid())
        pass_.applyLightGrid(shader, [self._shape()], matrix, None)
        assert len(self.sampled) == 1

    def test_a_lightmapped_surface_is_not(self):
        pass_, shader, matrix = self._pass(self._grid())
        pass_.applyLightGrid(shader, [self._shape(lightmap=True)], matrix, None)
        assert self.sampled == []

    def test_a_scene_with_no_grid_costs_nothing_per_object(self):
        pass_, shader, matrix = self._pass(None)
        pass_.applyLightGrid(shader, [self._shape()], matrix, None)
        assert self.sampled == []

    def test_a_shape_with_no_material_is_sampled(self):
        from OpenGLContext.scenegraph.basenodes import Shape
        pass_, shader, matrix = self._pass(self._grid())
        pass_.applyLightGrid(shader, [Shape()], matrix, None)
        assert len(self.sampled) == 1


class TestWhereTheObjectIs:
    """The lookup is taken at the middle of what is drawn."""

    def _pass(self):
        from OpenGLContext.passes._flat import FlatPass
        return FlatPass.__new__(FlatPass)

    def _placed(self, x):
        import numpy as np
        matrix = np.identity(4, dtype='d')
        matrix[3, :3] = (x, 0.0, 0.0)       # row-vector convention
        return matrix

    def test_with_no_bounding_volume_it_is_the_object_s_origin(self):
        assert list(self._pass().objectCentre(self._placed(4.0), None)) == \
            pytest.approx([4.0, 0.0, 0.0])

    def test_the_bounding_volume_s_centre_is_taken_through_the_transform(self):
        """A figure's origin is between its feet, which is as likely to be in
        the floor as in the room."""
        class Volume:
            center = (0.0, 1.0, 0.0)
        assert list(self._pass().objectCentre(self._placed(4.0), Volume())) == \
            pytest.approx([4.0, 1.0, 0.0])


@pytest.fixture(scope="module")
def lightgrid_image(tmp_path_factory):
    """Two identical spheres, lit only by a grid that is bright on the left."""
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image

    out = str(tmp_path_factory.mktemp("lightgrid") / "lightgrid.png")
    try:
        subprocess.run([sys.executable, CAPTURE, out, 'lightgrid'], timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pytest.skip("the capture did not finish")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for the light-grid render")
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def _halves(image):
    width = image.shape[1]
    return image[:, :width // 2], image[:, width // 2:]


def test_the_object_standing_in_the_light_is_lit(lightgrid_image):
    """Nothing else lights this scene, so what is on the left is the grid."""
    left, _right = _halves(lightgrid_image)
    assert left.max() > 100


def test_the_object_standing_in_the_dark_is_not(lightgrid_image):
    """The grid is a lookup at each object's own position, not a scene fill."""
    left, right = _halves(lightgrid_image)
    assert right.max() < 20
    assert left.mean() > right.mean() * 5


def test_the_lit_object_has_a_lit_side_and_a_shaded_one(lightgrid_image):
    """The directional half of the sample, shaded by the normal.

    Its absence is what an ambient-only reading looks like: a disc in one flat
    colour, which reads as a cut-out rather than as a figure.
    """
    import numpy as np
    left, _right = _halves(lightgrid_image)
    drawn = left.sum(2) > 20
    rows = np.nonzero(drawn)[0]
    middle = (rows.min() + rows.max()) // 2
    upper = left[:middle][drawn[:middle]].mean()
    lower = left[middle:][drawn[middle:]].mean()
    assert upper > lower * 2
