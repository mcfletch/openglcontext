"""The probe's layers past the scene's, and the lights uploaded into them.

A zone's captured environment and a document's ``EXT_lights_image_based``
light each live in a layer of the probe's cube-map arrays. These fill layers,
read them back, grow the arrays and turn a light, against a real context
where GL is involved.
"""
import math

import numpy as np
import pytest
from OpenGL import GL

from OpenGLContext.passes import ibl
from OpenGLContext.passes.ibl import IBLProbe
from OpenGLContext.scenegraph import imagebasedlight
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight
from OpenGLContext.passes.shaderpass import link_program


def _smooth(directions):
    """A smooth environment: what the turned light is compared against."""
    return directions[..., 0] + 0.5 * directions[..., 1] + 2.0


def _faces(size, value=None):
    if value is None:
        return [np.repeat(_smooth(imagebasedlight.face_directions(face, size))[..., None],
                          3, -1).astype('f4') for face in range(6)]
    return [np.full((size, size, 3), value, 'f4') for _face in range(6)]


def _light(value=0.5, levels=IBLProbe.PRE_LEVELS, **named):
    return ImageBasedLight(
        specular=[_faces(max(1, IBLProbe.PRE_SIZE >> level), value)
                  for level in range(levels)],
        irradianceCoefficients=[(value, value, value)] + [(0.0, 0.0, 0.0)] * 8,
        **named)


class TestATurnedLight:
    def test_it_is_sampled_between_texels(self):
        """A turn reads the faces bilinearly, so a smooth sky stays smooth.

        Read at the nearest texel the mean error here is 0.02; bilinearly it
        is a tenth of that, the rest being the face edges, where each face is
        clamped rather than read across into its neighbour.
        """
        size = 16
        turn = (0.0, math.sin(0.15), 0.0, math.cos(0.15))
        light = ImageBasedLight(specular=[_faces(size)], rotation=turn)
        matrix = imagebasedlight._rotation_matrix(turn)
        errors = np.concatenate([
            np.abs(got[..., 0] - _smooth(
                imagebasedlight.face_directions(face, size) @ matrix)).ravel()
            for face, got in enumerate(light.specular_faces(0))])
        assert errors.mean() < 0.005

    def test_an_unturned_light_is_its_own_faces(self):
        faces = _faces(8)
        light = ImageBasedLight(specular=[faces])
        for got, face in zip(light.specular_faces(0), faces):
            assert np.array_equal(got, face)


@pytest.fixture
def probe(gl_context, monkeypatch):
    """A built probe with room for the scene's layer and three more."""
    monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
    monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
    ibl.set_equirect_env(None)
    built = IBLProbe(layers=4)
    if not built.ensure_built():
        pytest.skip('this driver cannot build an arrayed probe')
    yield built
    built.release()


class TestALightInALayer:
    def test_what_is_uploaded_reads_back(self, probe):
        assert probe.upload_light(_light(0.25), layer=2)
        irradiance, mips = probe.read_layer(2)
        assert len(irradiance) == 6 and len(mips) == IBLProbe.PRE_LEVELS
        assert np.allclose(mips[0][0], 0.25, atol=1e-3)
        assert np.allclose(mips[-1][5], 0.25, atol=1e-3)
        assert irradiance[0].mean() > 0.0

    def test_a_light_with_no_specular_images_leaves_the_layer_alone(self, probe):
        assert probe.upload_light(_light(0.25), layer=1)
        before, _mips = probe.read_layer(1)
        assert not probe.upload_light(_light(0.75, levels=0), layer=1)
        after, _mips = probe.read_layer(1)
        assert all(np.array_equal(a, b) for a, b in zip(before, after))

    def test_a_light_with_fewer_mips_repeats_its_roughest(self, probe):
        assert probe.upload_light(_light(0.5, levels=2), layer=3)
        _irradiance, mips = probe.read_layer(3)
        assert np.allclose(mips[4][0], 0.5, atol=1e-3)


class TestConvolvingALayer:
    def test_the_callers_state_is_given_back(self, probe):
        program = int(link_program(
            '#version 330 core\nvoid main(){ gl_Position = vec4(0.0); }\n',
            '#version 330 core\nout vec4 colour;\nvoid main(){ colour = vec4(1.0); }\n'))
        GL.glUseProgram(program)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_BLEND)
        try:
            assert probe.convolve(probe.env, 1)
            assert int(GL.glGetIntegerv(GL.GL_CURRENT_PROGRAM)) == program
            assert not GL.glIsEnabled(GL.GL_DEPTH_TEST)
            assert not GL.glIsEnabled(GL.GL_CULL_FACE)
            assert GL.glIsEnabled(GL.GL_BLEND)
        finally:
            GL.glUseProgram(0)
            GL.glDisable(GL.GL_BLEND)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glDeleteProgram(program)

    def test_the_scenes_own_layer_is_refused(self, probe):
        assert not probe.convolve(probe.env, 0)


class TestGrowingTheArrays:
    def test_the_filled_layers_are_kept(self, probe):
        if not bool(ibl.glCopyImageSubData):
            pytest.skip('this driver cannot copy between textures')
        assert probe.upload_light(_light(0.25), layer=3)
        lost = probe.lost
        probe.grow(6)
        assert probe.layers == 8
        _irradiance, mips = probe.read_layer(3)
        assert np.allclose(mips[0][0], 0.25, atol=1e-3)
        assert probe.lost == lost

    def test_a_loss_is_counted_once(self, probe, monkeypatch):
        """Without a copy the layers are lost, and the rebuild that follows is the same loss."""
        monkeypatch.setattr(ibl, 'glCopyImageSubData', None)
        lost = probe.lost
        probe.grow(6)
        assert probe.lost == lost + 1
        assert probe.ensure_built()
        assert probe.lost == lost + 1


class TestTheCoefficientsAndTheEncoding:
    def test_a_fit_evaluates_back_to_what_was_fitted(self):
        """A sky that is a constant plus a gradient is exactly l <= 1."""
        size = 32
        sky = [np.repeat((1.0 + 0.5 * imagebasedlight.face_directions(face, size)[..., 1]
                          )[..., None], 3, -1) for face in range(6)]
        fitted = imagebasedlight.sh_fit(sky)
        for face in range(6):
            directions = imagebasedlight.face_directions(face, size)
            back = imagebasedlight.sh_irradiance(fitted, directions)
            assert np.allclose(back, sky[face], atol=0.02)

    def test_rgbd_carries_values_above_one(self):
        values = np.array([[0.0, 0.25, 1.0], [2.0, 8.0, 40.0], [200.0, 1.0, 0.5]])
        encoded = imagebasedlight.encode_rgbd(values)
        assert encoded.dtype == np.uint8 and encoded.shape == (3, 4)
        decoded = imagebasedlight.decode_rgbd(encoded)
        # Each channel is within one step of its pixel's shared scale.
        step = np.maximum(values.max(axis=1, keepdims=True), 1.0) / 255.0
        assert np.all(np.abs(decoded - values) <= step)

    def test_three_channels_are_values_as_they_are(self):
        pixels = np.array([[0, 128, 255]], dtype=np.uint8)
        assert np.allclose(imagebasedlight.decode_rgbd(pixels), [[0.0, 128 / 255, 1.0]])
