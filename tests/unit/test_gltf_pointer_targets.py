"""KHR_animation_pointer targets from the glTF Object Model, driven by a Player.

Each document is built in the test: a node with a mesh and a material, a node
with a spot light, a node with a camera, and one animation of one pointer
channel. Two keys, 0 at t=0 and the value at t=1; the player is evaluated at
t=1 and the property read back.
"""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.writer import _pack_glb

TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)


def _document(pointer, start, end, visible=None, morph=False, extra_extensions=None,
              camera=None, images=None, scene_extensions=None):
    """The document, with a pointer channel from ``start`` to ``end`` over 1 s."""
    start = np.atleast_1d(np.asarray(start, np.float32))
    end = np.atleast_1d(np.asarray(end, np.float32))
    times = np.array([0.0, 1.0], np.float32)
    keys = np.concatenate([start, end]).astype(np.float32)
    blob = bytearray(TRIANGLE.tobytes() + times.tobytes() + keys.tobytes())
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
             {'buffer': 0, 'byteOffset': 36, 'byteLength': 8},
             {'buffer': 0, 'byteOffset': 44, 'byteLength': keys.nbytes}]
    kind = {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4'}.get(len(start), 'SCALAR')
    count = 2 if kind != 'SCALAR' or len(start) == 1 else 2 * len(start)
    accessors = [
        {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
         'min': [0, 0, 0], 'max': [1, 1, 0]},
        {'bufferView': 1, 'componentType': 5126, 'type': 'SCALAR', 'count': 2,
         'min': [0], 'max': [1]},
        {'bufferView': 2, 'componentType': 5126, 'type': kind, 'count': count}]
    primitive = {'attributes': {'POSITION': 0}, 'material': 0}
    mesh = {'primitives': [primitive]}
    if morph:
        primitive['targets'] = [{'POSITION': 0}, {'POSITION': 0}]
        mesh['weights'] = [0.0, 0.0]
    node = {'mesh': 0}
    if visible is not None:
        node['extensions'] = {'KHR_node_visibility': {'visible': visible}}
    extensions = {'KHR_lights_punctual': {'lights': [
        {'type': 'spot', 'color': [1, 1, 1], 'intensity': 5.0, 'range': 10.0,
         'spot': {'innerConeAngle': 0.1, 'outerConeAngle': 0.5}}]}}
    extensions.update(extra_extensions or {})
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_animation_pointer', 'KHR_lights_punctual',
                           'KHR_node_visibility'],
        'extensions': extensions,
        'scene': 0, 'scenes': [{'nodes': [0, 1, 2]}],
        'nodes': [node,
                  {'extensions': {'KHR_lights_punctual': {'light': 0}},
                   'translation': [0, 2, 0]},
                  {'camera': 0, 'translation': [0, 0, 5]}],
        'cameras': [camera or {'type': 'perspective',
                               'perspective': {'yfov': 0.8, 'znear': 0.1, 'zfar': 100.0}}],
        'meshes': [mesh],
        'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1]},
                       'alphaMode': 'BLEND',
                       'extensions': {'KHR_materials_ior': {'ior': 1.5}}}],
        'accessors': accessors, 'bufferViews': views,
        'buffers': [{'byteLength': len(blob)}],
        'animations': [{'samplers': [{'input': 1, 'output': 2}],
                        'channels': [{'sampler': 0, 'target': {
                            'path': 'pointer', 'extensions': {
                                'KHR_animation_pointer': {'pointer': pointer}}}}]}],
    }
    if images:
        doc['images'] = images
    if scene_extensions:
        doc['scenes'][0]['extensions'] = scene_extensions
    return _pack_glb(doc, bytes(blob))


def _played(pointer, start, end, t=1.0, **named):
    scene = load_gltf(_document(pointer, start, end, **named))
    player = scene.player(0, loop=False)
    assert player is not None and player.animation.pointer_channels, pointer
    player.evaluate(t)
    return scene


def _shape(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no shape')


def _light(scene):
    from OpenGLContext.scenegraph.basenodes import SpotLight
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if isinstance(node, SpotLight):
            return node
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no light')


class TestNodes:
    @pytest.mark.parametrize('path, end, field, expected', [
        ('translation', [1, 2, 3], 'translation', [1, 2, 3]),
        ('scale', [2, 3, 4], 'scale', [2, 3, 4]),
    ])
    def test_translation_and_scale(self, path, end, field, expected):
        scene = _played('/nodes/0/%s' % path, [1, 1, 1] if path == 'scale' else [0, 0, 0],
                        end)
        assert np.allclose(getattr(scene.node_transforms[0], field), expected)

    def test_rotation(self):
        half = np.sqrt(0.5)
        scene = _played('/nodes/0/rotation', [0, 0, 0, 1], [0, half, 0, half])
        axis_angle = scene.node_transforms[0].rotation
        assert np.allclose(axis_angle[:3], [0, 1, 0]) and np.isclose(axis_angle[3], np.pi / 2)

    def test_all_weights(self):
        scene = _played('/nodes/0/weights', [0, 0], [0.25, 0.75], morph=True)
        mesh = _shape(scene).geometry
        assert np.allclose(mesh.morph_weights, [0.25, 0.75])

    def test_one_weight(self):
        scene = _played('/nodes/0/weights/1', [0], [0.5], morph=True)
        assert np.allclose(_shape(scene).geometry.morph_weights, [0.0, 0.5])

    def test_visibility(self):
        scene = _played('/nodes/0/extensions/KHR_node_visibility/visible', [1], [0])
        assert scene.node_transforms[0].visible is False or not scene.node_transforms[0].visible

    def test_a_node_hidden_at_load_can_be_shown(self):
        scene = _played('/nodes/0/extensions/KHR_node_visibility/visible', [0], [1],
                        visible=False)
        assert scene.node_transforms[0].visible
        assert _shape(scene) is not None


class TestStaticVisibility:
    def test_a_hidden_node_is_built_and_hidden(self):
        scene = load_gltf(_document('/nodes/0/translation', [0, 0, 0], [0, 0, 0],
                                    visible=False))
        assert not scene.node_transforms[0].visible
        assert _shape(scene) is not None


class TestMaterials:
    @pytest.mark.parametrize('pointer, end, read', [
        ('alphaCutoff', 0.25, lambda s: s.appearance.alphaCutoff),
        ('normalTexture/scale', 0.5, lambda s: s.appearance.material.normalScale),
        ('occlusionTexture/strength', 0.5, lambda s: s.appearance.material.occlusionStrength),
        ('pbrMetallicRoughness/metallicFactor', 0.5, lambda s: s.appearance.material.metallic),
        ('extensions/KHR_materials_ior/ior', 1.25, lambda s: s.appearance.material.ior),
        ('extensions/KHR_materials_clearcoat/clearcoatFactor', 0.5,
         lambda s: s.appearance.material.clearcoat),
        ('extensions/KHR_materials_clearcoat/clearcoatNormalTexture/scale', 0.5,
         lambda s: s.appearance.material.clearcoatNormalScale),
        ('extensions/KHR_materials_transmission/transmissionFactor', 0.5,
         lambda s: s.appearance.material.transmission),
        ('extensions/KHR_materials_iridescence/iridescenceThicknessMaximum', 300.0,
         lambda s: s.appearance.material.iridescenceThicknessMax),
        ('extensions/KHR_materials_anisotropy/anisotropyRotation', 0.5,
         lambda s: s.appearance.material.anisotropyRotation),
        ('extensions/KHR_materials_dispersion/dispersion', 0.5,
         lambda s: s.appearance.material.dispersion),
        ('extensions/KHR_materials_retroreflection/retroreflectionFactor', 0.5,
         lambda s: s.appearance.material.retroreflection),
        ('extensions/KHR_materials_scatter/scatterAnisotropy', 0.5,
         lambda s: s.appearance.material.scatterAnisotropy),
        ('extensions/KHR_materials_volume/attenuationDistance', 2.0,
         lambda s: s.appearance.material.attenuationDistance),
    ])
    def test_scalar_properties(self, pointer, end, read):
        scene = _played('/materials/0/%s' % pointer, [end * 0.5], [end])
        assert np.isclose(read(_shape(scene)), end)

    @pytest.mark.parametrize('pointer, end, field', [
        ('extensions/KHR_materials_sheen/sheenColorFactor', [0.5, 0.25, 0.125], 'sheenColor'),
        ('extensions/KHR_materials_specular/specularColorFactor', [0.5, 0.5, 0.25],
         'specularColor'),
        ('extensions/KHR_materials_scatter/multiscatterColorFactor', [0.5, 0.25, 0.125],
         'multiscatterColor'),
        ('extensions/KHR_materials_volume/attenuationColor', [0.5, 0.75, 1.0],
         'attenuationColor'),
        ('emissiveFactor', [1, 0.5, 0], 'emissiveColor'),
    ])
    def test_colours(self, pointer, end, field):
        scene = _played('/materials/0/%s' % pointer, [0, 0, 0], end)
        assert np.allclose(getattr(_shape(scene).appearance.material, field), end)

    def test_base_colour_alpha(self):
        scene = _played('/materials/0/pbrMetallicRoughness/baseColorFactor',
                        [1, 1, 1, 1], [0.5, 0.5, 0.5, 0.25])
        material = _shape(scene).appearance.material
        assert np.allclose(material.baseColor, [0.5, 0.5, 0.5])
        assert np.isclose(material.transparency, 0.75)


class TestLights:
    @pytest.mark.parametrize('pointer, end, field', [
        ('intensity', 2.0, 'intensity'),
        ('spot/innerConeAngle', 0.2, 'beamWidth'),
        ('spot/outerConeAngle', 0.4, 'cutOffAngle'),
        ('range', 4.0, 'radius'),
    ])
    def test_scalars(self, pointer, end, field):
        scene = _played('/extensions/KHR_lights_punctual/lights/0/%s' % pointer,
                        [end], [end])
        assert np.isclose(getattr(_light(scene), field), end)

    def test_colour(self):
        scene = _played('/extensions/KHR_lights_punctual/lights/0/color',
                        [1, 1, 1], [1, 0.5, 0.25])
        assert np.allclose(_light(scene).color, [1, 0.5, 0.25])


class TestCameras:
    def test_field_of_view(self):
        scene = _played('/cameras/0/perspective/yfov', [0.8], [0.6])
        assert np.isclose(scene.viewpoints[0].fieldOfView, 0.6)

    @pytest.mark.parametrize('name', ['znear', 'zfar'])
    def test_clipping_distances(self, name):
        scene = _played('/cameras/0/perspective/%s' % name, [2.0], [3.0])
        attribute = {'znear': 'near', 'zfar': 'far'}[name]
        assert np.isclose(getattr(scene.viewpoints[0], attribute), 3.0)


ORTHOGRAPHIC = {'type': 'orthographic',
                'orthographic': {'xmag': 2.0, 'ymag': 1.0, 'znear': 0.5, 'zfar': 50.0}}


class TestOrthographicCameras:
    def test_an_orthographic_camera_is_an_ortho_viewpoint(self):
        from OpenGLContext.scenegraph.viewpoint import OrthoViewpoint
        scene = load_gltf(_document('/cameras/0/orthographic/xmag', [2.0], [2.0],
                                    camera=ORTHOGRAPHIC))
        viewpoint = scene.viewpoints[0]
        assert isinstance(viewpoint, OrthoViewpoint)
        assert np.allclose(viewpoint.fieldOfView, [-2, -1, 2, 1])
        assert np.isclose(viewpoint.nearDistance, 0.5)
        assert np.isclose(viewpoint.farDistance, 50.0)

    @pytest.mark.parametrize('name, window', [
        ('xmag', [-3, -1, 3, 1]), ('ymag', [-2, -3, 2, 3])])
    def test_magnification(self, name, window):
        scene = _played('/cameras/0/orthographic/%s' % name, [1.0], [3.0],
                        camera=ORTHOGRAPHIC)
        assert np.allclose(scene.viewpoints[0].fieldOfView, window)

    @pytest.mark.parametrize('name, field', [('znear', 'nearDistance'), ('zfar', 'farDistance')])
    def test_clipping_distances(self, name, field):
        scene = _played('/cameras/0/orthographic/%s' % name, [2.0], [3.0],
                        camera=ORTHOGRAPHIC)
        assert np.isclose(getattr(scene.viewpoints[0], field), 3.0)


def test_the_aspect_ratio_travels_with_the_viewpoint():
    scene = _played('/cameras/0/perspective/aspectRatio', [1.0], [1.5])
    assert np.isclose(scene.viewpoints[0].aspectRatio, 1.5)


def _image_light_extension():
    """An EXT_lights_image_based light of one 1x1 white mip, the scene lit by it."""
    import base64
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (1, 1), (255, 255, 255)).save(out, format='PNG')
    uri = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
    return uri, {'EXT_lights_image_based': {'lights': [{
        'intensity': 1.0, 'rotation': [0, 0, 0, 1],
        'irradianceCoefficients': [[0.5, 0.5, 0.5]] + [[0, 0, 0]] * 8,
        'specularImageSize': 1, 'specularImages': [[0, 0, 0, 0, 0, 0]]}]}}


class TestImageBasedLights:
    def _scene(self, pointer, start, end, t=1.0):
        uri, extensions = _image_light_extension()
        glb = _document(pointer, start, end, extra_extensions=extensions,
                        images=[{'uri': uri}],
                        scene_extensions={'EXT_lights_image_based': {'light': 0}})
        scene = load_gltf(glb)
        player = scene.player(0, loop=False)
        assert player is not None and player.animation.pointer_channels, pointer
        player.evaluate(t)
        return scene

    def test_intensity(self):
        scene = self._scene('/extensions/EXT_lights_image_based/lights/0/intensity',
                            [1.0], [2.5])
        assert np.isclose(scene.environment.intensity, 2.5)

    def test_rotation(self):
        half = float(np.sqrt(0.5))
        scene = self._scene('/extensions/EXT_lights_image_based/lights/0/rotation',
                            [0, 0, 0, 1], [0, half, 0, half])
        assert np.allclose(scene.environment.rotation, [0, half, 0, half])

    def test_rotation_is_interpolated_as_a_quaternion(self):
        half = float(np.sqrt(0.5))
        scene = self._scene('/extensions/EXT_lights_image_based/lights/0/rotation',
                            [0, 0, 0, 1], [0, half, 0, half], t=0.25)
        angle = np.pi / 16
        assert np.allclose(scene.environment.rotation,
                           [0, np.sin(angle), 0, np.cos(angle)], atol=1e-5)


def test_an_unsupported_pointer_is_reported(caplog):
    scene = load_gltf(_document('/scenes/0/nodes/0', [0], [1]))
    assert not scene.animations or not scene.animations[0].pointer_channels
    assert '/scenes/0/nodes/0' in caplog.text
