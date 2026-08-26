"""A ``Shape`` whose appearance is a ``Shader`` says why it did not draw.

`Shader` is a programmable substitute for an `Appearance`: it carries a GLSL
program of its own rather than a material and a texture.  The compatibility pass
draws such a shape, because the geometry submits its vertices through the
fixed-function arrays the shader's own `gl_Vertex` reads.  The core pass cannot:
its geometry is submitted through vertex array objects at attribute locations the
shader would have to declare.

What matters here is that the shape says so.  Reaching for `.texture` on a node
that has none gives an `AttributeError` per shape per frame, which names the
attribute rather than the situation.
"""

import pytest

from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.basenodes import Appearance, Box, Material
from OpenGLContext.scenegraph.shaders import Shader


class _Mode:
    """Enough of a render pass for ``_render_shader`` to get as far as the
    appearance."""

    shader_mode = True
    visible = True
    shadow_pass = False
    shader_program = object()
    transparent = False


def test_a_shader_appearance_is_reported_rather_than_crashing_on_an_attribute():
    shape = Shape(geometry=Box(), appearance=Shader())
    with pytest.raises(NotImplementedError) as raised:
        shape.Render(mode=_Mode())
    message = str(raised.value)
    assert 'Shader' in message
    assert "profile = 'compatibility'" in message


def test_an_ordinary_appearance_is_not_refused():
    """The check must not catch the node every other shape in the scene uses."""
    shape = Shape(geometry=Box(), appearance=Appearance(material=Material()))
    mode = _Mode()
    with pytest.raises(Exception) as raised:
        shape.Render(mode=mode)
    assert not isinstance(raised.value, NotImplementedError)


def test_a_shape_with_no_appearance_at_all_is_not_refused():
    """An unset SFNode field reads as a null node, not as ``None``."""
    shape = Shape(geometry=Box())
    mode = _Mode()
    with pytest.raises(Exception) as raised:
        shape.Render(mode=mode)
    assert not isinstance(raised.value, NotImplementedError)
