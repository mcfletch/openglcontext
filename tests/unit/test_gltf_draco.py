"""KHR_draco_mesh_compression decoding tests.

The synthetic-GLB cases build a real Draco-compressed ``.glb`` in memory (encode a
mesh with DracoPy, wrap it in a glTF whose attribute accessors carry no bufferView,
exactly as a Draco asset does) so they need no network. The sample-asset case pulls
the Khronos Duck Draco variant and checks its counts against the uncompressed Duck.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
DracoPy = pytest.importorskip("DracoPy")

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))

from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import draco as draco_mod
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


# Draco AttributeType enum -> glTF semantic
_TYPE_SEMANTIC = {0: 'POSITION', 1: 'NORMAL', 3: 'TEXCOORD_0', 2: 'COLOR_0'}


def _draco_glb(with_normals=True, with_texcoords=True):
    """A one-primitive Draco ``.glb`` (a quad) built the way real assets are.

    Encodes the mesh with DracoPy, then authors accessors whose ``count``/bounds
    match the *decoded* output (as an exporter does) and whose ``bufferView`` is
    None; the extension carries the only bufferView plus the semantic->uid map.
    Returns ``(glb_bytes, decoded_mesh)`` so tests can assert against ground truth.
    """
    positions = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32)
    normals = np.tile(np.array([0, 0, 1], dtype=np.float64), (4, 1))
    texcoords = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=np.float64)
    kw = {}
    if with_normals:
        kw['normals'] = normals
    if with_texcoords:
        kw['tex_coord'] = texcoords
    blob = DracoPy.encode(positions, faces, **kw)
    m = DracoPy.decode(blob)
    uid_by_type = {a['attribute_type']: a['unique_id'] for a in m.attributes}

    pts = np.asarray(m.points, dtype=np.float32)
    nverts = len(pts)
    nindices = len(np.asarray(m.faces).ravel())

    accessors = [
        Accessor(componentType=5125, count=nindices, type='SCALAR'),          # 0 indices
        Accessor(componentType=5126, count=nverts, type='VEC3',
                 min=pts.min(0).tolist(), max=pts.max(0).tolist()),           # 1 POSITION
    ]
    ext_attrs = {'POSITION': uid_by_type[0]}
    prim_attrs = Attributes(POSITION=1)
    if with_normals:
        prim_attrs.NORMAL = len(accessors)
        ext_attrs['NORMAL'] = uid_by_type[1]
        accessors.append(Accessor(componentType=5126, count=nverts, type='VEC3'))
    if with_texcoords:
        prim_attrs.TEXCOORD_0 = len(accessors)
        ext_attrs['TEXCOORD_0'] = uid_by_type[3]
        accessors.append(Accessor(componentType=5126, count=nverts, type='VEC2'))

    prim = Primitive(attributes=prim_attrs, indices=0, mode=4, material=0)
    prim.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 0, 'attributes': ext_attrs}}

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.6, 0.6, 0.6, 1.0]))]
    g.meshes = [Mesh(primitives=[prim])]
    g.accessors = accessors
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(blob))]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.extensionsUsed = ['KHR_draco_mesh_compression']
    g.extensionsRequired = ['KHR_draco_mesh_compression']
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes()), m


def _find_shape(node):
    for child in getattr(node, 'children', []) or []:
        if getattr(child, 'geometry', None) is not None:
            return child
        found = _find_shape(child)
        if found is not None:
            return found
    return None


class TestSyntheticDracoGLB:
    def test_decodes_geometry(self):
        glb, m = _draco_glb()
        scene = gltf.load_gltf(glb)
        shape = _find_shape(scene.group)
        assert shape is not None
        mesh = shape.geometry
        assert isinstance(mesh, PBRMesh)
        assert mesh.positions.shape == (len(np.asarray(m.points)), 3)
        assert len(mesh.indices) == len(np.asarray(m.faces).ravel())
        # Every index addresses a real vertex.
        assert int(mesh.indices.max()) < len(mesh.positions)

    def test_positions_match_within_quantization(self):
        glb, m = _draco_glb()
        scene = gltf.load_gltf(glb)
        mesh = _find_shape(scene.group).geometry
        decoded = np.asarray(m.points, dtype=np.float32)
        # Same vertices in the same order as the Draco stream, quantization aside.
        assert mesh.positions.shape == decoded.shape
        assert np.allclose(mesh.positions, decoded, atol=1e-3)

    def test_normals_and_texcoords_decoded(self):
        glb, m = _draco_glb(with_normals=True, with_texcoords=True)
        scene = gltf.load_gltf(glb)
        mesh = _find_shape(scene.group).geometry
        assert mesh.normals is not None and mesh.normals.shape[0] == mesh.positions.shape[0]
        assert mesh.texcoords is not None and mesh.texcoords.shape == (mesh.positions.shape[0], 2)

    def test_loads_without_supplied_normals(self):
        glb, m = _draco_glb(with_normals=False, with_texcoords=False)
        scene = gltf.load_gltf(glb)
        mesh = _find_shape(scene.group).geometry
        # No NORMAL in the stream -> loader estimates face normals, as for plain glTF.
        assert mesh.normals is not None
        assert mesh.normals.shape[0] == mesh.positions.shape[0]


class TestMissingDracoLibrary:
    def test_skips_primitive_and_warns(self, monkeypatch, caplog):
        glb, _ = _draco_glb()
        monkeypatch.setattr(draco_mod, 'HAVE_DRACO', False)
        with caplog.at_level('WARNING'):
            scene = gltf.load_gltf(glb)
        # The whole load must survive: the scene builds, the Draco primitive is
        # simply absent rather than crashing the loader.
        assert scene is not None
        assert _find_shape(scene.group) is None
        assert any('draco' in r.getMessage().lower() for r in caplog.records)

    def test_detects_draco_extension(self):
        glb, _ = _draco_glb()
        g = pygltflib.GLTF2.load_from_bytes(b"".join([glb]) if isinstance(glb, bytes) else glb)
        prim = g.meshes[0].primitives[0]
        assert draco_mod.draco_extension(prim) is not None


def _draco_glb_semantic_without_accessor():
    """A Draco ``.glb`` whose stream carries TEXCOORD_0 the primitive never declares.

    The extension's attribute map lists TEXCOORD_0 (a real Draco unique id) but the
    primitive supplies no TEXCOORD_0 accessor, the malformed shape that used to reach
    ``_coerce_normalized(None, ...)`` and raise ``AttributeError``.
    """
    positions = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32)
    texcoords = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=np.float64)
    blob = DracoPy.encode(positions, faces, tex_coord=texcoords)
    m = DracoPy.decode(blob)
    uid_by_type = {a['attribute_type']: a['unique_id'] for a in m.attributes}
    pts = np.asarray(m.points, dtype=np.float32)
    nverts = len(pts)
    nindices = len(np.asarray(m.faces).ravel())

    prim = Primitive(attributes=Attributes(POSITION=1), indices=0, mode=4, material=0)
    prim.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 0,
        'attributes': {'POSITION': uid_by_type[0], 'TEXCOORD_0': uid_by_type[3]}}}

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[prim])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.6, 0.6, 0.6, 1.0]))]
    g.accessors = [
        Accessor(componentType=5125, count=nindices, type='SCALAR'),
        Accessor(componentType=5126, count=nverts, type='VEC3',
                 min=pts.min(0).tolist(), max=pts.max(0).tolist()),
    ]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(blob))]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.extensionsUsed = ['KHR_draco_mesh_compression']
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes()), m


def _draco_glb_valid_plus_corrupt():
    """A one-mesh ``.glb`` with a valid Draco primitive and a corrupt one.

    The second primitive's extension points at a bufferView that reads past the end
    of the buffer, so ``_decode_blob`` raises ``ValueError``; the first is sound.
    """
    positions = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], dtype=np.float64)
    faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.uint32)
    blob = DracoPy.encode(positions, faces)
    m = DracoPy.decode(blob)
    uid = {a['attribute_type']: a['unique_id'] for a in m.attributes}[0]
    pts = np.asarray(m.points, dtype=np.float32)
    nverts = len(pts)
    nindices = len(np.asarray(m.faces).ravel())

    good = Primitive(attributes=Attributes(POSITION=1), indices=0, mode=4, material=0)
    good.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 0, 'attributes': {'POSITION': uid}}}
    bad = Primitive(attributes=Attributes(POSITION=1), indices=0, mode=4, material=0)
    bad.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 1, 'attributes': {'POSITION': uid}}}

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[good, bad])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.6, 0.6, 0.6, 1.0]))]
    g.accessors = [
        Accessor(componentType=5125, count=nindices, type='SCALAR'),
        Accessor(componentType=5126, count=nverts, type='VEC3',
                 min=pts.min(0).tolist(), max=pts.max(0).tolist()),
    ]
    g.bufferViews = [
        BufferView(buffer=0, byteOffset=0, byteLength=len(blob)),
        BufferView(buffer=0, byteOffset=0, byteLength=len(blob) + 100000),
    ]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.extensionsUsed = ['KHR_draco_mesh_compression']
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes()), m


class TestMalformedDraco:
    def test_missing_accessor_raises_located_valueerror(self):
        # The stream lists TEXCOORD_0 but the primitive declares no matching
        # accessor: a located ValueError, not the AttributeError from dereferencing
        # None, and not a whole-scene abort.
        glb, _ = _draco_glb_semantic_without_accessor()
        g = pygltflib.GLTF2.load_from_bytes(glb)
        prim = g.meshes[0].primitives[0]
        with pytest.raises(ValueError) as exc:
            draco_mod.draco_arrays(g, prim, None)
        assert 'TEXCOORD_0' in str(exc.value)
        assert 'accessor' in str(exc.value).lower()

    def test_corrupt_primitive_skipped_scene_survives(self, caplog):
        # One primitive of the mesh is corrupt; it is skipped with a warning while
        # the sound primitive still builds -- matching the DracoPy-absent behaviour.
        glb, m = _draco_glb_valid_plus_corrupt()
        with caplog.at_level('WARNING'):
            scene = gltf.load_gltf(glb)
        assert scene is not None
        shape = _find_shape(scene.group)
        assert shape is not None
        assert shape.geometry.positions.shape[0] == len(np.asarray(m.points))
        assert any('draco' in r.getMessage().lower() for r in caplog.records)


class TestWarnOnceWithoutResolver:
    def test_missing_library_warns_once_when_resolver_is_none(self, monkeypatch, caplog):
        # With no resolver to stash the dedupe flag on, the "install DracoPy"
        # warning must still fire only once across repeated primitives.
        monkeypatch.setattr(draco_mod, '_warned_missing_no_resolver', False)
        with caplog.at_level('WARNING'):
            draco_mod._warn_missing_once(None)
            draco_mod._warn_missing_once(None)
        draco_warnings = [r for r in caplog.records
                          if 'draco' in r.getMessage().lower()]
        assert len(draco_warnings) == 1


def _draco_box_glb():
    """A self-contained Draco-compressed unit cube with a directional light.

    No texture and no IBL dependency, so it renders to pixels through the viewer's
    fast path (the textured Khronos models exercise a slower analytic-sky settle).
    The whole geometry lives in one Draco bufferView; the attribute accessors carry
    no bufferView, exactly as an exported Draco asset does.
    """
    c = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)]
    verts, faces = [], []
    for a, b, d, e in quads:
        base = len(verts)
        verts += [c[a], c[b], c[d], c[e]]
        faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    positions = np.array(verts, dtype=np.float64) * 0.6
    faces = np.array(faces, dtype=np.uint32)
    blob = DracoPy.encode(positions, faces)
    m = DracoPy.decode(blob)
    uid_by_type = {a['attribute_type']: a['unique_id'] for a in m.attributes}
    pts = np.asarray(m.points, dtype=np.float32)
    nverts = len(pts)
    nindices = len(np.asarray(m.faces).ravel())

    prim = Primitive(attributes=Attributes(POSITION=1), indices=0, mode=4, material=0)
    prim.extensions = {'KHR_draco_mesh_compression': {
        'bufferView': 0, 'attributes': {'POSITION': uid_by_type[0]}}}

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0, 1])]
    g.nodes = [
        Node(mesh=0),
        Node(extensions={'KHR_lights_punctual': {'light': 0}}),
    ]
    g.meshes = [Mesh(primitives=[prim])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.8, 0.3, 0.2, 1.0], metallicFactor=0.0, roughnessFactor=0.7))]
    g.accessors = [
        Accessor(componentType=5125, count=nindices, type='SCALAR'),
        Accessor(componentType=5126, count=nverts, type='VEC3',
                 min=pts.min(0).tolist(), max=pts.max(0).tolist()),
    ]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(blob))]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.extensions = {'KHR_lights_punctual': {'lights': [
        {'type': 'directional', 'intensity': 3.0, 'color': [1, 1, 1]}]}}
    g.extensionsUsed = ['KHR_draco_mesh_compression', 'KHR_lights_punctual']
    g.extensionsRequired = ['KHR_draco_mesh_compression']
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


class TestDracoRender:
    """A Draco primitive must render to real pixels, not just decode to arrays."""

    def test_draco_cube_renders_non_blank(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        glb = tmp_path / "draco_cube.glb"
        glb.write_bytes(_draco_box_glb())
        out = str(tmp_path / "draco_cube.png")
        args = [str(glb), '--no-cameras', '--no-physics', '--no-rotate',
                '--no-shadows', '--background', '0,0,0', '--yaw', '0.6',
                '--capture', out, '--frames', '6', '--capture-delay', '0.2',
                '--size', '320x240']
        try:
            subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                           timeout=180, capture_output=True, text=True,
                           cwd=TESTS_DIR + '/..')
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        arr = np.asarray(Image.open(out).convert("RGB")).astype(int)
        assert arr.any(), "captured Draco frame is all black"
        # The lit reddish cube must actually cover a chunk of the frame.
        lit = (arr.sum(axis=2) > 30)
        assert lit.mean() > 0.02, "Draco cube barely visible in the render"


@pytest.mark.network
class TestKhronosDuckDraco:
    """The Duck Draco variant must decode to the same counts as uncompressed Duck."""

    def _load(self, variant, cache):
        base = ('https://raw.githubusercontent.com/KhronosGroup/'
                'glTF-Sample-Assets/main/Models/Duck')
        return gltf.load_gltf_url('%s/%s/Duck.gltf' % (base, variant), cache)

    def test_duck_draco_counts_match_uncompressed(self, tmp_path):
        cache = str(tmp_path)
        try:
            draco = self._load('glTF-Draco', cache)
            plain = self._load('glTF', cache)
        except Exception as err:  # pragma: no cover - network/offline guard
            pytest.skip("network unavailable for Khronos sample fetch: %s" % err)
        dshape = _find_shape(draco.group)
        pshape = _find_shape(plain.group)
        assert dshape is not None and pshape is not None
        dpos = dshape.geometry.positions
        ppos = pshape.geometry.positions
        assert dpos.shape == ppos.shape
        # Draco is lossy (quantized), so compare bounding boxes, not exact verts.
        assert np.allclose(dpos.min(0), ppos.min(0), atol=1.0)
        assert np.allclose(dpos.max(0), ppos.max(0), atol=1.0)
        assert len(dshape.geometry.indices) == len(pshape.geometry.indices)
