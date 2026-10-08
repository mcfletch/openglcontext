"""An Inline loads any format a registered reader opens.

The url is resolved under the inlining document's policy, the reader is chosen
as `SceneLoader` chooses one, and the Inline draws the nodes the reader says
its result is drawn as: a scene's children, a glTF's group.
"""
import logging

import numpy as np
import pytest
from vrml.vrml97 import nodetypes

from OpenGLContext.loaders import background, formats
from OpenGLContext.loaders.gltf.writer import write_glb
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.inline import Inline
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

PATIENCE = 20.0

PART = b'''<X3D version="4.0"><Scene>
  <Shape><Appearance><Material diffuseColor="0 0 1"/></Appearance><Sphere radius="2"/></Shape>
</Scene></X3D>'''


def document(url):
    return ('''<X3D version="4.0"><Scene><Inline url='"%s"'/></Scene></X3D>''' % url).encode()


def settle():
    """Wait for the loads to finish"""
    assert background.wait_for_idle(PATIENCE)


def inlined(scene):
    """The scene's Inline, once its load has finished"""
    settle()
    found = scene.children[0]
    assert isinstance(found, Inline)
    return found


def test_an_x3d_document_inlines_another(tmp_path):
    (tmp_path / 'part.x3d').write_bytes(PART)
    (tmp_path / 'world.x3d').write_bytes(document('part.x3d'))
    children = inlined(Loader.load(str(tmp_path / 'world.x3d'))).renderedChildren()
    assert [type(child) for child in children] == [basenodes.Shape]
    assert type(children[0].geometry) is basenodes.Sphere


def test_an_x3d_document_inlines_a_gltf_model(tmp_path):
    quad = PBRMesh(positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 'f'),
                   indices=np.array([0, 1, 2], np.uint32))
    (tmp_path / 'part.glb').write_bytes(write_glb(quad))
    (tmp_path / 'world.x3d').write_bytes(document('part.glb'))
    children = inlined(Loader.load(str(tmp_path / 'world.x3d'))).renderedChildren()
    assert len(children) == 1
    assert isinstance(children[0], nodetypes.Grouping)
    assert children[0].children


def test_a_url_outside_the_documents_directory_is_refused(tmp_path, caplog):
    (tmp_path / 'part.x3d').write_bytes(PART)
    inside = tmp_path / 'inside'
    inside.mkdir()
    (inside / 'world.x3d').write_bytes(document('../part.x3d'))
    with caplog.at_level(logging.WARNING, logger='OpenGLContext.scenegraph.inline'):
        found = inlined(Loader.load(str(inside / 'world.x3d')))
    assert found.renderedChildren() == []
    assert 'Unable to load' in caplog.text


def test_load_false_loads_nothing_until_it_is_set(tmp_path):
    (tmp_path / 'part.x3d').write_bytes(PART)
    (tmp_path / 'world.x3d').write_bytes(document('part.x3d').replace(
        b'<Inline ', b'<Inline load="false" '))
    # Held: the url is resolved against the scene's own location.
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    found = inlined(scene)
    assert found.renderedChildren() == []
    found.load = True
    settle()
    assert len(found.renderedChildren()) == 1
    found.load = False
    assert found.renderedChildren() == []


@pytest.mark.parametrize('name', ['scene.x3d', 'scene.wrl', 'model.obj'])
def test_a_scene_reader_mounts_a_scenes_children(name):
    class Native:
        children = ['a', 'b']
    assert formats.adapter_for(name).nodes(Native()) == ['a', 'b']


def test_the_gltf_reader_mounts_its_group():
    class Native:
        group = 'the group'
    assert formats.adapter_for('model.glb').nodes(Native()) == ['the group']


RED_PART = (b'<X3D version="4.0"><Scene><Shape><Appearance><Material diffuseColor="1 0 0" '
            b'emissiveColor="1 0 0"/></Appearance><Box size="3 3 3"/></Shape></Scene></X3D>')


def test_a_scene_read_after_the_world_is_drawn_is_drawn(gl_context, tmp_path):
    """The pass draws what the Inline reads, though the world was drawn before it arrived."""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    (tmp_path / 'part.x3d').write_bytes(RED_PART)
    (tmp_path / 'world.x3d').write_bytes(
        b'<X3D version="4.0"><Scene><Viewpoint position="0 0 8"/>'
        b'<Inline load="false" url=\'"part.x3d"\'/></Scene></X3D>')
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    with scene_context(scene) as context:
        context.OnDraw(force=1)
        scene.children[1].load = True
        assert background.wait_for_idle(PATIENCE)
        for _ in range(2):
            context.OnDraw(force=1)
        image = drawn_image(context)
        h, w = image.shape[:2]
        red, green, blue = image[h // 2, w // 2]
        assert red > 100 and red > 3 * max(green, blue, 1)
        scene.children[1].load = False
        context.OnDraw(force=1)
        assert drawn_image(context)[h // 2, w // 2].sum() < 60


def test_an_inlined_documents_nodes_keep_their_scene(tmp_path):
    """The scene its nodes are rooted in lives as long as the Inline: it is what
    says they are a document's, and the base an Inline among them resolves
    its url against"""
    import gc  # noqa: PLC0415 kept with its use

    from vrml import protofunctions  # noqa: PLC0415 kept with its use
    from vrml.x3d.scene import X3DScene  # noqa: PLC0415 kept with its use
    (tmp_path / 'part.x3d').write_bytes(PART)
    (tmp_path / 'world.x3d').write_bytes(document('part.x3d'))
    inline = inlined(Loader.load(str(tmp_path / 'world.x3d')))
    gc.collect()
    shape = inline.renderedChildren()[0]
    assert isinstance(protofunctions.root(shape), X3DScene)
    assert protofunctions.root(shape.appearance) is protofunctions.root(shape)


def test_an_inline_in_an_inlined_document_reads_beside_it(tmp_path):
    (tmp_path / 'parts').mkdir()
    (tmp_path / 'parts' / 'part.x3d').write_bytes(PART)
    (tmp_path / 'parts' / 'middle.x3d').write_bytes(document('part.x3d'))
    (tmp_path / 'world.x3d').write_bytes(document('parts/middle.x3d'))
    import gc  # noqa: PLC0415 kept with its use
    middle = inlined(Loader.load(str(tmp_path / 'world.x3d')))
    gc.collect()
    inner = middle.renderedChildren()[0]
    inner.load = True
    settle()
    assert [type(child) for child in inner.renderedChildren()] == [basenodes.Shape]


def test_a_document_inlining_itself_is_not_read_again(tmp_path, caplog):
    (tmp_path / 'world.x3d').write_bytes(document('world.x3d'))
    found = inlined(Loader.load(str(tmp_path / 'world.x3d')))
    assert found.renderedChildren() == []
    assert 'includes itself' in caplog.text


def test_two_documents_inlining_each_other_stop(tmp_path, caplog):
    (tmp_path / 'a.x3d').write_bytes(document('b.x3d'))
    (tmp_path / 'b.x3d').write_bytes(document('a.x3d'))
    first = inlined(Loader.load(str(tmp_path / 'a.x3d')))
    second = first.renderedChildren()[0]
    settle()
    assert isinstance(second, Inline)
    assert second.renderedChildren() == []
    assert 'includes itself' in caplog.text
