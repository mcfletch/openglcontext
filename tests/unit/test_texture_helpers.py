"""Helpers in `OpenGLContext.texture` that do not need an image loaded."""
import pytest

from OpenGL.GL import GL_MAX_TEXTURE_SIZE, GL_RGB, glGetIntegerv

from OpenGLContext import texture


def test_best_size_rounds_up_to_a_power_of_two(gl_context):
    assert texture.bestSize(1) == 1
    assert texture.bestSize(3) == 4
    assert texture.bestSize(64) == 64
    assert texture.bestSize(65) == 128


def test_best_size_stops_at_the_largest_texture(gl_context):
    """A dimension past what the driver will take comes back as the limit."""
    limit = int(glGetIntegerv(GL_MAX_TEXTURE_SIZE))
    assert texture.bestSize(limit * 4) == limit


def test_update_without_a_stored_image_is_refused(gl_context):
    """`update` has no format to read the data as until something is stored."""
    tex = texture.Texture()
    with pytest.raises(RuntimeError):
        tex.update((0, 0), (1, 1), b'\0\0\0')


def test_binding_as_a_context_manager_yields_the_texture(gl_context_compat):
    """`with texture as bound:` hands back the texture, not None."""
    tex = texture.Texture()
    with tex as bound:
        assert bound is tex


def test_numpy_adapter_reports_a_mode_for_each_channel_count():
    from OpenGLContext.arrays import zeros

    assert texture.NumpyAdapter(zeros((4, 4, 3), 'B')).mode == 'RGB'
    assert texture.NumpyAdapter(zeros((4, 4, 4), 'B')).mode == 'RGBA'
    assert texture.NumpyAdapter(zeros((4, 4, 1), 'B')).mode == 'L'
    assert texture.NumpyAdapter(zeros((4, 4, 2), 'B')).mode == 'LA'


def test_get_length_format_of_an_adapter():
    from OpenGLContext.arrays import zeros

    assert texture.getLengthFormat(
        texture.NumpyAdapter(zeros((4, 4, 3), 'B'))
    ) == (3, GL_RGB)
