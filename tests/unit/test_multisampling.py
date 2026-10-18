"""Antialiasing by multisampling (X_ITE's Antialiased and Multisampling)

``ContextDefinition.multisampleSamples`` asks the window for that many
samples a pixel; ``OPENGLCONTEXT_MULTISAMPLING`` is its default. The frame's
copies of the window (the glass backdrop, the opaque depth volumes stop at)
resolve the samples first.
"""
import pytest

from OpenGLContext import contextdefinition, renderoptions

TRIANGLE = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
            b"<NavigationInfo headlight='false'/><Shape><Appearance>"
            b"<Material emissiveColor='1 1 1'/></Appearance>"
            b"<IndexedFaceSet coordIndex='0 1 2'>"
            b"<Coordinate point='-0.37 -0.3 -1 0.41 -0.33 -1 0.03 0.36 -1'/>"
            b"</IndexedFaceSet></Shape></Scene></X3D>")


def drawn(text, **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    from OpenGL import GL  # noqa: PLC0415 kept with its use
    with scene_context(Loader.loads(text, 'a.x3d'), size=(48, 48), **definition) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
        samples = int(GL.glGetIntegerv(GL.GL_SAMPLES))
        assert GL.glGetError() == GL.GL_NO_ERROR
        return image, samples


def partial(image):
    """How many pixels an edge covers only part of"""
    red = image[..., 0]
    return int(((red > 8) & (red < 247)).sum())


def test_the_environment_is_the_default(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_MULTISAMPLING', '4')
    renderoptions.reset_env_cache()
    assert contextdefinition.ContextDefinition().multisampleSamples == 4
    assert 'OPENGLCONTEXT_MULTISAMPLING' in renderoptions.ENVIRONMENT


def test_without_samples_an_edge_is_stepped(gl_context):
    image, samples = drawn(TRIANGLE)
    assert samples == 0
    assert partial(image) == 0


def test_with_samples_an_edge_is_blended(gl_context):
    image, samples = drawn(TRIANGLE, multisampleSamples=4)
    if samples == 0:
        pytest.skip('this driver gives no multisampled window')
    assert partial(image) > 20


GLASS = (b"<X3D version='4.0'><head><component name='X_ITE' level='1'/></head>"
         b"<Scene><Viewpoint position='0 0 0'/>"
         b"<NavigationInfo headlight='false'/>"
         b"<Shape><Appearance><Material emissiveColor='1 0 0'/></Appearance>"
         b"<IndexedFaceSet coordIndex='0 1 2 3'>"
         b"<Coordinate point='-5 -5 -4 5 -5 -4 5 5 -4 -5 5 -4'/></IndexedFaceSet></Shape>"
         b"<Shape><Appearance><PhysicalMaterial baseColor='1 1 1' metallic='0' roughness='0'>"
         b"<TransmissionMaterialExtension transmission='1'/></PhysicalMaterial></Appearance>"
         b"<IndexedFaceSet coordIndex='0 1 2 3'>"
         b"<Coordinate point='-1 -1 -2 1 -1 -2 1 1 -2 -1 1 -2'/></IndexedFaceSet></Shape>"
         b"</Scene></X3D>")


def test_glass_shows_its_backdrop_in_a_multisampled_window(gl_context):
    plain, _samples = drawn(GLASS, transmission='full')
    image, samples = drawn(GLASS, transmission='full', multisampleSamples=4)
    if samples == 0:
        pytest.skip('this driver gives no multisampled window')
    centre = tuple(image[24, 24])
    assert centre == pytest.approx(tuple(plain[24, 24]), abs=4)
    assert centre[0] > 100 and centre[0] > centre[1] + 50


VOLUME_BEHIND = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
                 b"<NavigationInfo headlight='false'/>"
                 b"<Shape><Appearance><Material emissiveColor='0 0 1'/>"
                 b"<UnlitMaterial emissiveColor='0 0 1'/></Appearance>"
                 b"<IndexedFaceSet coordIndex='0 1 2 3'>"
                 b"<Coordinate point='-5 -5 -4 5 -5 -4 5 5 -4 -5 5 -4'/></IndexedFaceSet></Shape>"
                 b"<Shape><Appearance><Material emissiveColor='1 1 1' transparency='0.5'/>"
                 b"</Appearance><IndexedFaceSet coordIndex='0 1 2 3'>"
                 b"<Coordinate point='-1 -1 -2 1 -1 -2 1 1 -2 -1 1 -2'/></IndexedFaceSet></Shape>"
                 b"</Scene></X3D>")


def test_a_transparent_phase_in_a_multisampled_window(gl_context):
    plain, _samples = drawn(VOLUME_BEHIND)
    image, samples = drawn(VOLUME_BEHIND, multisampleSamples=4)
    if samples == 0:
        pytest.skip('this driver gives no multisampled window')
    assert tuple(image[24, 24]) == pytest.approx(tuple(plain[24, 24]), abs=4)
