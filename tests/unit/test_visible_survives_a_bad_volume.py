"""A frustum check that cannot be made logs and culls nothing.

``visible()`` on :class:`OpenGLContext.scenegraph.shape.Shape` and on
:class:`OpenGLContext.scenegraph.shaders.ShaderGeometry` is called per node
per frame from the render pass.  A geometry whose bounding volume cannot be
worked out -- an attribute array of the wrong shape, a coordinate node that
has not loaded yet -- must not take the frame down with it: the check reports
and the node is drawn, which is the safe direction to be wrong in.
"""
import logging

import pytest

from OpenGLContext.scenegraph import shaders, shape


class _Boom(Exception):
    """What a bounding-volume calculation raises in these tests."""


@pytest.fixture(params=['Shape', 'ShaderGeometry'])
def node(request, monkeypatch):
    cls = {'Shape': shape.Shape, 'ShaderGeometry': shaders.ShaderGeometry}[request.param]
    module = {'Shape': shape, 'ShaderGeometry': shaders}[request.param]
    instance = cls()

    def boundingVolume(mode):
        raise _Boom('no volume for you')

    monkeypatch.setattr(instance, 'boundingVolume', boundingVolume)
    return instance, module


def test_it_does_not_raise(node, caplog):
    instance, _module = node
    with caplog.at_level(logging.WARNING):
        assert not instance.visible(frustum=None, matrix=None, mode=None)


def test_it_says_which_node_and_why(node, caplog):
    instance, module = node
    with caplog.at_level(logging.WARNING, logger=module.log.name):
        instance.visible(frustum=None, matrix=None, mode=None)
    text = '\n'.join(record.getMessage() for record in caplog.records)
    assert 'no volume for you' in text, text
