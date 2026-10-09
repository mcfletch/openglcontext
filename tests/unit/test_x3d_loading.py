"""X3D documents opened by the engine: every encoding, into the engine's nodes.

`OpenGLContext.loaders.x3d` reads `.x3d`, `.x3dz`, `.x3dv`, `.x3dvz`, `.x3dj`
(and `.json` whose top-level key is "X3D") and `.x3db` through `vrml.x3d`,
building the engine's implementation of each node it has one of. The scene is
an `X3DScene` the render pass draws.
"""
import gzip
import json
import logging
import struct

import numpy as np
import pytest
from vrml import protofunctions
from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d
from vrml.x3d import xite

from OpenGLContext.loaders import formats
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.x3d import X3DHandler, prototypes
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.scenegraph import SceneGraph
from OpenGLContext.testing.scenes import drawn_image, scene_context

XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0">
  <Scene>
    <Viewpoint position="0 0 6"/>
    <Shape>
      <Appearance><Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance>
      <Box size="3 3 3"/>
    </Shape>
    <SignalPdu/>
  </Scene>
</X3D>
'''


def classic():
    return vrml_x3d.dumps(vrml_x3d.loads(XML), encoding='classic').encode('utf-8')


def as_json():
    return vrml_x3d.dumps(vrml_x3d.loads(XML), encoding='json').encode('utf-8')


def binary():
    """The scene in the compressed binary encoding (Fast Infoset), set down
    by hand: each element by its index in the X3D vocabulary"""
    return (
        b'\xe0\x00\x00\x01\x20\x10\x00\x1e' + b'urn:web3d:x3d:fi-vocabulary-3.2'
        + b'\x60\x6a\x40\xfb\x42' + b'3.3' + b'\xf0'        # X3D version="3.3"
        + b'\x20\x56'                                      # Scene
        + b'\x20\x67\xf0'                                  # Viewpoint, ended
        + b'\x00\x01'                                      # Shape, Appearance
        + b'\x42\x1c\x30\x68\x03' + struct.pack('>fff', 1, 0, 0)  # Material diffuseColor
        + b'\xff\xf0'                                      # Material, Appearance ended
        + b'\x1d\xff\xff\xf0'                              # Box; Box to X3D ended
    )


ENCODED = {
    'scene.x3d': lambda: XML,
    'scene.x3dz': lambda: gzip.compress(XML),
    'scene.x3dv': classic,
    'scene.x3dvz': lambda: gzip.compress(classic()),
    'scene.x3dj': as_json,
    'scene.x3db': binary,
    'scene.x3db.gz': lambda: gzip.compress(binary()),
}


@pytest.mark.parametrize('name', sorted(ENCODED))
def test_each_encoding_loads_into_the_engines_nodes(name):
    scene = Loader.loads(ENCODED[name](), name)
    assert isinstance(scene, SceneGraph)
    shape = scene.children[1]
    assert type(shape) is basenodes.Shape
    assert type(shape.geometry) is basenodes.Box
    assert type(shape.appearance.material) is basenodes.Material


def test_a_node_the_engine_does_not_implement_is_its_declaration_and_reported():
    scene = Loader.loads(XML, 'scene.x3d')
    assert type(scene.children[2]) is x3d.SignalPdu
    assert any('SignalPdu' in str(problem.message) for problem in scene.problems)


def test_the_engines_classes_are_used_only_where_they_implement_the_declaration():
    found = prototypes()
    for name, cls in found.items():
        if name != 'X3DScene':
            assert issubclass(cls, xite.declaration(name)), name
    assert found['Shape'] is basenodes.Shape
    assert 'SignalPdu' not in found


def test_a_broken_document_gives_what_it_read_and_logs_the_errors(caplog):
    with caplog.at_level(logging.ERROR, logger='OpenGLContext.loaders.x3d'):
        success, scene = X3DHandler().parse(b'<X3D><Scene><Shape>', 'broken.x3d', '', None)
    assert success
    assert type(scene.children[0]) is basenodes.Shape
    assert 'broken.x3d' in caplog.text


def test_a_document_in_no_encoding_is_an_error():
    with pytest.raises(ValueError):
        X3DHandler().parse(b'nothing at all', 'mystery', '', None)


@pytest.mark.parametrize('name, content_type', [
    ('world.x3d', None), ('world.x3dz', None), ('world.x3dv', None),
    ('world.x3dvz', None), ('world.x3dj', None), ('world.x3db', None),
    ('world', 'model/x3d+xml'), ('world', 'model/x3d+vrml'), ('world', 'model/x3d-vrml'),
    ('world', 'model/x3d+fastinfoset'), ('world', 'model/x3d+binary'),
    ('world', 'model/x3d+json'),
])
def test_the_reader_is_chosen_by_name_and_type(name, content_type):
    assert formats.adapter_for(name, content_type).name == 'x3d'


def test_x3d_json_named_json_is_recognised_by_its_content(tmp_path):
    path = tmp_path / 'world.json'
    path.write_bytes(as_json())
    assert formats.adapter_for(str(path)).name == 'x3d'


def test_other_json_is_not(tmp_path):
    path = tmp_path / 'other.json'
    path.write_text(json.dumps({'X3Dish': 1}))
    with pytest.raises(formats.UnknownSourceType):
        formats.adapter_for(str(path))


def test_the_viewer_adapter_presents_the_world():
    reader = formats.adapter_for('scene.x3d')
    presented = reader.present(reader.read_content(XML, 'scene.x3d'))
    assert presented.viewpoints


HEADED = XML.replace(b'<Scene>', b'''<head>
    <meta name="title" content="Gallery"/>
    <meta name="creator" content="A. Author"/>
    <meta name="rights" content="(c) 2026 A. Author"/>
    <meta name="license" content="CC-BY-4.0"/>
    <meta name="reference" content="https://example.com/gallery"/>
    <meta name="generator" content="hand"/>
  </head>
  <Scene>''')


def test_the_documents_head_is_a_notice():
    reader = formats.adapter_for('scene.x3d')
    notices = reader.present(reader.read_content(HEADED, 'scene.x3d')).notices
    assert len(notices) == 1
    notice = notices[0]
    assert (notice.title, notice.creator, notice.copyright, notice.licence, notice.source) == (
        'Gallery', 'A. Author', '(c) 2026 A. Author', 'CC-BY-4.0', 'https://example.com/gallery')


def test_a_head_with_nothing_to_say_is_no_notice():
    reader = formats.adapter_for('scene.x3d')
    assert reader.present(reader.read_content(XML, 'scene.x3d')).notices == []


def test_a_loaded_scene_draws(gl_context):
    scene = Loader.loads(XML, 'scene.x3d')
    with scene_context(list(scene.children)[1:2]) as context:
        context.OnDraw(force=1)
        image = drawn_image(context)
    centre = image[image.shape[0] // 2 - 4:image.shape[0] // 2 + 4,
                   image.shape[1] // 2 - 4:image.shape[1] // 2 + 4].reshape(-1, 3).mean(axis=0)
    assert centre[0] > 100 and centre[0] > 3 * max(centre[1], centre[2], 1)
    assert np.isfinite(centre).all()


def test_the_documented_node_list_is_the_engines():
    """docs/x3d.rst lists, by component, every X3D node the engine implements."""
    import os  # noqa: PLC0415 kept with its one use
    import re  # noqa: PLC0415 kept with its one use
    from OpenGLContext.testing.paths import tests_root  # noqa: PLC0415 kept with its one use
    root = os.path.dirname(str(tests_root(__file__)))
    with open(os.path.join(root, 'docs', 'x3d.rst'), encoding='utf-8') as stream:
        text = stream.read()
    listed = text.split('.. x3d-implemented-start')[1].split('.. x3d-implemented-end')[0]
    documented = {}
    for item in re.split(r'\n- ', listed.strip().lstrip('- ')):
        component, names = item.split(' - ', 1)
        for name in re.split(r'[,\s]+', names.strip()):
            documented[name] = component.strip()
    found = {name: xite.declaration(name).COMPONENT[0]
             for name in prototypes() if name != 'X3DScene'}
    assert documented == found


@pytest.mark.parametrize('attributes, expected', [('', False), (' shadows="true"', True)])
def test_a_documents_light_casts_shadows_only_where_it_says_so(attributes, expected):
    document = ('<X3D version="4.0"><Scene><PointLight%s/><Shape castShadow="false"><Box/>'
                '</Shape></Scene></X3D>' % attributes).encode()
    scene = Loader.loads(document, 'scene.x3d')
    assert bool(scene.children[0].shadows) is expected
    assert not scene.children[1].castShadow
    assert basenodes.PointLight().shadows


def test_a_prototype_appearance_draws_with_its_bodys_material(gl_context):
    """A prototype instance is used where its body's first node would be"""
    scene = Loader.loads(b'''#X3D V3.3 utf8
PROFILE Immersive
PROTO Paint [ inputOutput SFColor tint 1 0 0 ] {
  Appearance { material Material { diffuseColor IS tint emissiveColor IS tint } } }
Viewpoint { position 0 0 6 }
Shape { appearance Paint { tint 0 0 1 } geometry Box { size 3 3 3 } }
''', 'paint.x3dv')
    with scene_context(scene, size=(32, 32)) as context:
        image = drawn_image(context)
    red, _green, blue = (int(value) for value in image[16, 16, :3])
    assert blue > 150 and red < 80, (red, blue)


EXTERN = b'''<X3D version="4.0"><Scene>
  <ExternProtoDeclare name="Joint" url='"%s#Joint"'>
    <field name="size" type="SFFloat" accessType="initializeOnly"/>
  </ExternProtoDeclare>
  <ProtoInstance DEF="J" name="Joint"><fieldValue name="size" value="2"/></ProtoInstance>
</Scene></X3D>'''
DEFINITION = b'''<X3D version="4.0"><Scene>
  <ProtoDeclare name="Joint"><ProtoInterface>
    <field name="size" type="SFFloat" accessType="initializeOnly" value="1"/>
  </ProtoInterface><ProtoBody><Group/></ProtoBody></ProtoDeclare>
</Scene></X3D>'''


def test_an_external_prototype_beside_the_document_is_read(tmp_path):
    (tmp_path / 'joint.x3d').write_bytes(DEFINITION)
    (tmp_path / 'world.x3d').write_bytes(EXTERN % b'joint.x3d')
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    assert len(protofunctions.getSceneGraph(scene.getDEF('J')).children) == 1
    assert scene.getDEF('J').size == 2.0


def test_an_external_prototype_url_with_no_name_takes_the_files_first(tmp_path):
    """19775-1 4.9.3: the file's first PROTO, whatever its name
    (ConformanceNist EXTERNPROTO/first_proto)"""
    (tmp_path / 'joints.x3d').write_bytes(DEFINITION.replace(b'name="Joint"', b'name="First"'))
    (tmp_path / 'world.x3d').write_bytes(EXTERN.replace(b'%s#Joint', b'%s') % b'joints.x3d')
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    assert len(protofunctions.getSceneGraph(scene.getDEF('J')).children) == 1
    assert scene.getDEF('J').size == 2.0


def test_an_external_prototype_outside_the_documents_folder_is_not_read(tmp_path, caplog):
    (tmp_path / 'joint.x3d').write_bytes(DEFINITION)
    (tmp_path / 'inner').mkdir()
    (tmp_path / 'inner' / 'world.x3d').write_bytes(EXTERN % b'../joint.x3d')
    with caplog.at_level(logging.WARNING):
        scene = Loader.load(str(tmp_path / 'inner' / 'world.x3d'))
    assert not protofunctions.getSceneGraph(scene.getDEF('J')).children
    assert 'joint.x3d' in caplog.text
