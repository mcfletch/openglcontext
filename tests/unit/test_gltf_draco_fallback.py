"""KHR_draco_mesh_compression: attributes outside the Draco map, and fallbacks.

The extension's ``attributes`` map names what the compressed stream holds; a
primitive attribute it does not name is read from its own accessor. A document
that lists the extension in ``extensionsUsed`` only may also give every
accessor a ``bufferView`` holding the uncompressed data, which a loader without
a Draco decoder draws instead.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
DracoPy = pytest.importorskip("DracoPy")

from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import draco as draco_mod

_POSITIONS = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], np.float64)
_FACES = np.array([[0, 1, 2], [1, 3, 2]], np.uint32)


def _document(with_fallback, extra_texcoords):
    """A one-quad Draco ``.glb`` and the stream's decoded vertices.

    ``with_fallback`` gives the index and POSITION accessors bufferViews of
    uncompressed data (offset so the fallback is told apart from the stream);
    ``extra_texcoords`` adds a TEXCOORD_0 accessor, with a bufferView, that the
    Draco map does not name.
    """
    blob = DracoPy.encode(_POSITIONS, _FACES)
    m = DracoPy.decode(blob)
    uid = {a['attribute_type']: a['unique_id'] for a in m.attributes}[0]
    pts = np.asarray(m.points, np.float32)
    faces = np.asarray(m.faces, np.uint32).ravel()
    data = bytearray(blob)
    views = [BufferView(buffer=0, byteOffset=0, byteLength=len(blob))]

    def append(array):
        while len(data) % 4:
            data.append(0)
        views.append(BufferView(buffer=0, byteOffset=len(data),
                                byteLength=array.nbytes))
        data.extend(array.tobytes())
        return len(views) - 1

    fallback = pts + np.float32(10.0)
    accessors = [
        Accessor(componentType=5125, count=len(faces), type='SCALAR',
                 bufferView=append(faces) if with_fallback else None),
        Accessor(componentType=5126, count=len(pts), type='VEC3',
                 min=pts.min(0).tolist(), max=pts.max(0).tolist(),
                 bufferView=append(fallback) if with_fallback else None),
    ]
    attrs = Attributes(POSITION=1)
    texcoords = (pts[:, :2] / 2.0).astype(np.float32)
    if extra_texcoords:
        attrs.TEXCOORD_0 = len(accessors)
        accessors.append(Accessor(componentType=5126, count=len(pts), type='VEC2',
                                  bufferView=append(texcoords)))
    prim = Primitive(attributes=attrs, indices=0, mode=4, material=0)
    prim.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 0, 'attributes': {'POSITION': uid}}}
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.6, 0.6, 0.6, 1.0]))]
    g.meshes = [Mesh(primitives=[prim])]
    g.accessors = accessors
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(data))]
    g.extensionsUsed = ['KHR_draco_mesh_compression']
    if not with_fallback:
        g.extensionsRequired = ['KHR_draco_mesh_compression']
    g.set_binary_blob(bytes(data))
    return b"".join(g.save_to_bytes()), pts, texcoords


def _mesh(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        geometry = getattr(node, 'geometry', None)
        if geometry is not None:
            return geometry
        stack.extend(getattr(node, 'children', []) or [])
    return None


def test_attribute_outside_the_draco_map_is_read_from_its_accessor():
    glb, pts, texcoords = _document(with_fallback=False, extra_texcoords=True)
    mesh = _mesh(gltf.load_gltf(glb))
    assert mesh is not None
    assert np.allclose(mesh.positions, pts, atol=1e-3)
    assert mesh.texcoords is not None
    assert np.allclose(mesh.texcoords, texcoords)


def test_draco_stream_is_preferred_to_the_fallback():
    glb, pts, _ = _document(with_fallback=True, extra_texcoords=False)
    mesh = _mesh(gltf.load_gltf(glb))
    assert np.allclose(mesh.positions, pts, atol=1e-3)


def test_without_dracopy_the_uncompressed_fallback_draws(monkeypatch, caplog):
    glb, pts, texcoords = _document(with_fallback=True, extra_texcoords=True)
    monkeypatch.setattr(draco_mod, 'HAVE_DRACO', False)
    with caplog.at_level('WARNING'):
        mesh = _mesh(gltf.load_gltf(glb))
    assert mesh is not None
    assert np.allclose(mesh.positions, pts + 10.0)
    assert np.allclose(mesh.texcoords, texcoords)
    assert not [r for r in caplog.records if 'draco' in r.getMessage().lower()]


def test_without_dracopy_or_fallback_one_reason_is_logged(monkeypatch, caplog):
    glb, _, _ = _document(with_fallback=False, extra_texcoords=True)
    monkeypatch.setattr(draco_mod, 'HAVE_DRACO', False)
    with caplog.at_level('WARNING'):
        scene = gltf.load_gltf(glb)
    assert _mesh(scene) is None
    reasons = [r.getMessage() for r in caplog.records
               if 'draco' in r.getMessage().lower()]
    assert len(reasons) == 1
    assert 'DracoPy' in reasons[0] and 'fallback' in reasons[0]
