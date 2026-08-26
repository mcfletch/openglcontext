"""``ShaderAttribute`` sets an attribute up and takes it down again.

``render`` binds the buffer, points the attribute at it and enables the array;
``renderPost`` is the other half, and it is a published part of the node -- the
*Shader Scenegraph Nodes* tutorials drive the pair by hand rather than through
``ShaderGeometry``.  The token ``render`` returns is what carries the binding
between them, and passing nothing means there is nothing to undo.
"""

import pytest

from OpenGLContext.scenegraph.shaders import ShaderAttribute


class _Recorder:
    def __init__(self):
        self.unbound = []
        self.disabled = []


@pytest.fixture
def attribute(monkeypatch):
    from OpenGLContext.scenegraph import shaders

    recorder = _Recorder()
    monkeypatch.setattr(shaders, 'glDisableVertexAttribArray',
                        recorder.disabled.append)
    node = ShaderAttribute(name='position', size=3, dataType='FLOAT')
    node.recorder = recorder
    return node


class _Buffer:
    def __init__(self, recorder):
        self.recorder = recorder

    def unbind(self):
        self.recorder.unbound.append(self)


class TestRenderPost:
    def test_a_token_unbinds_its_buffer_and_disables_its_array(self, attribute):
        buffer = _Buffer(attribute.recorder)
        attribute.renderPost(None, None, (buffer, 7))
        assert attribute.recorder.unbound == [buffer]
        assert attribute.recorder.disabled == [7]

    def test_no_token_means_nothing_was_bound(self, attribute):
        attribute.renderPost(None, None, None)
        assert attribute.recorder.unbound == []
        assert attribute.recorder.disabled == []

    def test_the_token_is_optional(self, attribute):
        attribute.renderPost(None, None)
        assert attribute.recorder.disabled == []
