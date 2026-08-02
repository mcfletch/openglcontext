"""Unit tests for the glTF loader using an in-memory synthetic GLB (no GL, no net)."""
import os

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders import resolver
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def _triangle_glb(with_normals=False, indices=True):
    pos = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=np.float32)
    blob = pos.tobytes()
    accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                          max=pos.max(0).tolist(), min=pos.min(0).tolist())]
    views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
    attrs = Attributes(POSITION=0)
    prim_idx = None
    if indices:
        idx = np.array([0, 1, 2], dtype=np.uint32)
        views.append(BufferView(buffer=0, byteOffset=len(blob), byteLength=idx.nbytes))
        accessors.append(Accessor(bufferView=1, componentType=5125, count=3, type='SCALAR'))
        blob += idx.tobytes()
        prim_idx = 1

    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[0.2, 0.8, 0.3, 0.5], metallicFactor=0.25, roughnessFactor=0.6),
        emissiveFactor=[0.1, 0.0, 0.0], alphaMode='BLEND', doubleSided=True)]
    g.meshes = [Mesh(primitives=[Primitive(attributes=attrs, indices=prim_idx, material=0)])]
    g.accessors = accessors
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _find_shape(node):
    for child in getattr(node, 'children', []) or []:
        if getattr(child, 'geometry', None) is not None:
            return child
        found = _find_shape(child)
        if found is not None:
            return found
    return None


class TestSyntheticGLB:
    def test_loads_mesh_geometry(self):
        scene = gltf.load_gltf(_triangle_glb())
        shape = _find_shape(scene.group)
        assert shape is not None
        mesh = shape.geometry
        assert isinstance(mesh, PBRMesh)
        assert mesh.positions.shape == (3, 3)
        assert mesh.indices.tolist() == [0, 1, 2]

    def test_maps_material_fields(self):
        scene = gltf.load_gltf(_triangle_glb())
        mat = _find_shape(scene.group).appearance.material
        assert isinstance(mat, PBRMaterial)
        assert tuple(round(float(x), 2) for x in mat.baseColor) == (0.2, 0.8, 0.3)
        assert mat.metallic == 0.25 and mat.roughness == 0.6
        assert round(float(mat.transparency), 2) == 0.5     # 1 - baseColor alpha
        assert mat.alphaMode == 'BLEND'
        assert bool(mat.doubleSided) is True
        assert tuple(round(float(x), 2) for x in mat.emissiveColor) == (0.1, 0.0, 0.0)

    def test_estimates_normals_when_absent(self):
        mesh = _find_shape(gltf.load_gltf(_triangle_glb()).group).geometry
        assert mesh.normals is not None and mesh.normals.shape == (3, 3)
        # triangle in the z=0 plane -> normal along +/- Z
        assert abs(abs(mesh.normals[0][2]) - 1.0) < 1e-4

    def test_non_indexed_primitive(self):
        mesh = _find_shape(gltf.load_gltf(_triangle_glb(indices=False)).group).geometry
        assert mesh.indices is None
        assert mesh.positions.shape == (3, 3)

    def test_vertex_colors_decoded(self):
        # a triangle with a COLOR_0 (VEC4 float) attribute
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        col = np.array([[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]], dtype=np.float32)
        blob = pos.tobytes() + col.tobytes()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.meshes = [Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0, COLOR_0=1))])]
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5126, count=3, type='VEC4'),
        ]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
            BufferView(buffer=0, byteOffset=pos.nbytes, byteLength=col.nbytes),
        ]
        g.buffers = [Buffer(byteLength=len(blob))]
        g.set_binary_blob(blob)
        mesh = _find_shape(gltf.load_gltf(b"".join(g.save_to_bytes())).group).geometry
        assert mesh.colors is not None and mesh.colors.shape == (3, 4)
        assert np.allclose(mesh.colors[0], [1, 0, 0, 1])

    def test_bounds_for_framing(self):
        scene = gltf.load_gltf(_triangle_glb())
        assert scene.radius > 0
        assert len(scene.center) == 3


def _normal_mapped_triangle_glb():
    """A UV-mapped triangle whose material carries a (tiny, flat) normalTexture but
    no TANGENT attribute -- the case where the loader must synthesize tangents."""
    import io
    from PIL import Image as PILImage
    from pygltflib import Image as GLTFImage, Sampler, Texture, NormalMaterialTexture
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    uv = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32)
    buf = io.BytesIO()
    PILImage.new('RGB', (2, 2), (128, 128, 255)).save(buf, format='PNG')
    png = buf.getvalue()
    blob = pos.tobytes() + uv.tobytes() + png
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, TEXCOORD_0=1), material=0)])]
    g.accessors = [
        Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                 max=pos.max(0).tolist(), min=pos.min(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=3, type='VEC2'),
    ]
    g.bufferViews = [
        BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
        BufferView(buffer=0, byteOffset=pos.nbytes, byteLength=uv.nbytes),
        BufferView(buffer=0, byteOffset=pos.nbytes + uv.nbytes, byteLength=len(png)),
    ]
    g.images = [GLTFImage(bufferView=2, mimeType='image/png')]
    g.samplers = [Sampler()]
    g.textures = [Texture(source=0, sampler=0)]
    g.materials = [Material(normalTexture=NormalMaterialTexture(index=0))]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


class TestTangentEstimation:
    """A normal map does nothing without tangents -- the pbr shader disables normal
    mapping when the tangent is zero -- so the loader synthesizes tangents from the
    UVs whenever a normal-mapped primitive ships none (glTF 3.7.2.1)."""

    def _uv_triangle(self, uv):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        nrm = np.array([[0, 0, 1]] * 3, dtype=np.float32)
        return gltf.meshes.estimate_tangents(pos, nrm, np.asarray(uv, np.float32),
                                       np.array([0, 1, 2], np.uint32))

    def test_tangent_points_along_the_u_axis(self):
        # U runs along +X, V along +Y -> tangent is +X. glTF reconstructs the
        # bitangent as cross(N,T)*w with green-up normal maps, so the standard
        # orientation is w = -1 (verified against NormalTangentMirrorTest's supplied
        # tangents -- the opposite sign shows a hard dark band on rotated-UV cells).
        t = self._uv_triangle([[0, 0], [1, 0], [0, 1]])
        assert t.shape == (3, 4)
        assert np.allclose(t[0, :3], [1, 0, 0], atol=1e-5)
        assert t[0, 3] == -1.0

    def test_handedness_flips_with_mirrored_v(self):
        # V running -Y mirrors the surface, so the bitangent handedness flips (to
        # +1, the negation of the standard-orientation -1).
        t = self._uv_triangle([[0, 0], [1, 0], [0, -1]])
        assert t[0, 3] == 1.0

    def test_partial_triangle_and_non_indexed_are_guarded(self):
        # 4 verts = one triangle + a trailing vertex; the extra vertex gets no
        # tangent (stays zero) rather than crashing, mirroring _estimate_normals.
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]], dtype=np.float32)
        nrm = np.array([[0, 0, 1]] * 4, dtype=np.float32)
        uv = np.array([[0, 0], [1, 0], [0, 1], [0, 0]], dtype=np.float32)
        t = gltf.meshes.estimate_tangents(pos, nrm, uv, None)      # non-indexed
        assert t.shape == (4, 4)
        assert np.allclose(t[3, :3], [0, 0, 0])

    def test_degenerate_uvs_leave_zero_tangent(self):
        # All-identical UVs give a zero UV gradient; the tangent must be zero (the
        # shader then falls back to the geometric normal) and never NaN.
        t = self._uv_triangle([[0, 0], [0, 0], [0, 0]])
        assert np.isfinite(t).all()
        assert np.allclose(t[:, :3], 0.0)

    def test_generated_for_normal_mapped_primitive(self):
        mesh = _find_shape(gltf.load_gltf(_normal_mapped_triangle_glb()).group).geometry
        assert mesh.tangents is not None and mesh.tangents.shape == (3, 4)

    def test_not_generated_without_normal_map(self):
        # _triangle_glb has UVs-free geometry and no normal map -> gate stays shut.
        mesh = _find_shape(gltf.load_gltf(_triangle_glb()).group).geometry
        assert mesh.tangents is None


def _triangle_with_cameras_glb(names=(None,)):
    """A triangle plus one perspective camera per entry in ``names`` (None = unnamed),
    each translated to a distinct +Z position so their poses differ."""
    from pygltflib import Camera, Perspective
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    blob = pos.tobytes()
    g = GLTF2()
    g.scene = 0
    node_indices = [0]
    g.nodes = [Node(mesh=0)]
    g.cameras = []
    for i, name in enumerate(names):
        g.cameras.append(Camera(type='perspective', name=name,
                                perspective=Perspective(yfov=0.6, znear=0.2, zfar=50.0)))
        g.nodes.append(Node(camera=i, name=name, translation=[0.0, 0.0, 5.0 + i]))
        node_indices.append(len(g.nodes) - 1)
    g.scenes = [Scene(nodes=node_indices)]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
    g.meshes = [Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0),
                                           material=0)])]
    g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                            max=pos.max(0).tolist(), min=pos.min(0).tolist())]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


class TestCameraExtraction:
    def _triangle_with_camera_glb(self):
        return _triangle_with_cameras_glb()

    def test_camera_pose_extracted(self):
        scene = gltf.load_gltf(self._triangle_with_camera_glb())
        assert scene.camera is not None
        # camera node sits at z=5 looking down -Z
        assert round(scene.camera['position'][2], 1) == 5.0
        assert round(scene.camera['fov'], 2) == 0.6
        assert scene.camera['forward'][2] < 0   # looks toward -Z

    def test_no_camera_when_absent(self):
        scene = gltf.load_gltf(_triangle_glb())
        assert scene.camera is None


class TestViewpointNodes:
    def test_one_viewpoint_per_camera(self):
        scene = gltf.load_gltf(_triangle_with_cameras_glb(names=('near', 'far', 'top')))
        assert len(scene.viewpoints) == len(scene.cameras) == 3

    def test_viewpoint_pose_and_name(self):
        from OpenGLContext.loaders.gltf import look_orientation
        scene = gltf.load_gltf(_triangle_with_cameras_glb(names=('aerial',)))
        vp = scene.viewpoints[0]
        assert vp.description == 'aerial'
        assert round(float(vp.position[2]), 1) == 5.0
        assert round(float(vp.fieldOfView), 2) == 0.6
        # near/far carried through as plain attributes for moveTo to apply
        assert vp.near == 0.2 and vp.far == 50.0
        expect = look_orientation(scene.cameras[0]['forward'], scene.cameras[0]['up'])
        assert np.allclose([float(x) for x in vp.orientation], expect, atol=1e-6)

    def test_viewpoint_addressable_by_name(self):
        scene = gltf.load_gltf(_triangle_with_cameras_glb(names=('hero',)))
        # the camera name seeds the DEF, so the Viewpoint is findable in the registry
        defs = scene.sceneGraph.defNames
        assert any(vp is node for node in defs.values() for vp in scene.viewpoints)

    def test_no_viewpoints_when_absent(self):
        scene = gltf.load_gltf(_triangle_glb())
        assert scene.viewpoints == []


class TestSampleCatalog:
    def test_sample_model_url(self):
        url = gltf.sample_model_url('Duck')
        assert url.endswith('/Duck/glTF-Binary/Duck.glb')
        # The current sample repo is glTF-Sample-Assets (glTF-Sample-Models is
        # deprecated/frozen and 404s for newer models).
        assert 'KhronosGroup/glTF-Sample-Assets' in url

    def test_catalog_constant_nonempty(self):
        assert 'DamagedHelmet' in gltf.SAMPLE_MODELS


class TestTextureSource:
    """`_texture_source` resolves which image a texture samples, including the
    EXT_texture_webp fallback used when the base ``source`` is omitted."""

    class _Tex:
        def __init__(self, source=None, extensions=None):
            self.source = source
            self.extensions = extensions

    def test_plain_source_used_directly(self):
        assert gltf.textures._texture_source(self._Tex(source=4)) == 4

    def test_webp_extension_fills_in_missing_source(self):
        tex = self._Tex(source=None,
                        extensions={'EXT_texture_webp': {'source': 7}})
        assert gltf.textures._texture_source(tex) == 7

    def test_base_source_wins_over_webp_extension(self):
        tex = self._Tex(source=2,
                        extensions={'EXT_texture_webp': {'source': 7}})
        assert gltf.textures._texture_source(tex) == 2

    def test_basisu_is_not_consulted(self):
        # KTX2/Basis needs a transcoder Pillow lacks, so it must NOT be treated
        # as a usable source -- resolve to None instead of a KTX2 image index.
        tex = self._Tex(source=None,
                        extensions={'KHR_texture_basisu': {'source': 3}})
        assert gltf.textures._texture_source(tex) is None

    def test_no_source_no_extension_is_none(self):
        assert gltf.textures._texture_source(self._Tex()) is None


class TestPunctualLight:
    """KHR_lights_punctual -> scenegraph light: local coords (the node Transform
    places it), inverse-square falloff, and a carried `range` for the shader."""

    def test_point_light_is_local_with_inverse_square_and_range(self):
        world = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0],
                          [-2.25, 0.0, 0.2, 1]], dtype='d')   # off-centre node
        light = gltf.scene._light_node(
            {'type': 'point', 'intensity': 1.0, 'range': 1.125,
             'color': [1, 0, 0]}, world)
        # Local origin: the world position lives on the parent Transform, not here,
        # so it is NOT baked in again (that double-transform displaced the light).
        assert tuple(light.location) == (0.0, 0.0, 0.0)
        # Pure quadratic attenuation == glTF inverse-square.
        assert tuple(float(a) for a in light.attenuation) == (0.0, 0.0, 1.0)
        assert light._gltf_range == 1.125

    def test_spot_light_local_and_carries_range(self):
        light = gltf.scene._light_node(
            {'type': 'spot', 'intensity': 5.0, 'range': 5.0,
             'spot': {'outerConeAngle': 0.7, 'innerConeAngle': 0.3}},
            np.eye(4))
        assert tuple(light.location) == (0.0, 0.0, 0.0)
        assert tuple(light.direction) == (0.0, 0.0, -1.0)
        assert light._gltf_range == 5.0

    def test_directional_has_no_falloff_and_no_range(self):
        light = gltf.scene._light_node({'type': 'directional', 'intensity': 512.0},
                                 np.eye(4))
        # Directional lights are placeless; they must not carry a point-light range.
        assert not hasattr(light, '_gltf_range')
        assert tuple(light.direction) == (0.0, 0.0, -1.0)


class TestMeterExposure:
    """The load-time light meter: absolute-unit scenes stop down, else 1.0."""

    class _L:
        def __init__(self, intensity):
            self.intensity = intensity

    def test_no_lights_is_neutral(self):
        assert gltf.scene._meter_exposure([], (0, 0, 0)) == 1.0

    def test_normalized_intensities_stay_neutral(self):
        # A 1-cd point light 1 unit away delivers ~1 lux -- below target, no stop-down.
        meter = [(self._L(1.0), (1.0, 0.0, 0.0))]
        assert gltf.scene._meter_exposure(meter, (0, 0, 0)) == 1.0

    def test_bright_directional_stops_down(self):
        # 512 lux directional -> exposure well below 1 so it can't clip to white.
        e = gltf.scene._meter_exposure([(self._L(512.0), None)], (0, 0, 0))
        assert 0.0 < e < 0.05

    def test_modest_lights_stay_neutral(self):
        # A few lux (e.g. the Parthenon rig) must not be stopped down, or its
        # baseline shifts. 4-5 lux is below the overexposure threshold.
        assert gltf.scene._meter_exposure([(self._L(4.4), None)], (0, 0, 0)) == 1.0

    def test_never_brightens(self):
        e = gltf.scene._meter_exposure([(self._L(0.01), None)], (0, 0, 0))
        assert e == 1.0


def _have_internet():
    import socket
    try:
        socket.create_connection(("raw.githubusercontent.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _have_internet(), reason="no internet")
class TestCatalogNetwork:
    def test_fetch_full_catalog(self):
        cat = gltf.fetch_sample_catalog()
        assert len(cat) > 20
        names = [e['name'] for e in cat]
        assert 'DamagedHelmet' in names
        helmet = next(e for e in cat if e['name'] == 'DamagedHelmet')
        assert helmet['screenshot_url'].startswith('http')
        assert 'screenshot' in helmet['screenshot_url']

    def test_load_sample_box(self):
        scene = gltf.load_sample('Box')
        assert scene.radius > 0


def _glb_from(accessors, views, blob, prim_kw=None, node_kw=None, materials=None,
              extra_nodes=None, scene_nodes=None):
    """Assemble a single-mesh GLB from prebuilt accessor/bufferView/blob pieces."""
    g = GLTF2()
    g.scene = 0
    g.nodes = [Node(mesh=0, **(node_kw or {}))]
    if extra_nodes:
        g.nodes.extend(extra_nodes)
    g.scenes = [Scene(nodes=scene_nodes or [0])]
    g.materials = materials or [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
    prim = Primitive(attributes=Attributes(POSITION=0), material=0, **(prim_kw or {}))
    g.meshes = [Mesh(primitives=[prim])]
    g.accessors = accessors
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(bytes(blob))
    return b"".join(g.save_to_bytes())


def _quad_strip_glb(mode, indexed=True):
    """4 coplanar verts; drawn under the given primitive mode."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32)
    blob = bytearray(pos.tobytes())
    accessors = [Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                          max=pos.max(0).tolist(), min=pos.min(0).tolist())]
    views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
    prim_kw = {'mode': mode}
    if indexed:
        idx = np.array([0, 1, 2, 3], dtype=np.uint32)
        views.append(BufferView(buffer=0, byteOffset=len(blob), byteLength=idx.nbytes))
        accessors.append(Accessor(bufferView=1, componentType=5125, count=4, type='SCALAR'))
        blob += idx.tobytes()
        prim_kw['indices'] = 1
    return _glb_from(accessors, views, blob, prim_kw=prim_kw)


class TestPrimitiveMode:
    def test_triangle_strip_converted_to_list(self):
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(5)).group).geometry  # TRIANGLE_STRIP
        assert mesh.indices is not None
        # strip [0,1,2,3] -> triangles (0,1,2),(2,1,3) with alternating winding
        assert mesh.indices.tolist() == [0, 1, 2, 2, 1, 3]

    def test_triangle_fan_converted_to_list(self):
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(6)).group).geometry  # TRIANGLE_FAN
        assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]

    def test_explicit_triangles_mode_unchanged(self):
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(4, indexed=True)).group).geometry
        assert mesh.indices.tolist() == [0, 1, 2, 3]

    def test_points_primitive_rendered_as_points(self):
        # mode 0 = POINTS: now drawn as GL_POINTS (glTF mode == GL enum), not skipped
        from OpenGL.GL import GL_POINTS
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(0)).group).geometry
        assert mesh is not None and mesh.draw_mode == GL_POINTS

    def test_line_primitive_rendered_as_lines(self):
        from OpenGL.GL import GL_LINES
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(1)).group).geometry  # LINES
        assert mesh is not None and mesh.draw_mode == GL_LINES

    def test_non_indexed_strip_converted(self):
        mesh = _find_shape(gltf.load_gltf(_quad_strip_glb(5, indexed=False)).group).geometry
        assert mesh.indices is not None and mesh.indices.tolist() == [0, 1, 2, 2, 1, 3]

    def test_normal_estimation_guards_non_multiple_of_three(self):
        # 4 non-indexed positions, no normals: estimate must not raise on reshape
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        accessors = [Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                              max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        mesh = _find_shape(gltf.load_gltf(_glb_from(accessors, views, blob)).group).geometry
        assert mesh.normals is not None and mesh.normals.shape == (4, 3)


class TestAlphaMode:
    def _material_glb(self, alpha_mode, base_alpha):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                              max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        mats = [Material(alphaMode=alpha_mode, pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorFactor=[1, 1, 1, base_alpha]))]
        return _glb_from(accessors, views, blob, materials=mats)

    def test_opaque_ignores_base_alpha(self):
        mat = _find_shape(gltf.load_gltf(self._material_glb('OPAQUE', 0.3)).group).appearance.material
        assert float(mat.transparency) == 0.0

    def test_mask_ignores_base_alpha(self):
        mat = _find_shape(gltf.load_gltf(self._material_glb('MASK', 0.3)).group).appearance.material
        assert float(mat.transparency) == 0.0

    def test_blend_derives_transparency(self):
        mat = _find_shape(gltf.load_gltf(self._material_glb('BLEND', 0.3)).group).appearance.material
        assert round(float(mat.transparency), 2) == 0.7


class TestSparseAccessor:
    def test_sparse_substitution_applied(self):
        from pygltflib import (Sparse as AccessorSparse, AccessorSparseIndices,
                               AccessorSparseValues)
        base = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.float32)
        sidx = np.array([1, 3], dtype=np.uint16)
        svals = np.array([[5, 6, 7], [8, 9, 10]], dtype=np.float32)
        blob = bytearray(base.tobytes())
        idx_off = len(blob)
        blob += sidx.tobytes()
        val_off = len(blob)
        blob += svals.tobytes()
        views = [
            BufferView(buffer=0, byteOffset=0, byteLength=base.nbytes),
            BufferView(buffer=0, byteOffset=idx_off, byteLength=sidx.nbytes),
            BufferView(buffer=0, byteOffset=val_off, byteLength=svals.nbytes),
        ]
        sparse = AccessorSparse(
            count=2,
            indices=AccessorSparseIndices(bufferView=1, byteOffset=0, componentType=5123),
            values=AccessorSparseValues(bufferView=2, byteOffset=0))
        accessors = [Accessor(bufferView=0, componentType=5126, count=4, type='VEC3',
                              sparse=sparse,
                              max=[8, 9, 10], min=[0, 0, 0])]
        mesh = _find_shape(gltf.load_gltf(_glb_from(accessors, views, blob)).group).geometry
        assert mesh.positions[1].tolist() == [5, 6, 7]
        assert mesh.positions[3].tolist() == [8, 9, 10]
        assert mesh.positions[0].tolist() == [0, 0, 0]

    def test_no_bufferview_and_no_sparse_raises(self):
        acc = Accessor(bufferView=None, componentType=5126, count=3, type='VEC3')
        with pytest.raises(NotImplementedError):
            gltf.accessors._read_accessor(_FakeGLTF([acc]), 0, None)


class _FakeGLTF:
    def __init__(self, accessors):
        self.accessors = accessors


class TestInterleavedAccessor:
    def test_interleaved_position_decoded(self):
        # interleave POSITION(vec3 f32) + a 4-byte pad -> byteStride 16
        pos = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32)
        stride = 16
        raw = bytearray()
        for row in pos:
            raw += row.tobytes() + b'\x00\x00\x00\x00'
        accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                              byteOffset=0, max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        views = [BufferView(buffer=0, byteOffset=0, byteLength=len(raw), byteStride=stride)]
        mesh = _find_shape(gltf.load_gltf(_glb_from(accessors, views, raw)).group).geometry
        assert np.allclose(mesh.positions, pos)


class TestQuaternionNormalization:
    def test_non_unit_quaternion_normalized(self):
        # a 90-deg rotation about +Y, scaled x2 (non-unit) -> still 90 deg about Y
        s = np.sin(np.pi / 4)
        q = [0.0, s, 0.0, np.cos(np.pi / 4)]
        q = [2.0 * v for v in q]  # denormalize
        xyzr = gltf.transforms._quat_to_xyzr(q)
        assert abs(xyzr[3] - np.pi / 2) < 1e-4
        assert abs(xyzr[1] - 1.0) < 1e-4  # axis +Y


class TestNormalizedComponents:
    def test_signed_normalized_clamped_to_minus_one(self):
        # int8 -128 normalizes to -1.0 (not -128/127) per glTF spec
        assert abs(gltf.accessors._normalize_component(np.int8(-128)) - (-1.0)) < 1e-6
        assert abs(gltf.accessors._normalize_component(np.int8(127)) - 1.0) < 1e-6

    def test_unsigned_normalized(self):
        assert abs(gltf.accessors._normalize_component(np.uint8(255)) - 1.0) < 1e-6
        assert abs(gltf.accessors._normalize_component(np.uint8(0)) - 0.0) < 1e-6


class TestBufferDecodeCache:
    def test_data_uri_buffer_decoded_once(self, monkeypatch):
        # two accessors sharing one data-URI buffer -> base64 decoded a single time
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        nrm = np.tile([0, 0, 1], (3, 1)).astype(np.float32)
        blob = pos.tobytes() + nrm.tobytes()
        import base64 as _b64
        uri = 'data:application/octet-stream;base64,' + _b64.b64encode(blob).decode()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
        g.meshes = [Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0, NORMAL=1), material=0)])]
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5126, count=3, type='VEC3'),
        ]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
            BufferView(buffer=0, byteOffset=pos.nbytes, byteLength=nrm.nbytes),
        ]
        g.buffers = [Buffer(uri=uri, byteLength=len(blob))]

        calls = {'n': 0}
        real = resolver.base64.b64decode

        def counting(data, *a, **k):
            calls['n'] += 1
            return real(data, *a, **k)
        monkeypatch.setattr(resolver.base64, 'b64decode', counting)
        # Load as .gltf JSON so the data-URI buffer survives (GLB packing would
        # otherwise absorb it into the binary blob and skip base64 entirely).
        gltf.load_gltf(g.gltf_to_json().encode('utf-8'))
        assert calls['n'] == 1


class TestAccessorValidation:
    """Mismatched counts / out-of-range indices must raise a located
    error, not an opaque numpy failure or a silent wrong-geometry read."""

    def test_truncated_buffer_raises_located(self):
        # accessor claims 100 vec3 (1200 bytes) but the buffer holds only 12
        acc = Accessor(bufferView=0, componentType=5126, count=100, type='VEC3')
        g = _FakeGLTF([acc])
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=12)]
        g.buffers = [Buffer(byteLength=12)]

        class _R:
            _buffers = {0: b'\x00' * 12}
        with pytest.raises(ValueError, match='accessor 0'):
            gltf.accessors._accessor_base(g, acc, _R(), 0)

    def test_out_of_range_index_raises(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        idx = np.array([0, 1, 5], dtype=np.uint32)   # vertex 5 with only 3 vertices
        blob = bytearray(pos.tobytes())
        idx_off = len(blob)
        blob += idx.tobytes()
        accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5125, count=3, type='SCALAR'),
        ]
        views = [
            BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
            BufferView(buffer=0, byteOffset=idx_off, byteLength=idx.nbytes),
        ]
        with pytest.raises(ValueError, match='out of range'):
            gltf.load_gltf(_glb_from(accessors, views, blob, prim_kw={'indices': 1}))

    def test_attribute_count_mismatch_raises(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        nrm = np.tile([0, 0, 1], (2, 1)).astype(np.float32)  # 2 normals, 3 positions
        blob = bytearray(pos.tobytes())
        n_off = len(blob)
        blob += nrm.tobytes()
        accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5126, count=2, type='VEC3'),
        ]
        views = [
            BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
            BufferView(buffer=0, byteOffset=n_off, byteLength=nrm.nbytes),
        ]
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
        g.meshes = [Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0, NORMAL=1), material=0)])]
        g.accessors = accessors
        g.bufferViews = views
        g.buffers = [Buffer(byteLength=len(blob))]
        g.set_binary_blob(bytes(blob))
        with pytest.raises(ValueError, match='NORMAL'):
            gltf.load_gltf(b"".join(g.save_to_bytes()))


class TestNodeCycle:
    """A cyclic node hierarchy must raise, not stack-overflow."""

    def test_self_cycle_detected(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                              max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        data = _glb_from(accessors, views, blob, node_kw={'children': [0]})
        with pytest.raises(ValueError, match='cycle'):
            gltf.load_gltf(data)

    def test_mutual_cycle_detected(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                              max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        views = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        # node 0 -> child 1 -> child 0 (mutual cycle)
        data = _glb_from(accessors, views, blob, node_kw={'children': [1]},
                         extra_nodes=[Node(children=[0])])
        with pytest.raises(ValueError, match='cycle'):
            gltf.load_gltf(data)


class TestCacheDir:
    """Fetched assets cache under a per-user directory, not the
    shared world-writable system temp root."""

    def test_cache_dir_is_user_scoped(self):
        from OpenGLContext import userpaths
        d = resolver._default_cache_dir()
        assert 'cache' in os.path.basename(d).lower()
        base = userpaths.appdatadirectory()
        assert os.path.commonpath([os.path.normpath(d), os.path.normpath(base)]) \
            == os.path.normpath(base)

    def test_fetch_url_uses_default_cache_dir(self, monkeypatch, tmp_path):
        calls = {}
        monkeypatch.setattr(resolver, '_default_cache_dir', lambda: str(tmp_path / 'c'))

        class _Resp:
            """Serves its body once and is then exhausted, as a real one is."""

            def __init__(self):
                self._left = b'glTFdummy'

            def read(self, n=-1):
                data, self._left = self._left, b''
                return data

            def close(self):
                pass

        # The fetch now goes through a redirect-guarded opener, so
        # patch build_opener rather than urlopen.
        class _Opener:
            def open(self, url, timeout=None):
                return _Resp()
        monkeypatch.setattr(resolver.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        data = resolver._fetch_url('http://example.invalid/x.glb')
        assert data == b'glTFdummy'
        assert (tmp_path / 'c').is_dir()


class TestCachePurge:
    """purge_cache evicts assets unused past a cutoff; a cache hit is touched so
    its mtime tracks last use and the eviction keeps the working set."""

    def test_purge_removes_only_stale_entries(self, tmp_path):
        import time
        cache = tmp_path / 'c'
        cache.mkdir()
        fresh, stale = cache / 'fresh.bin', cache / 'stale.bin'
        fresh.write_bytes(b'a')
        stale.write_bytes(b'b')
        old = time.time() - 40 * 86400
        os.utime(stale, (old, old))
        removed = resolver.purge_cache(cache_dir=str(cache), max_age_days=30)
        assert removed == 1
        assert fresh.exists() and not stale.exists()

    def test_purge_missing_dir_is_noop(self, tmp_path):
        assert resolver.purge_cache(cache_dir=str(tmp_path / 'nope')) == 0

    def test_cache_hit_touches_entry(self, tmp_path, monkeypatch):
        import time
        import hashlib
        cache = tmp_path / 'c'
        monkeypatch.setattr(resolver, '_default_cache_dir', lambda: str(cache))

        class _Resp:
            """Serves its body once and is then exhausted, as a real one is."""

            def __init__(self):
                self._left = b'glTFx'

            def read(self, n=-1):
                data, self._left = self._left, b''
                return data

            def close(self):
                pass

        class _Opener:
            def open(self, url, timeout=None):
                return _Resp()
        monkeypatch.setattr(resolver.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        url = 'http://example.invalid/x.glb'
        resolver._fetch_url(url)                       # populate the cache
        key = hashlib.sha1(url.encode('utf-8')).hexdigest() + '.glb'
        path = cache / key
        old = time.time() - 40 * 86400
        os.utime(path, (old, old))
        resolver._fetch_url(url)                       # cache hit -> touch
        assert os.path.getmtime(path) > old + 86400    # mtime bumped to ~now


class TestComponentConstants:
    """The float componentType enum is named, not an inline 5126."""

    def test_float_component_constant(self):
        assert gltf.accessors._COMPONENT_FLOAT == 5126
        assert gltf.accessors._COMPONENT_DTYPE[gltf.accessors._COMPONENT_FLOAT] == np.float32


class TestSameOriginFetch:
    """An external reference may only load from the same origin
    (scheme + host + port) as the document it came from."""

    def test_origin_is_scheme_host_port(self):
        assert resolver._origin('https://a.com:8443/x') == ('https', 'a.com:8443')

    def test_same_origin_distinctions(self):
        base = 'https://a.com/x/model.gltf'
        assert resolver._same_origin(base, 'https://a.com/x/buf.bin')     # same
        assert not resolver._same_origin(base, 'https://a.com:8443/y')    # port differs
        assert not resolver._same_origin(base, 'http://a.com/y')          # scheme differs
        assert not resolver._same_origin(base, 'https://b.com/y')         # host differs

    def test_cross_origin_and_file_rejected_without_fetching(self, monkeypatch):
        called = {'n': 0}

        def boom(*a, **k):
            called['n'] += 1
            raise AssertionError("must not fetch")
        monkeypatch.setattr(resolver.urllib.request, 'urlopen', boom)
        r = resolver.Resolver(base_url='https://example.com/a/model.gltf')
        with pytest.raises(IOError, match='same-origin'):
            r.fetch('https://evil.example.net/x.bin')
        with pytest.raises(IOError):
            r.fetch('file:///etc/passwd')
        with pytest.raises(IOError):
            r.fetch('http://169.254.169.254/latest/meta-data/')
        assert called['n'] == 0

    def test_same_origin_reference_is_fetched(self, monkeypatch):
        class _Resp:
            def read(self, n=-1):
                return b'OK'

            def close(self):
                pass
        seen = {}

        class _Opener:
            def open(self, request, timeout=None):
                # A Request rather than a bare URL: the fetch identifies itself
                # with a User-Agent, which some asset hosts require.
                seen['url'] = request.full_url
                seen['agent'] = request.get_header('User-agent')
                return _Resp()
        # Patch build_opener: the fetch is now made through a redirect-guarded
        # opener rather than a bare urlopen.
        monkeypatch.setattr(resolver.urllib.request, 'build_opener',
                            lambda *a, **k: _Opener())
        r = resolver.Resolver(base_url='https://example.com/a/model.gltf')
        assert r.fetch('buf.bin') == b'OK'
        assert seen['url'].startswith('https://example.com/a/')
        assert 'OpenGLContext' in seen['agent']


class TestLocalPathConfinement:
    """A local load stays inside its model directory."""

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(IOError):
            resolver._resolve_local(str(tmp_path), '../../etc/passwd')

    def test_absolute_rejected(self, tmp_path):
        with pytest.raises(IOError):
            resolver._resolve_local(str(tmp_path), '/etc/passwd')

    def test_url_scheme_rejected(self, tmp_path):
        with pytest.raises(IOError):
            resolver._resolve_local(str(tmp_path), 'http://evil/x')

    def test_relative_reference_ok(self, tmp_path):
        (tmp_path / 'sub').mkdir()
        (tmp_path / 'sub' / 'buf.bin').write_bytes(b'x')
        p = resolver._resolve_local(str(tmp_path), 'sub/buf.bin')
        assert p == os.path.realpath(str(tmp_path / 'sub' / 'buf.bin'))


class TestResourceSizeCap:
    """A single fetched/decoded resource is bounded."""

    def test_read_capped_rejects_overflow(self):
        class _Resp:
            def read(self, n=-1):
                return b'x' * n           # pretend the stream is huge
        with pytest.raises(ValueError, match='limit'):
            resolver._read_capped(_Resp(), 10)

    def test_data_uri_over_cap_rejected(self):
        uri = 'data:;base64,' + resolver.base64.b64encode(b'x' * 100).decode()
        with pytest.raises(ValueError):
            resolver._decode_data_uri(uri, max_bytes=10)


class TestDataUriParsing:
    """Robust data: URI decoding."""

    def test_base64_payload(self):
        uri = 'data:application/octet-stream;base64,' + resolver.base64.b64encode(b'hi').decode()
        assert resolver._decode_data_uri(uri) == b'hi'

    def test_percent_encoded_payload(self):
        assert resolver._decode_data_uri('data:text/plain,Hello%20World') == b'Hello World'

    def test_malformed_no_comma_raises(self):
        with pytest.raises(ValueError, match='data:'):
            resolver._decode_data_uri('data:nonsense')


class TestSceneRoots:
    """Tolerant scene-root computation."""

    def test_scene_nodes_none_yields_no_roots(self):
        class _S:
            nodes = None

        class _G:
            scenes = [_S()]
            scene = 0
            nodes = [object(), object()]
        assert gltf.scene._scene_root_indices(_G()) == []

    def test_no_scenes_excludes_child_nodes(self):
        class _N:
            def __init__(self, children=None):
                self.children = children

        class _G:
            scenes = None
            scene = None
            nodes = [_N(children=[1]), _N()]
        # node 0 parents node 1, so only node 0 is a true root
        assert gltf.scene._scene_root_indices(_G()) == [0]


def _glb_with_material(material, extra_nodes=None, animations=None,
                       ext_used=None, top_ext=None):
    """A one-triangle GLB whose single node uses ``material`` (a pygltflib Material),
    with optional extra nodes / animations / extension metadata for feature tests."""
    pos = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=np.float32)
    blob = pos.tobytes()
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)] + list(extra_nodes or [])
    g.materials = [material]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0), material=0)])]
    g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                            max=pos.max(0).tolist(), min=pos.min(0).tolist())]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
    g.buffers = [Buffer(byteLength=len(blob))]
    if animations is not None:
        g.animations = animations
    if ext_used is not None:
        g.extensionsUsed = ext_used
    if top_ext is not None:
        g.extensions = top_ext
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


class TestAnisotropyDispersion:
    """KHR_materials_anisotropy / KHR_materials_dispersion factor parsing."""

    def _material(self, mat):
        scene = gltf.load_gltf(_glb_with_material(mat))
        return _find_shape(scene.group).appearance.material

    def test_anisotropy_strength_and_rotation_read(self):
        m = Material(extensions={'KHR_materials_anisotropy': {
            'anisotropyStrength': 0.7, 'anisotropyRotation': 1.5}})
        mat = self._material(m)
        assert abs(mat.anisotropyStrength - 0.7) < 1e-6
        assert abs(mat.anisotropyRotation - 1.5) < 1e-6

    def test_dispersion_read(self):
        m = Material(extensions={'KHR_materials_dispersion': {'dispersion': 2.5}})
        assert abs(self._material(m).dispersion - 2.5) < 1e-6

    def test_defaults_zero_when_absent(self):
        mat = self._material(Material())
        assert mat.anisotropyStrength == 0.0
        assert mat.dispersion == 0.0


class TestJsonPointer:
    """The KHR_animation_pointer JSON-pointer resolver over a pygltflib tree."""

    def test_resolves_node_visibility_dict(self):
        g = GLTF2()
        g.nodes = [Node(extensions={'KHR_node_visibility': {'visible': True}})]
        parent, last, kind = gltf.animation._resolve_json_pointer(
            g, ['nodes', '0', 'extensions', 'KHR_node_visibility', 'visible'])
        assert kind == 'dict' and last == 'visible'
        assert parent is g.nodes[0].extensions['KHR_node_visibility']

    def test_missing_path_returns_none(self):
        g = GLTF2()
        g.nodes = [Node()]
        assert gltf.animation._resolve_json_pointer(
            g, ['nodes', '0', 'extensions', 'nope', 'x']) is None


class TestAnimationPointerLive:
    """A KHR_animation_pointer channel drives a material factor LIVE through the
    Player (not a static bake): the resolved setter mutates the material each frame."""

    def _build(self):
        # A material whose baseColorFactor is animated red->green via a pointer.
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        times = np.array([0.0, 1.0], dtype=np.float32)
        vals = np.array([[1, 0, 0, 1], [0, 1, 0, 1]], dtype=np.float32)  # red -> green
        head = pos.tobytes()
        extra = times.tobytes() + vals.tobytes()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorFactor=[1, 0, 0, 1]))]
        g.meshes = [Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0), material=0)])]
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5126, count=2, type='SCALAR',
                     max=[1.0], min=[0.0]),
            Accessor(bufferView=2, componentType=5126, count=2, type='VEC4')]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=len(head)),
            BufferView(buffer=0, byteOffset=len(head), byteLength=times.nbytes),
            BufferView(buffer=0, byteOffset=len(head) + times.nbytes,
                       byteLength=vals.nbytes)]
        g.buffers = [Buffer(byteLength=len(head) + len(extra))]
        from pygltflib import (Animation, AnimationChannel, AnimationChannelTarget,
                               AnimationSampler)
        g.animations = [Animation(
            samplers=[AnimationSampler(input=1, output=2, interpolation='LINEAR')],
            channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(
                path='pointer',
                extensions={'KHR_animation_pointer': {
                    'pointer': '/materials/0/pbrMetallicRoughness/baseColorFactor'}}))])]
        g.set_binary_blob(head + extra)
        return gltf.load_gltf(b"".join(g.save_to_bytes()))

    def _material(self, scene):
        return _find_shape(scene.group).appearance.material

    def test_pointer_channel_parsed(self):
        scene = self._build()
        assert len(scene.animations) == 1
        assert len(scene.animations[0].pointer_channels) == 1

    def test_player_drives_material_factor(self):
        scene = self._build()
        player = scene.player(0, loop=False)
        mat = self._material(scene)
        player.evaluate(0.0)      # red
        assert mat.baseColor[0] > 0.9 and mat.baseColor[1] < 0.1
        player.evaluate(1.0)      # green
        assert mat.baseColor[1] > 0.9 and mat.baseColor[0] < 0.1
        assert int(getattr(mat, '_ubo_version', 0)) >= 2   # each edit bumps the UBO


class TestNodeVisibilityChildPropagation:
    """An invisible node hides its whole subtree (spec: visible iff all ancestors are)."""

    def _build(self):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        # node 0 invisible, its child node 1 has a mesh -> child must be hidden too.
        g.nodes = [Node(children=[1],
                        extensions={'KHR_node_visibility': {'visible': False}}),
                   Node(mesh=0)]
        g.meshes = [Mesh(primitives=[Primitive(attributes=Attributes(POSITION=0))])]
        g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                                max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=blob.__len__())]
        g.buffers = [Buffer(byteLength=len(blob))]
        g.set_binary_blob(blob)
        return gltf.load_gltf(b"".join(g.save_to_bytes()))

    def test_child_of_invisible_is_hidden(self):
        scene = self._build()
        assert _find_shape(scene.group) is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
