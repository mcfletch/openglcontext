"""``EXT_lights_image_based``: environments a document ships, already convolved."""
import base64
import io
import json

import numpy as np
import pytest

pytest.importorskip('pygltflib')
from PIL import Image  # noqa: E402

from OpenGLContext.loaders.gltf import loader  # noqa: E402
from OpenGLContext.scenegraph.imagebasedlight import (  # noqa: E402
    ImageBasedLight, decode_rgbd, face_directions, sh_irradiance,
)
from OpenGLContext.scenegraph.zone import ENVIRONMENT  # noqa: E402


def png(colour, size=4, alpha=None):
    pixels = np.zeros((size, size, 4 if alpha is not None else 3), 'u1')
    pixels[..., :3] = colour
    if alpha is not None:
        pixels[..., 3] = alpha
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def document(zone=True, scene=True, **fields):
    images = [{'uri': png((255, 0, 0), alpha=128)}, {'uri': png((0, 64, 0), size=2)}]
    light = {'name': 'red-room', 'intensity': 1.0,
             'irradianceCoefficients': [[1.0, 0.0, 0.0]] + [[0.0, 0.0, 0.0]] * 8,
             'specularImageSize': 4,
             'specularImages': [[0] * 6, [1] * 6], **fields}
    body = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['EXT_lights_image_based', 'OGLC_zone', 'KHR_implicit_shapes'],
        'extensions': {'EXT_lights_image_based': {'lights': [light]},
                       'KHR_implicit_shapes': {'shapes': [
                           {'type': 'box', 'box': {'size': [2, 2, 2]}}]}},
        'images': images,
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'room'}],
    }
    if scene:
        body['scenes'][0]['extensions'] = {'EXT_lights_image_based': {'light': 0}}
    if zone:
        body['nodes'][0]['extensions'] = {'OGLC_zone': {
            'shape': 0, 'environment': {'intensity': 0.5},
            'extensions': {'EXT_lights_image_based': {'light': 0}}}}
    return loader.load_gltf(json.dumps(body).encode('utf-8'))


class TestDecoding:
    def test_rgbd_divides_by_the_alpha(self):
        pixels = np.array([[[255, 0, 0, 128]]], 'u1')
        assert decode_rgbd(pixels)[0, 0] == pytest.approx((255 / 128, 0, 0), rel=1e-3)

    def test_three_channels_are_taken_as_they_are(self):
        assert decode_rgbd(np.array([[[51, 102, 255]]], 'u1'))[0, 0] == pytest.approx(
            (0.2, 0.4, 1.0))

    @pytest.mark.parametrize('face,axis', [(0, (1, 0, 0)), (1, (-1, 0, 0)),
                                           (2, (0, 1, 0)), (3, (0, -1, 0)),
                                           (4, (0, 0, 1)), (5, (0, 0, -1))])
    def test_each_face_looks_along_its_axis(self, face, axis):
        centre = face_directions(face, 3)[1, 1]
        assert centre == pytest.approx(axis, abs=1e-9)

    def test_a_constant_band_is_even_irradiance(self):
        coefficients = [[1.0, 1.0, 1.0]] + [[0.0] * 3] * 8
        found = sh_irradiance(coefficients, face_directions(2, 4))
        assert np.allclose(found, 0.282095)

    def test_a_rotation_turns_the_environment(self):
        up = [[0.0] * 3, [1.0, 1.0, 1.0]] + [[0.0] * 3] * 7   # brighter toward +Y
        light = ImageBasedLight(irradianceCoefficients=up)
        turned = ImageBasedLight(irradianceCoefficients=up,
                                 rotation=(0.0, 0.0, 1.0, 0.0))   # half a turn about Z
        assert light.irradiance_faces(2)[2].mean() > light.irradiance_faces(2)[3].mean()
        assert turned.irradiance_faces(2)[2].mean() < turned.irradiance_faces(2)[3].mean()


class TestReading:
    def test_the_lights_are_read(self):
        scene = document()
        light = scene.environment
        assert isinstance(light, ImageBasedLight)
        assert len(light.specular) == 2 and light.specular[0][0].shape == (4, 4, 3)
        assert light.specular[0][0][0, 0] == pytest.approx((255 / 128, 0, 0), rel=1e-3)

    def test_a_zone_takes_the_light_as_its_environment(self):
        zone = document(scene=False).zones[0]
        setting = zone.setting(ENVIRONMENT)
        assert isinstance(setting.light, ImageBasedLight)
        assert setting.intensity == pytest.approx(0.5)

    def test_a_scene_without_one_has_none(self):
        assert document(zone=False, scene=False).environment is None

    def test_a_missing_light_is_reported(self, caplog):
        body = json.loads(json.dumps({'asset': {'version': '2.0'}, 'scenes': [
            {'nodes': [], 'extensions': {'EXT_lights_image_based': {'light': 3}}}],
            'scene': 0}))
        assert loader.load_gltf(json.dumps(body).encode()).environment is None


class TestMalformedValues:
    """One bad value in a light costs the value, or the light, never the load."""

    @pytest.mark.parametrize('fields, check', [
        ({'intensity': 'bright'}, lambda light: light.intensity == 1.0),
        ({'intensity': float('nan')}, lambda light: light.intensity == 1.0),
        ({'intensity': -2.0}, lambda light: light.intensity == 0.0),
        ({'rotation': 'abc'}, lambda light: tuple(light.rotation) == (0.0, 0.0, 0.0, 1.0)),
        ({'rotation': [0, 0, float('inf'), 1]},
         lambda light: tuple(light.rotation) == (0.0, 0.0, 0.0, 1.0)),
        ({'specularImageSize': 1e999}, lambda light: light.specularImageSize == 4),
        ({'specularImageSize': 'big'}, lambda light: light.specularImageSize == 4),
    ])
    def test_a_malformed_value_is_its_default(self, fields, check):
        assert check(document(**fields).environment)

    @pytest.mark.parametrize('coefficients', [
        [5] * 9, [[1.0, 0.0]] * 9, [['a', 0, 0]] * 9, [[float('nan'), 0, 0]] * 9,
    ])
    def test_coefficients_that_are_no_numbers_leave_the_light_out(self, coefficients, caplog):
        with caplog.at_level('WARNING'):
            scene = document(irradianceCoefficients=coefficients)
        assert scene.environment is None
        assert 'EXT_lights_image_based' in caplog.text

    def test_an_image_pillow_refuses_as_too_large_leaves_the_light_out(self, monkeypatch):
        from PIL import Image as pil
        monkeypatch.setattr(pil, 'MAX_IMAGE_PIXELS', 4)
        assert document().environment is None


class TestFaceSizes:
    """A light's faces are square, six alike, and each mip half the one before."""

    def test_a_face_that_is_not_square_leaves_the_light_out(self, caplog):
        body_images = [png((255, 0, 0), alpha=128), _wide_png()]
        with caplog.at_level('WARNING'):
            scene = _with_images(body_images, [[0] * 6, [1] * 6])
        assert scene.environment is None
        assert 'square' in caplog.text

    def test_a_mip_that_is_not_half_the_one_before_leaves_the_light_out(self, caplog):
        with caplog.at_level('WARNING'):
            scene = _with_images([png((255, 0, 0), alpha=128)], [[0] * 6, [0] * 6])
        assert scene.environment is None
        assert 'mip 1' in caplog.text

    def test_faces_of_one_mip_differ_in_size_leaves_the_light_out(self):
        images = [png((255, 0, 0), alpha=128), png((0, 64, 0), size=2)]
        assert _with_images(images, [[0, 0, 0, 0, 0, 1]]).environment is None

    def test_a_stated_size_the_faces_do_not_have_is_the_faces_size(self, caplog):
        with caplog.at_level('WARNING'):
            light = document(specularImageSize=16).environment
        assert light.specularImageSize == 4
        assert 'specularImageSize' in caplog.text


class TestReadWhenNamed:
    """A light is decoded when a scene or a zone names it, each image once."""

    @pytest.fixture
    def reads(self, monkeypatch):
        from OpenGLContext.loaders.gltf import textures
        seen = []
        original = textures._image_bytes

        def counting(g, index, resolver):
            seen.append(index)
            return original(g, index, resolver)
        monkeypatch.setattr(textures, '_image_bytes', counting)
        return seen

    def test_each_image_is_decoded_once(self, reads):
        document()                       # the scene and the zone name one light
        assert sorted(reads) == [0, 1]

    def test_a_light_nothing_names_is_not_decoded(self, reads):
        document(zone=False, scene=False)
        assert reads == []


def _wide_png():
    pixels = np.zeros((2, 4, 3), 'u1')
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _with_images(images, mips):
    body = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['EXT_lights_image_based'],
        'extensions': {'EXT_lights_image_based': {'lights': [{
            'irradianceCoefficients': [[1.0, 0.0, 0.0]] + [[0.0, 0.0, 0.0]] * 8,
            'specularImages': mips}]}},
        'images': [{'uri': uri} for uri in images],
        'scene': 0,
        'scenes': [{'nodes': [], 'extensions': {'EXT_lights_image_based': {'light': 0}}}],
    }
    return loader.load_gltf(json.dumps(body).encode('utf-8'))
