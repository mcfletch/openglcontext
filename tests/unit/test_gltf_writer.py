"""The glTF 2.0 writer, asserted by round-tripping through the loader.

Every test here writes a document with :mod:`OpenGLContext.loaders.gltf.writer`
and reads it back with :func:`OpenGLContext.loaders.gltf.load_gltf`, so what is
being asserted is the pair: a mesh written is the mesh that loads, and a material
written is the material that loads. A few tests additionally parse the bytes as a
container -- header fields, chunk alignment -- because a GLB that only *our*
reader accepts is not a GLB.

No GL and no network: a document is bytes, and a loaded scene is arrays.
"""
import json
import struct

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import writer as gltf_writer
from OpenGLContext.loaders.gltf.writer import (
    GLTFWriter, InstanceSet, SceneNode, write_glb,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform


# --- fixtures -----------------------------------------------------------------

def _quad(with_all_attributes=True):
    """A two-triangle quad carrying every vertex attribute the writer emits."""
    positions = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f')
    indices = np.array([0, 1, 2, 0, 2, 3], np.uint32)
    if not with_all_attributes:
        return PBRMesh(positions=positions, indices=indices)
    return PBRMesh(
        positions=positions,
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
        texcoords1=np.array([(0, 1), (1, 1), (1, 0), (0, 0)], 'f'),
        tangents=np.array([(1, 0, 0, 1)] * 4, 'f'),
        colors=np.array([(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (1, 1, 0, 0.5)], 'f'),
        indices=indices,
        material=PBRMaterial(baseColor=(0.25, 0.5, 0.75), metallic=0.3, roughness=0.7),
    )


def _find_shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _find_shapes(child, out)
    return out


def _round_trip(nodes):
    """Write, load, and return the loaded scene."""
    return gltf.load_gltf(write_glb(nodes))


def _only_shape(nodes):
    shapes = _find_shapes(_round_trip(nodes).group)
    assert len(shapes) == 1, "expected exactly one shape, got %d" % len(shapes)
    return shapes[0]


# --- the container ------------------------------------------------------------

class TestTheGLBContainer:
    def test_it_carries_the_glb_header(self):
        data = write_glb(_quad())
        magic, version, length = struct.unpack('<4sII', data[:12])
        assert magic == b'glTF'
        assert version == 2
        assert length == len(data)

    def test_every_chunk_is_four_byte_aligned(self):
        data = write_glb(_quad())
        offset, kinds = 12, []
        while offset < len(data):
            size, kind = struct.unpack('<II', data[offset:offset + 8])
            assert size % 4 == 0, "chunk at %d is %d bytes" % (offset, size)
            kinds.append(kind)
            offset += 8 + size
        assert offset == len(data)
        assert kinds == [0x4E4F534A, 0x004E4942]        # JSON then BIN

    def test_the_json_chunk_is_padded_with_spaces(self):
        """A parser that trims nothing must still see valid JSON."""
        data = write_glb(_quad())
        size, = struct.unpack('<I', data[12:16])
        chunk = data[20:20 + size]
        assert chunk.endswith(b' ') or len(chunk) % 4 == 0
        assert json.loads(chunk.decode('utf-8'))['asset']['version'] == '2.0'

    def test_it_names_itself_as_the_generator(self):
        doc = json.loads(_json_chunk(write_glb(_quad())))
        assert 'OpenGLContext' in doc['asset']['generator']

    def test_a_path_receives_the_same_bytes_it_returns(self, tmp_path):
        target = tmp_path / 'quad.glb'
        data = write_glb(_quad(), path=str(target))
        assert target.read_bytes() == data


def _json_chunk(data):
    size, = struct.unpack('<I', data[12:16])
    return data[20:20 + size].decode('utf-8')


# --- geometry -----------------------------------------------------------------

class TestAMeshRoundTrips:
    def test_positions_survive(self):
        mesh = _only_shape(_quad()).geometry
        assert np.allclose(mesh.positions, _quad().positions)

    def test_every_vertex_attribute_survives(self):
        written = _quad()
        mesh = _only_shape(written).geometry
        for name in ('positions', 'normals', 'texcoords', 'texcoords1',
                     'tangents', 'colors'):
            got, expected = getattr(mesh, name), getattr(written, name)
            assert got is not None, "%s was dropped" % name
            assert np.allclose(got, expected, atol=1e-6), name

    def test_indices_survive(self):
        mesh = _only_shape(_quad()).geometry
        assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]

    def test_a_bare_mesh_needs_only_positions(self):
        mesh = _only_shape(_quad(with_all_attributes=False)).geometry
        assert np.allclose(mesh.positions, _quad().positions)

    def test_a_non_indexed_mesh_stays_non_indexed(self):
        written = PBRMesh(positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f'))
        assert _only_shape(written).geometry.indices is None

    def test_three_component_colours_survive(self):
        """COLOR_0 may be VEC3; the loader pads it to RGBA with alpha 1."""
        written = PBRMesh(
            positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f'),
            colors=np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1)], 'f'))
        colors = _only_shape(written).geometry.colors
        assert np.allclose(colors[:, :3], written.colors, atol=1e-6)

    def test_small_meshes_use_short_indices(self):
        """A tile of a few thousand vertices should not pay 32-bit indices."""
        doc = json.loads(_json_chunk(write_glb(_quad())))
        index_accessor = doc['accessors'][doc['meshes'][0]['primitives'][0]['indices']]
        assert index_accessor['componentType'] == 5123        # UNSIGNED_SHORT

    def test_large_meshes_use_int_indices(self):
        n = 70000
        written = PBRMesh(
            positions=np.zeros((n, 3), 'f'),
            indices=np.array([0, 1, n - 1], np.uint32))
        doc = json.loads(_json_chunk(write_glb(written)))
        index_accessor = doc['accessors'][doc['meshes'][0]['primitives'][0]['indices']]
        assert index_accessor['componentType'] == 5125        # UNSIGNED_INT

    def test_the_position_accessor_states_its_bounds(self):
        """min/max on POSITION is required by the spec, and the tiles3d
        uploader reads it to place a tile without decoding the vertices."""
        doc = json.loads(_json_chunk(write_glb(_quad())))
        position = doc['accessors'][
            doc['meshes'][0]['primitives'][0]['attributes']['POSITION']]
        assert position['min'] == [0.0, 0.0, 0.0]
        assert position['max'] == [1.0, 1.0, 0.0]

    def test_a_point_cloud_keeps_its_draw_mode(self):
        written = PBRMesh(positions=np.zeros((4, 3), 'f'), draw_mode=0)   # GL_POINTS
        assert int(_only_shape(written).geometry.draw_mode) == 0

    def test_mismatched_attribute_lengths_are_refused(self):
        written = PBRMesh(positions=np.zeros((4, 3), 'f'), normals=np.zeros((3, 3), 'f'))
        with pytest.raises(ValueError, match='NORMAL'):
            write_glb(written)

    def test_an_out_of_range_index_is_refused(self):
        written = PBRMesh(positions=np.zeros((3, 3), 'f'),
                          indices=np.array([0, 1, 7], np.uint32))
        with pytest.raises(ValueError, match='out of range'):
            write_glb(written)

    def test_a_mesh_with_no_positions_is_refused(self):
        with pytest.raises(ValueError, match='POSITION'):
            write_glb(PBRMesh(positions=np.zeros((0, 3), 'f')))


# --- materials ----------------------------------------------------------------

class TestAMaterialRoundTrips:
    def _written(self, **kwargs):
        base = dict(baseColor=(0.2, 0.4, 0.6), metallic=0.25, roughness=0.75)
        base.update(kwargs)
        material = PBRMaterial(**base)
        mesh = _quad()
        mesh.material = material
        return material, _only_shape(mesh).appearance.material

    def test_metallic_roughness_factors_survive(self):
        _, got = self._written()
        assert np.allclose(got.baseColor, (0.2, 0.4, 0.6), atol=1e-6)
        assert round(float(got.metallic), 4) == 0.25
        assert round(float(got.roughness), 4) == 0.75

    def test_emission_survives(self):
        _, got = self._written(emissiveColor=(0.9, 0.1, 0.0))
        assert np.allclose(got.emissiveColor, (0.9, 0.1, 0.0), atol=1e-6)

    def test_blend_transparency_survives(self):
        _, got = self._written(alphaMode='BLEND', transparency=0.25)
        assert got.alphaMode == 'BLEND'
        assert round(float(got.transparency), 4) == 0.25

    def test_masked_cutoff_survives(self):
        _, got = self._written(alphaMode='MASK', alphaCutoff=0.25)
        assert got.alphaMode == 'MASK'
        assert round(float(got.alphaCutoff), 4) == 0.25

    def test_double_sidedness_survives(self):
        _, got = self._written(doubleSided=True)
        assert bool(got.doubleSided) is True

    def test_an_opaque_material_writes_no_alpha_mode(self):
        """OPAQUE is the glTF default; writing it is noise in every tile."""
        doc = json.loads(_json_chunk(write_glb(_quad())))
        assert 'alphaMode' not in doc['materials'][0]

    @pytest.mark.parametrize('field,value,extension', [
        ('emissiveStrength', 3.0, 'KHR_materials_emissive_strength'),
        ('ior', 1.7, 'KHR_materials_ior'),
        ('transmission', 0.8, 'KHR_materials_transmission'),
        ('clearcoat', 0.6, 'KHR_materials_clearcoat'),
        ('sheenRoughness', 0.4, 'KHR_materials_sheen'),
        ('specular', 0.3, 'KHR_materials_specular'),
        ('thickness', 2.0, 'KHR_materials_volume'),
        ('anisotropyStrength', 0.5, 'KHR_materials_anisotropy'),
        ('dispersion', 0.2, 'KHR_materials_dispersion'),
        ('iridescence', 0.7, 'KHR_materials_iridescence'),
        ('unlit', True, 'KHR_materials_unlit'),
    ])
    def test_khr_extension_factors_survive(self, field, value, extension):
        material, got = self._written(**{field: value})
        assert type(value)(getattr(got, field)) == pytest.approx(value) \
            if not isinstance(value, bool) else bool(getattr(got, field)) is value
        doc = json.loads(_json_chunk(write_glb(_quad_with(material))))
        assert extension in doc['extensionsUsed']
        assert extension in doc['materials'][0]['extensions']

    def test_a_default_material_declares_no_extensions(self):
        doc = json.loads(_json_chunk(write_glb(_quad())))
        assert 'extensionsUsed' not in doc
        assert 'extensions' not in doc['materials'][0]

    def test_meshes_sharing_a_material_share_its_index(self):
        material = PBRMaterial(baseColor=(1, 0, 0))
        a, b = _quad(), _quad()
        a.material = b.material = material
        doc = json.loads(_json_chunk(write_glb([a, b])))
        assert len(doc['materials']) == 1


def _quad_with(material):
    mesh = _quad()
    mesh.material = material
    return mesh


# --- textures -----------------------------------------------------------------

def _image(color=(255, 0, 0, 255), size=(4, 4)):
    Image = pytest.importorskip('PIL.Image')
    return Image.new('RGBA', size, color)


class TestTexturesRoundTrip:
    def test_a_base_colour_map_survives(self):
        material = PBRMaterial(baseColor=(1, 1, 1))
        material.textures = {'baseColor': PBRTexture(_image((10, 200, 30, 255)), srgb=True)}
        got = _only_shape(_quad_with(material)).appearance.material
        assert 'baseColor' in got.textures
        assert got.textures['baseColor'].image.size == (4, 4)
        assert got.textures['baseColor'].image.getpixel((0, 0)) == (10, 200, 30, 255)

    def test_every_core_channel_survives(self):
        material = PBRMaterial(baseColor=(1, 1, 1))
        material.textures = {
            channel: PBRTexture(_image(), srgb=channel in ('baseColor', 'emissive'))
            for channel in ('baseColor', 'metallicRoughness', 'normal',
                            'occlusion', 'emissive')}
        got = _only_shape(_quad_with(material)).appearance.material
        assert set(got.textures) == set(material.textures)

    def test_normal_scale_and_occlusion_strength_survive(self):
        material = PBRMaterial(normalScale=0.5, occlusionStrength=0.25)
        material.textures = {'normal': PBRTexture(_image()),
                             'occlusion': PBRTexture(_image())}
        got = _only_shape(_quad_with(material)).appearance.material
        assert round(float(got.normalScale), 4) == 0.5
        assert round(float(got.occlusionStrength), 4) == 0.25

    def test_the_second_uv_set_selection_survives(self):
        material = PBRMaterial(texCoordMask=1)      # baseColor samples TEXCOORD_1
        material.textures = {'baseColor': PBRTexture(_image(), srgb=True)}
        got = _only_shape(_quad_with(material)).appearance.material
        assert int(got.texCoordMask) & 1

    def test_sampler_wrap_modes_survive(self):
        material = PBRMaterial()
        material.textures = {'baseColor': PBRTexture(
            _image(), srgb=True, wrap_s=33071, wrap_t=33648)}   # CLAMP, MIRROR
        got = _only_shape(_quad_with(material)).appearance.material
        holder = got.textures['baseColor']
        assert int(holder.wrap_s) == 33071 and int(holder.wrap_t) == 33648

    def test_an_already_encoded_image_is_embedded_as_it_is(self, tmp_path):
        """A source JPEG stays a JPEG rather than being inflated to PNG."""
        source = tmp_path / 'bark.jpg'
        _image((120, 90, 60, 255), size=(8, 8)).convert('RGB').save(str(source))
        encoded = gltf_writer.EncodedImage.from_path(str(source), srgb=True)
        material = PBRMaterial()
        material.textures = {'baseColor': encoded}
        doc = json.loads(_json_chunk(write_glb(_quad_with(material))))
        assert doc['images'][0]['mimeType'] == 'image/jpeg'
        got = _only_shape(_quad_with(material)).appearance.material
        assert got.textures['baseColor'].image.size == (8, 8)

    def test_one_image_is_written_once_however_many_channels_use_it(self):
        shared = PBRTexture(_image(), srgb=False)
        material = PBRMaterial()
        material.textures = {'metallicRoughness': shared, 'occlusion': shared}
        doc = json.loads(_json_chunk(write_glb(_quad_with(material))))
        assert len(doc['images']) == 1


# --- nodes, hierarchy and instancing ------------------------------------------

class TestTheNodeGraph:
    def test_a_node_transform_places_its_mesh(self):
        node = SceneNode(mesh=_quad(), translation=(5, 0, -3), scale=(2, 2, 2))
        scene = _round_trip(node)
        shapes = _find_shapes(scene.group)
        assert len(shapes) == 1
        # The loader bakes node transforms into Transform nodes above the shape.
        transforms = _transforms_above(scene.group, shapes[0])
        translations = [tuple(float(v) for v in t.translation) for t in transforms]
        assert (5.0, 0.0, -3.0) in translations

    def test_children_nest(self):
        child = SceneNode(mesh=_quad(), name='child')
        parent = SceneNode(name='parent', translation=(1, 2, 3), children=[child])
        doc = json.loads(_json_chunk(write_glb(parent)))
        names = [n.get('name') for n in doc['nodes']]
        assert 'parent' in names and 'child' in names
        parent_node = doc['nodes'][names.index('parent')]
        assert parent_node['children'] == [names.index('child')]

    def test_meshes_shared_between_nodes_are_written_once(self):
        mesh = _quad()
        doc = json.loads(_json_chunk(write_glb([
            SceneNode(mesh=mesh, translation=(0, 0, 0)),
            SceneNode(mesh=mesh, translation=(4, 0, 0)),
        ])))
        assert len(doc['meshes']) == 1
        assert len(doc['nodes']) == 2

    def test_gpu_instances_come_back_as_one_placement_set(self):
        translations = np.array([(-2, 0, 0), (0, 0, 0), (2, 0, 0)], 'f')
        node = SceneNode(mesh=_quad(), instances=InstanceSet(translations=translations))
        placed = _placement_sets(_round_trip(node))
        assert len(placed) == 1
        got = sorted(tuple(round(float(v), 3) for v in matrix[3, :3])
                     for matrix in placed[0].instancePlacements())
        assert got == [(-2.0, 0.0, 0.0), (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)]

    def test_gpu_instances_carry_rotation_and_scale(self):
        node = SceneNode(mesh=_quad(), instances=InstanceSet(
            translations=np.zeros((2, 3), 'f'),
            rotations=np.array([(0, 0, 0, 1), (0, 0.7071068, 0, 0.7071068)], 'f'),
            scales=np.array([(1, 1, 1), (2, 3, 4)], 'f')))
        placements = _placement_sets(_round_trip(node))[0].instancePlacements()
        # +X through the first placement is a unit step along +X; through the
        # second it is three times as long (the y scale) and turned onto -Z.
        first = np.array([1.0, 0, 0, 1.0]) @ placements[0]
        second = np.array([1.0, 0, 0, 1.0]) @ placements[1]
        assert np.allclose(first[:3], (1, 0, 0), atol=1e-4)
        assert np.allclose(second[:3], (0, 0, -2), atol=1e-4)

    def test_instancing_declares_its_extension(self):
        node = SceneNode(mesh=_quad(),
                         instances=InstanceSet(translations=np.zeros((2, 3), 'f')))
        doc = json.loads(_json_chunk(write_glb(node)))
        assert 'EXT_mesh_gpu_instancing' in doc['extensionsUsed']

    def test_instance_arrays_of_different_lengths_are_refused(self):
        node = SceneNode(mesh=_quad(), instances=InstanceSet(
            translations=np.zeros((3, 3), 'f'), scales=np.zeros((2, 3), 'f')))
        with pytest.raises(ValueError, match='instance'):
            write_glb(node)


def _placement_sets(scene):
    """The InstancedShape nodes a loaded scene holds."""
    from OpenGLContext.scenegraph.instancedshape import InstancedShape
    return [n for n in _flatten(scene.group) if isinstance(n, InstancedShape)]


def _flatten(node, out=None):
    out = [] if out is None else out
    out.append(node)
    for child in getattr(node, 'children', None) or []:
        _flatten(child, out)
    return out


def _transforms_above(root, target, chain=()):
    if root is target:
        return [n for n in chain if isinstance(n, Transform)]
    for child in getattr(root, 'children', None) or []:
        found = _transforms_above(child, target, chain + (root,))
        if found is not None:
            return found
    return None


# --- an independent parser ----------------------------------------------------

class TestAnotherParserAgrees:
    """Our own reader accepting the output proves too little on its own."""

    def test_pygltflib_reads_what_we_write(self):
        pygltflib = pytest.importorskip('pygltflib')
        g = pygltflib.GLTF2.load_from_bytes(write_glb(_quad()))
        assert g.asset.version == '2.0'
        assert len(g.meshes) == 1
        primitive = g.meshes[0].primitives[0]
        assert primitive.attributes.POSITION is not None
        assert g.accessors[primitive.attributes.POSITION].count == 4
        blob = g.binary_blob()
        assert len(blob) == g.buffers[0].byteLength


# --- the writer object --------------------------------------------------------

class TestTheWriterObject:
    def test_it_reports_the_indices_it_assigns(self):
        w = GLTFWriter()
        first = w.add_mesh(_quad())
        second = w.add_mesh(_quad(with_all_attributes=False))
        assert (first, second) == (0, 1)

    def test_an_empty_document_is_still_a_valid_glb(self):
        doc = json.loads(_json_chunk(GLTFWriter().to_glb()))
        assert doc['asset']['version'] == '2.0'
        assert doc.get('scenes') == [{'nodes': []}]

    def test_the_generator_string_is_the_engine_and_its_version(self):
        from OpenGLContext import __version__
        assert __version__ in gltf_writer.GENERATOR


class TestSharedTextures:
    """A texture used by many documents is named, not copied into each."""

    def test_an_external_image_is_written_as_a_uri(self):
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage(
            'road-surface.png', srgb=True)}
        doc = json.loads(_json_chunk(write_glb(_quad_with(material))))
        assert doc['images'] == [{'uri': 'road-surface.png'}]
        assert 'bufferView' not in doc['images'][0]

    def test_it_costs_the_document_nothing(self):
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage('t.png')}
        plain = len(write_glb(_quad()))
        assert len(write_glb(_quad_with(material))) < plain + 512

    def test_the_loader_reads_it_back_from_beside_the_document(self, tmp_path):
        _image((12, 34, 56, 255), size=(4, 4)).save(str(tmp_path / 'surface.png'))
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage(
            'surface.png', srgb=True)}
        write_glb(_quad_with(material), path=str(tmp_path / 'tile.glb'))
        loaded = gltf.load_gltf(str(tmp_path / 'tile.glb'))
        shape = _find_shapes(loaded.group)[0]
        assert shape.appearance.material.textures['baseColor'].image.getpixel(
            (0, 0)) == (12, 34, 56, 255)

    def test_one_external_image_is_named_once_however_many_channels_use_it(self):
        shared = gltf_writer.ExternalImage('maps.png')
        material = PBRMaterial()
        material.textures = {'metallicRoughness': shared, 'occlusion': shared}
        doc = json.loads(_json_chunk(write_glb(_quad_with(material))))
        assert len(doc['images']) == 1

    def test_its_sampler_survives(self, tmp_path):
        _image().save(str(tmp_path / 's.png'))
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage(
            's.png', srgb=True, wrap_s=33071, wrap_t=33071)}
        write_glb(_quad_with(material), path=str(tmp_path / 'tile.glb'))
        holder = _find_shapes(gltf.load_gltf(str(tmp_path / 'tile.glb')).group)[0] \
            .appearance.material.textures['baseColor']
        assert int(holder.wrap_s) == 33071


class TestABytesDocumentCanSayWhereItCameFrom:
    """A tile is read into memory before it is parsed, and its texture is
    beside the tileset rather than inside it."""

    def test_bytes_with_a_base_directory_resolve_their_images(self, tmp_path):
        _image((200, 30, 40, 255), size=(4, 4)).save(str(tmp_path / 'shared.png'))
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage(
            'shared.png', srgb=True)}
        data = write_glb(_quad_with(material))
        scene = gltf.load_gltf(data, base_dir=str(tmp_path))
        holder = _find_shapes(scene.group)[0].appearance.material.textures['baseColor']
        assert holder.image.getpixel((0, 0)) == (200, 30, 40, 255)

    def test_without_one_the_reference_is_simply_not_found(self, tmp_path):
        """No base, no directory to look in -- the material loads untextured
        rather than reaching somewhere it was not pointed."""
        material = PBRMaterial()
        material.textures = {'baseColor': gltf_writer.ExternalImage('shared.png')}
        scene = gltf.load_gltf(write_glb(_quad_with(material)))
        assert 'baseColor' not in _find_shapes(scene.group)[0].appearance.material.textures
