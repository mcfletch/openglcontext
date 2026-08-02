"""``OMI_environment_sky``: a document's sky, read into the backgrounds we draw.

The extension is a *declarative description* of a sky, and three of its four
types describe a background OpenGLContext already renders -- so these tests are
mostly about the translation being faithful: the colours land at the right
angles, the panorama lands the right way round, and the scene's chosen sky is
the one that is built.

Loader level, no GL.  The one thing that genuinely needs a rendered frame -- the
equirectangular orientation -- is in ``test_gltf_environment_sky_render.py``.
"""
import base64
import io
import json
import math

import numpy as np
import pytest

pytest.importorskip("pygltflib")
PIL = pytest.importorskip("PIL")
from PIL import Image                                       # noqa: E402

from OpenGLContext.loaders import gltf                      # noqa: E402
from OpenGLContext.loaders.gltf import environment_sky as skies   # noqa: E402
from OpenGLContext.scenegraph.background import Background   # noqa: E402
from OpenGLContext.scenegraph.cubebackground import CubeBackground  # noqa: E402
from OpenGLContext.scenegraph.hdrbackground import HDRBackground    # noqa: E402
from OpenGLContext.scenegraph.simplebackground import SimpleBackground  # noqa: E402

HALF_PI = math.pi / 2.0


def png_uri(color=(200, 40, 40), size=(4, 2)):
    """A solid PNG as a ``data:`` URI, so nothing here touches a disk."""
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def document(skies_block, sky=None, images=0, colors=None):
    """A minimal glTF whose scene selects a sky from ``skies_block``."""
    scene = {'nodes': []}
    if sky is not None:
        scene['extensions'] = {'OMI_environment_sky': {'sky': sky}}
    body = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['OMI_environment_sky'],
        'scene': 0,
        'scenes': [scene],
        'nodes': [],
        'extensions': {'OMI_environment_sky': {'skies': skies_block}},
    }
    if images:
        palette = colors or [(200, 40, 40)] * images
        body['images'] = [{'uri': png_uri(palette[i])} for i in range(images)]
        body['textures'] = [{'source': i} for i in range(images)]
    return json.dumps(body).encode('utf-8')


GRADIENT = {'type': 'gradient', 'gradient': {
    'topColor': [0.0, 0.0, 1.0],
    'horizonColor': [0.5, 0.5, 0.5],
    'bottomColor': [0.0, 1.0, 0.0]}}

PLAIN = {'type': 'plain', 'plain': {'color': [0.25, 0.5, 0.75]}}


def sky_of(body):
    """The ``Sky`` record a loaded document's active scene selects."""
    return gltf.load_gltf(body, base_url='http://example/s.gltf').sky


def background_of(body):
    """The background node the loader put in the scene, or None."""
    scene = gltf.load_gltf(body, base_url='http://example/s.gltf')
    found = [node for node in (scene.group.children or [])
             if isinstance(node, (Background, SimpleBackground, CubeBackground,
                                  HDRBackground))]
    return found[0] if found else None


class TestReadingTheExtension:
    """The records, their defaults and the scene's choice."""

    def test_a_document_without_it_has_no_sky(self):
        body = json.dumps({'asset': {'version': '2.0'}, 'scene': 0,
                           'scenes': [{'nodes': []}], 'nodes': []}).encode('utf-8')
        assert sky_of(body) is None

    def test_a_gradient_sky_keeps_its_three_colours(self):
        sky = sky_of(document([GRADIENT]))
        assert isinstance(sky, skies.GradientSky)
        assert sky.topColor == (0.0, 0.0, 1.0)
        assert sky.horizonColor == (0.5, 0.5, 0.5)
        assert sky.bottomColor == (0.0, 1.0, 0.0)

    def test_the_gradient_curves_default_as_the_specification_states(self):
        sky = sky_of(document([GRADIENT]))
        assert sky.topCurve == pytest.approx(0.15)
        assert sky.bottomCurve == pytest.approx(0.02)
        assert sky.sunAngleMax == pytest.approx(0.5)
        assert sky.sunCurve == pytest.approx(0.15)

    def test_ambient_defaults_as_the_specification_states(self):
        sky = sky_of(document([GRADIENT]))
        assert sky.ambientLightColor == (0.0, 0.0, 0.0)
        assert sky.ambientSkyContribution == pytest.approx(1.0)

    def test_a_plain_sky_keeps_its_colour(self):
        sky = sky_of(document([PLAIN]))
        assert isinstance(sky, skies.PlainSky)
        assert sky.color == (0.25, 0.5, 0.75)

    def test_a_panorama_sky_keeps_both_kinds_of_reference(self):
        block = [{'type': 'panorama',
                  'panorama': {'equirectangular': 0, 'cubemap': [1, 2, 3, 4, 5, 6]}}]
        sky = sky_of(document(block, images=7))
        assert isinstance(sky, skies.PanoramaSky)
        assert sky.equirectangular == 0
        assert sky.cubemap == (1, 2, 3, 4, 5, 6)

    def test_a_physical_sky_keeps_its_scattering_parameters(self):
        block = [{'type': 'physical', 'physical': {'rayleighScale': 0.0001}}]
        sky = sky_of(document(block))
        assert isinstance(sky, skies.PhysicalSky)
        assert sky.rayleighScale == pytest.approx(0.0001)
        assert sky.rayleighColor == (0.3, 0.5, 1.0)
        assert sky.mieScale == pytest.approx(0.000005)
        assert sky.mieAnisotropy == pytest.approx(0.8)
        assert sky.groundColor == (0.3, 0.2, 0.1)

    def test_the_scene_chooses_which_sky_it_uses(self):
        sky = sky_of(document([GRADIENT, PLAIN], sky=1))
        assert isinstance(sky, skies.PlainSky)

    def test_a_scene_that_names_none_takes_the_first(self):
        sky = sky_of(document([PLAIN, GRADIENT]))
        assert isinstance(sky, skies.PlainSky)

    def test_an_index_outside_the_array_costs_the_sky_not_the_scene(self):
        assert sky_of(document([PLAIN], sky=7)) is None

    def test_an_unknown_sky_type_is_ignored(self):
        assert sky_of(document([{'type': 'volumetric'}])) is None

    def test_a_colour_that_is_not_numbers_falls_back_to_its_default(self):
        block = [{'type': 'plain', 'plain': {'color': ['red', 'green', 'blue']}}]
        assert sky_of(document(block)).color == (0.0, 0.0, 0.0)

    def test_a_curve_that_is_not_a_number_falls_back_to_its_default(self):
        gradient = dict(GRADIENT['gradient'], topCurve='steep')
        sky = sky_of(document([{'type': 'gradient', 'gradient': gradient}]))
        assert sky.topCurve == pytest.approx(0.15)

    @pytest.mark.parametrize('block', [
        'not an array', {'skies': 3}, [3], ['gradient'], [{}],
    ])
    def test_malformed_content_never_raises(self, block):
        body = json.dumps({
            'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': []}],
            'nodes': [], 'extensions': {'OMI_environment_sky': {'skies': block}},
        }).encode('utf-8')
        assert sky_of(body) is None


class TestTheGradientSky:
    """Three colours and two curves onto the sphere background's colour stops."""

    def stops(self, **gradient):
        block = dict(GRADIENT['gradient'])
        block.update(gradient)
        node = background_of(document([{'type': 'gradient', 'gradient': block}]))
        assert isinstance(node, Background)
        return node

    def test_it_becomes_a_gradient_sphere_background(self):
        assert isinstance(background_of(document([GRADIENT])), Background)

    def test_the_zenith_is_the_top_colour(self):
        node = self.stops()
        assert tuple(node.skyColor[0]) == pytest.approx((0.0, 0.0, 1.0))

    def test_the_sky_ends_at_the_horizon_colour(self):
        node = self.stops()
        assert tuple(node.skyColor[-1]) == pytest.approx((0.5, 0.5, 0.5), abs=1e-6)
        assert node.skyAngle[-1] == pytest.approx(HALF_PI)

    def test_the_nadir_is_the_bottom_colour(self):
        node = self.stops()
        assert tuple(node.groundColor[0]) == pytest.approx((0.0, 1.0, 0.0))

    def test_the_ground_ends_at_the_horizon_colour(self):
        node = self.stops()
        assert tuple(node.groundColor[-1]) == pytest.approx((0.5, 0.5, 0.5), abs=1e-6)
        assert node.groundAngle[-1] == pytest.approx(HALF_PI)

    def test_there_is_one_more_colour_than_angle(self):
        """What VRML97's Background means by a colour stop."""
        node = self.stops()
        assert len(node.skyColor) == len(node.skyAngle) + 1
        assert len(node.groundColor) == len(node.groundAngle) + 1

    def test_the_angles_only_ever_increase(self):
        node = self.stops()
        for angles in (list(node.skyAngle), list(node.groundAngle)):
            assert angles == sorted(angles)
            assert all(0.0 < a <= HALF_PI + 1e-9 for a in angles)

    def test_a_curve_of_one_spaces_the_stops_evenly(self):
        """The specification's stated meaning of 1.0: a linear transition."""
        node = self.stops(topCurve=1.0)
        angles = [0.0] + list(node.skyAngle)
        steps = np.diff(angles)
        assert steps.std() < 1e-6, 'a linear curve should step evenly: %r' % (steps,)

    def test_a_curve_below_one_keeps_the_top_colour_further_down(self):
        """"Values between 0.0 and 1.0 make the top color more dominant"."""
        dominant = self.stops(topCurve=0.15)
        linear = self.stops(topCurve=1.0)
        middle = len(dominant.skyColor) // 2
        assert dominant.skyAngle[middle - 1] > linear.skyAngle[middle - 1]

    def test_a_curve_above_one_gives_the_horizon_colour_more_of_the_sky(self):
        """"Values between 1.0 and infinity make the horizon color more dominant"."""
        dominant = self.stops(topCurve=6.0)
        linear = self.stops(topCurve=1.0)
        middle = len(dominant.skyColor) // 2
        assert dominant.skyAngle[middle - 1] < linear.skyAngle[middle - 1]

    def test_a_curve_of_zero_is_treated_as_linear_rather_than_raising(self):
        """The specification requires a positive number; content is not always
        well formed, and a bad curve must cost the shaping, not the scene."""
        node = self.stops(topCurve=0.0)
        steps = np.diff([0.0] + list(node.skyAngle))
        assert steps.std() < 1e-6

    def test_a_colour_beyond_full_scale_is_clamped(self):
        """The gradient sphere is drawn in low dynamic range; the extension
        permits an HDR colour, and an unclamped one would wrap."""
        node = self.stops(topColor=[4.0, 0.0, 0.0])
        assert tuple(node.skyColor[0]) == pytest.approx((1.0, 0.0, 0.0))


class TestThePlainSky:
    def test_it_becomes_a_solid_clear_colour(self):
        node = background_of(document([PLAIN]))
        assert isinstance(node, SimpleBackground)
        assert tuple(node.color) == pytest.approx((0.25, 0.5, 0.75))

    def test_the_default_colour_is_black(self):
        node = background_of(document([{'type': 'plain'}]))
        assert tuple(node.color) == pytest.approx((0.0, 0.0, 0.0))


class TestThePanoramaSky:
    def test_an_equirectangular_panorama_becomes_an_hdr_background(self):
        block = [{'type': 'panorama', 'panorama': {'equirectangular': 0}}]
        node = background_of(document(block, images=1))
        assert isinstance(node, HDRBackground)
        assert node._equirect is not None
        assert node._equirect.shape[2] == 3

    def test_the_panorama_is_linear_light_not_srgb(self):
        """The IBL probe and the PBR pass both work in linear light; handing
        them sRGB bytes would light the scene from a washed-out sky."""
        block = [{'type': 'panorama', 'panorama': {'equirectangular': 0}}]
        node = background_of(document(block, images=1, colors=[(188, 188, 188)]))
        # 188/255 is ~0.737 encoded, ~0.5 linear.
        assert float(node._equirect.mean()) == pytest.approx(0.5, abs=0.02)

    def test_a_cubemap_becomes_a_six_face_cube_background(self):
        faces = [(255, 0, 0), (0, 255, 0), (0, 0, 255),
                 (255, 255, 0), (255, 0, 255), (0, 255, 255)]
        block = [{'type': 'panorama', 'panorama': {'cubemap': [0, 1, 2, 3, 4, 5]}}]
        node = background_of(document(block, images=6, colors=faces))
        assert isinstance(node, CubeBackground)
        for name in ('right', 'left', 'top', 'bottom', 'back', 'front'):
            assert getattr(node, name).image is not None, '%s face is empty' % name

    def test_the_cubemap_faces_land_in_the_order_the_specification_gives(self):
        """+X, -X, +Y, -Y, +Z, -Z."""
        faces = [(255, 0, 0), (0, 255, 0), (0, 0, 255),
                 (255, 255, 0), (255, 0, 255), (0, 255, 255)]
        block = [{'type': 'panorama', 'panorama': {'cubemap': [0, 1, 2, 3, 4, 5]}}]
        node = background_of(document(block, images=6, colors=faces))
        for name, color in (('right', faces[0]), ('left', faces[1]),
                            ('top', faces[2]), ('bottom', faces[3]),
                            ('back', faces[4]), ('front', faces[5])):
            got = getattr(node, name).image.convert('RGB').getpixel((0, 0))
            assert got == color, '%s should be %r, got %r' % (name, color, got)

    def test_an_equirectangular_panorama_wins_over_a_cubemap(self):
        """The specification names it the fallback for engines without cubemap
        skyboxes, and it is the one that also drives the reflections."""
        block = [{'type': 'panorama',
                  'panorama': {'equirectangular': 0, 'cubemap': [1, 2, 3, 4, 5, 6]}}]
        assert isinstance(background_of(document(block, images=7)), HDRBackground)

    def test_a_panorama_naming_no_texture_yields_no_background(self):
        assert background_of(document([{'type': 'panorama', 'panorama': {}}])) is None

    def test_a_cubemap_of_the_wrong_length_is_not_a_cubemap(self):
        block = [{'type': 'panorama', 'panorama': {'cubemap': [0, 1, 2]}}]
        sky = sky_of(document(block, images=3))
        assert sky.cubemap is None
        assert background_of(document(block, images=3)) is None

    def test_a_cubemap_of_things_that_are_not_indices_is_not_a_cubemap(self):
        block = [{'type': 'panorama',
                  'panorama': {'cubemap': [0, 1, 2, 3, 4, 'five']}}]
        assert sky_of(document(block, images=5)).cubemap is None

    def test_a_cubemap_face_that_names_nothing_yields_no_background(self):
        """A partial face set would draw a skybox with holes in it."""
        block = [{'type': 'panorama', 'panorama': {'cubemap': [0, 1, 2, 3, 4, 9]}}]
        assert background_of(document(block, images=5)) is None

    def test_an_equirectangular_index_that_names_nothing_yields_no_background(self):
        block = [{'type': 'panorama', 'panorama': {'equirectangular': 9}}]
        assert background_of(document(block, images=1)) is None

    def test_an_undecodable_panorama_costs_the_sky_not_the_scene(self):
        body = json.dumps({
            'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': []}],
            'nodes': [],
            'images': [{'uri': 'data:image/png;base64,bm90IGEgcG5n'}],
            'textures': [{'source': 0}],
            'extensions': {'OMI_environment_sky': {'skies': [
                {'type': 'panorama', 'panorama': {'equirectangular': 0}}]}},
        }).encode('utf-8')
        assert background_of(body) is None
        assert sky_of(body) is not None


class TestThePanoramaOrientation:
    """The extension's panorama convention against the skybox shader's.

    Two fixed mappings from a world direction to a panorama column, both written
    down -- the extension's in its specification, the renderer's in
    ``shaders/_cubemap_inc.glsl`` -- and one conversion between them, which is
    what is under test.  Both are restated here so a change to either is caught
    as a disagreement rather than absorbed silently.
    """

    WIDTH = 64

    def omi_u(self, direction):
        """Panorama column for a direction, as ``OMI_environment_sky`` projects it:
        the middle of the texture in +Z, with +X to the left of it."""
        x, _, z = direction
        return (0.5 - math.atan2(x, z) / (2.0 * math.pi)) % 1.0

    def shader_u(self, direction):
        """The same, as ``dirToEquirect`` in ``_cubemap_inc.glsl`` samples it."""
        x, _, z = direction
        return (math.atan2(z, x) / (2.0 * math.pi) + 0.5) % 1.0

    def panorama(self):
        """A panorama whose every column is a different, identifiable value."""
        columns = np.arange(self.WIDTH, dtype=np.float32) / self.WIDTH
        return np.repeat(columns[None, :, None], 3, axis=2).repeat(4, axis=0)

    def column(self, panorama, u):
        return panorama[0, int(u * self.WIDTH) % self.WIDTH, 0]

    @pytest.mark.parametrize('name,direction', [
        ('+Z', (0.0, 0.0, 1.0)), ('-Z', (0.0, 0.0, -1.0)),
        ('+X', (1.0, 0.0, 0.0)), ('-X', (-1.0, 0.0, 0.0)),
        ('between +X and +Z', (0.7071, 0.0, 0.7071)),
        ('between -X and -Z', (-0.7071, 0.0, -0.7071)),
    ])
    def test_a_direction_shows_the_column_the_extension_puts_there(self, name, direction):
        from OpenGLContext.loaders.gltf.environment_sky import _to_shader_orientation

        source = self.panorama()
        converted = _to_shader_orientation(source)
        wanted = self.column(source, self.omi_u(direction))
        shown = self.column(converted, self.shader_u(direction))
        assert shown == pytest.approx(wanted, abs=1e-6), (
            'looking at %s should show the column the extension puts there' % name)

    def test_the_conversion_keeps_every_column(self):
        """A roll, not a crop: no part of the sky may be lost or doubled."""
        from OpenGLContext.loaders.gltf.environment_sky import _to_shader_orientation

        source = self.panorama()
        converted = _to_shader_orientation(source)
        assert sorted(converted[0, :, 0]) == pytest.approx(sorted(source[0, :, 0]))

    def test_the_rows_are_left_alone(self):
        """Both conventions put the top row at +Y, so nothing moves vertically."""
        from OpenGLContext.loaders.gltf.environment_sky import _to_shader_orientation

        source = np.zeros((4, self.WIDTH, 3), dtype=np.float32)
        source[0] = 1.0
        converted = _to_shader_orientation(source)
        assert converted[0].min() == 1.0
        assert converted[1:].max() == 0.0


class TestThePhysicalSky:
    def test_it_is_read_but_draws_nothing_yet(self, caplog):
        with caplog.at_level('INFO'):
            node = background_of(document([{'type': 'physical'}]))
        assert node is None
        assert any('physical' in record.getMessage() for record in caplog.records)

    def test_the_scene_still_reports_the_sky_it_could_not_draw(self):
        """So a caller can say why the sky is missing, and so the record is
        there when the scattering shader arrives."""
        assert isinstance(sky_of(document([{'type': 'physical'}])), skies.PhysicalSky)


class TestTheSceneItAllLandsIn:
    def test_the_background_hangs_off_the_scene_root(self):
        scene = gltf.load_gltf(document([PLAIN]), base_url='http://example/s.gltf')
        assert any(isinstance(child, SimpleBackground)
                   for child in scene.group.children)

    def test_a_document_without_a_sky_gains_no_background(self):
        body = json.dumps({'asset': {'version': '2.0'}, 'scene': 0,
                           'scenes': [{'nodes': []}], 'nodes': []}).encode('utf-8')
        scene = gltf.load_gltf(body, base_url='http://example/s.gltf')
        assert background_of(body) is None
        assert scene.sky is None

    def test_the_viewer_leaves_a_documents_own_sky_alone(self):
        """A scene that brought a sky must not get a second one on top."""
        from OpenGLContext.viewer import environment as env
        scene = gltf.load_gltf(document([PLAIN]), base_url='http://example/s.gltf')
        assert env.count_backgrounds(scene.group) == 1
