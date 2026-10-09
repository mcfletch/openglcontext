"""Documents compressed with gzip: ``.x3djz``, ``.x3d.gz``, ``.gltf.gz``, ``.glb.gz``.

A compressed document is told by its gzip magic number, and is decompressed
no further than the resource limit allows.
"""
import gzip

import numpy as np
import pytest

from OpenGLContext.loaders import formats
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.resolver import ResourceTooLarge, gunzipped

X3D_JSON = (b'{"X3D":{"@profile":"Interchange","@version":"4.0","Scene":'
            b'{"-children":[{"Shape":{"-geometry":{"Box":{}}}}]}}}')
X3D_XML = (b'<X3D profile="Interchange" version="4.0"><Scene><Shape><Box/></Shape>'
           b'</Scene></X3D>')


class TestGunzipped:
    def test_plain_bytes_pass_through(self):
        assert gunzipped(b'plain', 10) == b'plain'

    def test_compressed_bytes_are_decompressed(self):
        assert gunzipped(gzip.compress(b'x' * 100), None) == b'x' * 100

    def test_the_limit_holds_for_the_decompressed_size(self):
        with pytest.raises(ResourceTooLarge):
            gunzipped(gzip.compress(b'x' * 1000), 999, 'a document')

    def test_a_truncated_stream_is_refused(self):
        with pytest.raises(ValueError):
            gunzipped(gzip.compress(b'x' * 1000)[:-8], None)


@pytest.mark.parametrize('name, document', [('box.x3djz', X3D_JSON),
                                            ('box.x3d.gz', X3D_XML),
                                            ('box.x3dv.gz', None)])
def test_x3d(tmp_path, name, document):
    if document is None:
        document = b'#X3D V4.0 utf8\nPROFILE Interchange\nShape { geometry Box {} }\n'
    path = tmp_path / name
    path.write_bytes(gzip.compress(document))
    assert formats.adapter_for(name).name == 'x3d'
    scene = Loader.load(str(path))
    assert [type(child).__name__ for child in scene.children] == ['Shape']


def _glb():
    from OpenGLContext.loaders.gltf.writer import _pack_glb
    triangle = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3',
                          'count': 3, 'min': [0, 0, 0], 'max': [1, 1, 0]}],
           'bufferViews': [{'buffer': 0, 'byteLength': 36}],
           'buffers': [{'byteLength': 36}]}
    return _pack_glb(doc, triangle.tobytes())


class TestGLTF:
    def test_glb_gz_path(self, tmp_path):
        from OpenGLContext.loaders.gltf import load_gltf
        path = tmp_path / 'model.glb.gz'
        path.write_bytes(gzip.compress(_glb()))
        assert formats.adapter_for(str(path)).name == 'gltf'
        assert load_gltf(str(path)).radius > 0

    def test_compressed_bytes(self):
        from OpenGLContext.loaders.gltf import load_gltf
        assert load_gltf(gzip.compress(_glb())).radius > 0

    def test_the_limit_holds(self):
        from OpenGLContext.loaders.gltf import load_gltf
        with pytest.raises(ResourceTooLarge):
            load_gltf(gzip.compress(_glb() + b'\0' * 4000), max_resource_bytes=2000)

    def test_gltf_gz_registered(self):
        assert formats.adapter_for('scene.gltf.gz').name == 'gltf'
