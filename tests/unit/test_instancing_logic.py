"""Headless tests for instancing key/grouping helpers with no GL.

Covers the content-signature, texture-set and pass-signature key builders, the
material-identity fallback keys, and the small value objects (InstanceGroup,
GLCapabilities). These are the pure batching-decision logic that runs on every
frame before any draw call.
"""
import numpy as np

from OpenGLContext.passes.instancing import (
    geometry_instance_key, geometry_texture_key, geometry_content_key,
    geometry_content_instance_key, InstanceGroup, GLCapabilities,
)


class Geom:
    """A geometry node with optional content signature / vertex arrays."""

    def __init__(self, content_key='__missing__', positions=None):
        if content_key != '__missing__':
            self.instanceContentKey = lambda: content_key
        if positions is not None:
            self.positions = positions


class RaisingGeom:
    def instanceContentKey(self):
        raise RuntimeError("no key")
    positions = None


class SlottedGeom:
    """Geometry that hashes its vertex arrays but rejects caching the result."""
    __slots__ = ('positions', 'normals', 'texcoords', 'tangents', 'colors',
                 'indices')

    def __init__(self, positions):
        self.positions = positions
        for name in ('normals', 'texcoords', 'tangents', 'colors', 'indices'):
            setattr(self, name, None)


class MatWithTexturesDict:
    def __init__(self, textures):
        self.textures = textures


class MatWithTextureAttrs:
    textures = None

    def __init__(self, base=None, normal=None):
        self.baseColorTexture = base
        self.normalTexture = normal


class Shape:
    def __init__(self, geometry, material=None, texture=None, appearance=True):
        self.geometry = geometry
        if appearance:
            self.appearance = type('A', (), {'material': material,
                                             'texture': texture})()
        else:
            self.appearance = None


def path(shape):
    return [shape]


class TestNoGeometry:
    def test_instance_key_none_without_geometry(self):
        assert geometry_instance_key(path(Shape(None))) is None

    def test_texture_key_none_without_geometry(self):
        assert geometry_texture_key(path(Shape(None))) is None

    def test_content_key_none_without_geometry(self):
        assert geometry_content_key(path(Shape(None))) is None

    def test_content_instance_key_none_without_geometry(self):
        assert geometry_content_instance_key(path(Shape(None))) is None


class TestMaterialTextureIds:
    def test_textures_dict_included_sorted_skipping_none(self):
        tex = object()
        g = Geom(content_key=('g',))
        m = MatWithTexturesDict({'baseColor': tex, 'normal': None})
        key = geometry_content_key(path(Shape(g, material=m)))
        # tex_key element is (channel, id(tex)); the None channel is dropped.
        tex_key = key[1]
        assert tex_key == (('baseColor', id(tex)),)

    def test_two_materials_same_textures_share_texkey(self):
        tex = object()
        g = Geom(content_key=('g',))
        a = geometry_content_key(path(Shape(g, MatWithTexturesDict({'baseColor': tex}))))
        b = geometry_content_key(path(Shape(g, MatWithTexturesDict({'baseColor': tex}))))
        assert a[1] == b[1]

    def test_single_texture_attribute_fallback(self):
        tex = object()
        g = Geom(content_key=('g',))
        m = MatWithTextureAttrs(base=tex)
        key = geometry_content_key(path(Shape(g, material=m)))
        assert key[1] == (('baseColorTexture', id(tex)),)

    def test_callable_texture_attribute_ignored(self):
        # PBRMaterial.texture is a lookup METHOD; it must not be treated as a map.
        g = Geom(content_key=('g',))
        m = MatWithTextureAttrs()
        m.baseColorTexture = lambda: None      # callable -> skipped
        key = geometry_content_key(path(Shape(g, material=m)))
        assert key[1] == ()


class TestContentSignature:
    def test_explicit_content_key_used(self):
        a = geometry_content_key(path(Shape(Geom(content_key=('Sphere', 1.0)))))
        b = geometry_content_key(path(Shape(Geom(content_key=('Sphere', 1.0)))))
        # Distinct nodes, equal explicit key -> same content component.
        assert a[0] == b[0] == ('Sphere', 1.0)

    def test_explicit_key_exception_falls_back_to_node_identity(self):
        g = RaisingGeom()
        key = geometry_content_key(path(Shape(g)))
        # No cached id, positions None -> content None -> id(geometry).
        assert key[0] == id(g)

    def test_cached_content_id_reused(self):
        g = Geom(content_key='__missing__')
        g._instance_content_id = 'CACHED'
        key = geometry_content_key(path(Shape(g)))
        assert key[0] == 'CACHED'

    def test_vertex_arrays_hashed_and_cached(self):
        pts = np.arange(9, dtype='f').reshape(3, 3)
        g = Geom(content_key='__missing__', positions=pts)
        key1 = geometry_content_key(path(Shape(g)))
        # A second identical-content node hashes to the same signature.
        g2 = Geom(content_key='__missing__', positions=pts.copy())
        key2 = geometry_content_key(path(Shape(g2)))
        assert key1[0] == key2[0]
        assert getattr(g, '_instance_content_id', None) == key1[0]

    def test_hash_cache_setattr_failure_is_tolerated(self):
        pts = np.arange(9, dtype='f').reshape(3, 3)
        g = SlottedGeom(pts)      # __slots__ -> cannot stash _instance_content_id
        key = geometry_content_key(path(Shape(g)))
        assert isinstance(key[0], str) and len(key[0]) == 32

    def test_no_positions_uses_node_identity(self):
        g = Geom(content_key='__missing__')     # no positions, no cache
        key = geometry_content_key(path(Shape(g)))
        assert key[0] == id(g)


class TestAppearanceTextureFallback:
    def test_appearance_texture_used_when_material_untextured(self):
        tex = object()
        g = Geom(content_key=('g',))
        key = geometry_content_key(path(Shape(g, material=None, texture=tex)))
        assert key[1] == (('appearance_texture', id(tex)),)


class TestContentInstanceKey:
    def test_splits_on_material_identity(self):
        g = Geom(content_key=('g',))
        m1, m2 = object(), object()
        a = geometry_content_instance_key(path(Shape(g, material=m1)))
        b = geometry_content_instance_key(path(Shape(g, material=m2)))
        assert a != b
        assert a[0] == b[0]     # same content

    def test_content_none_falls_back_to_node_identity(self):
        g = Geom(content_key='__missing__')     # no content signature
        key = geometry_content_instance_key(path(Shape(g)))
        assert key[0] == id(g)


class TestInstanceGroupValue:
    def test_len_and_repr(self):
        geo = Geom(content_key=('g',))
        grp = InstanceGroup(key='k', geometry=geo, appearance=None,
                            members=[1, 2, 3])
        assert len(grp) == 3
        assert 'InstanceGroup(3 instances' in repr(grp)


class TestGLCapabilitiesRepr:
    def test_repr_reports_fields(self):
        caps = GLCapabilities(version=(4, 3), max_uniform_block_size=65536,
                              ssbo=True, multi_draw_indirect=True,
                              bindless_texture=False)
        text = repr(caps)
        assert 'version=(4, 3)' in text
        assert 'ubo=65536' in text
        assert 'ssbo=True' in text


class TestDrawInstancedMeshEmpty:
    def test_empty_instance_set_draws_nothing(self):
        # Zero instances returns 0 before touching the gpu or issuing any GL call,
        # so it is safe to call with no mesh and no context.
        from OpenGLContext.passes.instancing import draw_instanced_mesh
        assert draw_instanced_mesh(gpu=None, modelviews=[], object_ids=[]) == 0
