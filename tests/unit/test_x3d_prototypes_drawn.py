"""A prototype instance is drawn as the node its body begins with.

An instance's class derives from ``PrototypedNode`` alone, so the grouping
nodes, `Switch`, `LOD` and the scene itself pass it on to the render walk by
the type of the first node of its body.
"""
import pytest

from OpenGLContext.loaders.x3d import X3DHandler
from OpenGLContext.scenegraph import grouping
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

BODY = ('<Transform><Shape><Appearance><Material emissiveColor="1 0 0"/></Appearance>'
        '<Box size="3 3 3"/></Shape></Transform>')
DECLARED = '<ProtoDeclare name="P"><ProtoBody>%s</ProtoBody></ProtoDeclare>' % BODY


def _scene(content):
    _ok, scene = X3DHandler().parse(
        ('<X3D version="4.0"><Scene>%s%s</Scene></X3D>' % (DECLARED, content)).encode(),
        'a.x3d')
    return scene


@pytest.mark.parametrize('content', [
    '<ProtoInstance name="P"/>',
    '<Group><ProtoInstance name="P"/></Group>',
    '<Switch whichChoice="0"><ProtoInstance name="P"/></Switch>',
    '<LOD range="1000"><ProtoInstance name="P"/><Group/></LOD>',
], ids=['scene', 'group', 'switch', 'lod'])
def test_an_instance_is_drawn_wherever_it_is(content):
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    with scene_context(_scene(content)) as context:
        context.OnDraw(force=1)
        image = drawn_image(context)
    assert tuple(image[48, 48]) == pytest.approx((255, 204, 204), abs=60)


def test_an_instance_is_of_the_types_its_body_begins_with():
    from vrml.vrml97 import nodetypes
    instance = _scene('<ProtoInstance name="P"/>').children[0]
    assert grouping.of_types(instance, (nodetypes.Children,))
    assert not grouping.of_types(instance, (nodetypes.Light,))
