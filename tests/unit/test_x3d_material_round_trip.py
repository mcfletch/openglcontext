"""A glTF material written as X3D and read back.

X3D's PhysicalMaterial has the core channels; the glTF extension factors and
textures and the engine's own fields travel in a `MetadataSet` named
'OpenGLContext', and a decoded image is written as an `ImageTexture` with a
`data:` URL. Read with the engine's material classes, the material is the
one that was written.
"""
import base64
import io

import numpy as np
import pytest
from PIL import Image
from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d
from vrml.x3d.scene import X3DScene

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.writer import EncodedImage, write_glb
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial, appearance_alpha
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.texturemapping import transform_for, transform_matrix
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial

ENCODINGS = ('xml', 'classic', 'json')
PROTOTYPES = {'PhysicalMaterial': PhysicalMaterial, 'UnlitMaterial': UnlitMaterial}
QUAD = dict(
    positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
    texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
    indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
)


def image(colour, mode='RGB'):
    return Image.new(mode, (2, 2), colour)


def written_and_read(appearance, encoding):
    """The appearance, on a Box, written in `encoding` and read back"""
    scene = X3DScene(children=[x3d.Shape(appearance=appearance, geometry=x3d.Box())])
    text = vrml_x3d.dumps(scene, encoding=encoding)
    read = vrml_x3d.loads(text, prototypes=PROTOTYPES)
    assert not [problem for problem in read.problems if problem.severity == 'error']
    return read.children[0].appearance


def pixels_of(texture):
    """The image an ImageTexture's data: URL holds, as RGBA bytes"""
    url = str(texture.url[0])
    assert url.startswith('data:image/')
    return Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))).convert('RGBA').tobytes()


@pytest.fixture(scope='module')
def loaded():
    """An appearance as the glTF loader builds it, from a material with a bit of everything"""
    transform = x3d.TextureTransformMatrix3D(
        mapping='TEXCOORD_0', matrix=np.array([[2, 0, 0, 0.25], [0, 2, 0, 0], [0, 0, 1, 0],
                                               [0, 0, 0, 1]], 'f'))
    material = PhysicalMaterial(
        baseColor=(0.8, 0.4, 0.2), metallic=0.25, roughness=0.5,
        clearcoat=0.75, clearcoatRoughness=0.125, sheenColor=(0.5, 0.25, 0.0),
        ior=1.4, transmission=0.5,
        baseTexture=ImageDataTexture(image=image((255, 0, 0, 128), 'RGBA')),
        baseTextureMapping='TEXCOORD_0',
        clearcoatTexture=ImageDataTexture(image=image((0, 255, 0))),
    )
    look = Appearance(material=material, alphaMode='MASK', alphaCutoff=0.25,
                      textureTransform=x3d.MultiTextureTransform(textureTransform=[transform]))
    scene = gltf.load_gltf(write_glb(PBRMesh(appearance=look, **QUAD)))
    stack = [scene.group]
    while stack:
        current = stack.pop()
        if isinstance(current, Shape):
            return current.appearance
        stack.extend(getattr(current, 'children', None) or ())
    raise AssertionError('no shape')


@pytest.mark.parametrize('encoding', ENCODINGS)
class TestAGLTFMaterial:
    def test_the_factors_come_back(self, loaded, encoding):
        material = written_and_read(loaded, encoding).material
        assert isinstance(material, PhysicalMaterial)
        for name in ('baseColor', 'metallic', 'roughness', 'clearcoat', 'clearcoatRoughness',
                     'sheenColor', 'ior', 'transmission'):
            assert np.allclose(getattr(material, name), getattr(loaded.material, name),
                               atol=1e-6), name

    def test_the_textures_come_back_as_their_images(self, loaded, encoding):
        material = written_and_read(loaded, encoding).material
        for channel in ('baseColor', 'clearcoat'):
            written = loaded.material.texture(channel).image.convert('RGBA').tobytes()
            assert pixels_of(material.texture(channel)) == written, channel

    def test_the_mapping_labels_and_transform_come_back(self, loaded, encoding):
        read = written_and_read(loaded, encoding)
        label = read.material.baseTextureMapping
        assert label == loaded.material.baseTextureMapping
        assert np.allclose(transform_matrix(transform_for(read, label)),
                           transform_matrix(transform_for(loaded, label)), atol=1e-6)

    def test_the_alpha_comes_back(self, loaded, encoding):
        assert appearance_alpha(written_and_read(loaded, encoding)) == appearance_alpha(loaded)


def test_an_unlit_material_comes_back():
    look = Appearance(material=UnlitMaterial(emissiveColor=(0.2, 0.4, 0.6), octahedralViews=4))
    for encoding in ENCODINGS:
        material = written_and_read(look, encoding).material
        assert isinstance(material, UnlitMaterial)
        assert material.octahedralViews == 4
        assert np.allclose(material.emissiveColor, (0.2, 0.4, 0.6))


def test_an_encoded_image_keeps_its_encoding():
    raw = io.BytesIO()
    image((10, 20, 30)).save(raw, 'JPEG')
    look = Appearance(material=PhysicalMaterial(
        baseTexture=EncodedImage(raw.getvalue(), mime_type='image/jpeg')))
    url = str(written_and_read(look, 'xml').material.baseTexture.url[0])
    assert url == 'data:image/jpeg;base64,' + base64.b64encode(raw.getvalue()).decode('ascii')


def test_a_shared_image_is_written_once():
    shared = ImageDataTexture(image=image((1, 2, 3)))
    look = Appearance(material=PhysicalMaterial(baseTexture=shared, emissiveTexture=shared))
    scene = X3DScene(children=[x3d.Shape(appearance=look, geometry=x3d.Box())])
    assert vrml_x3d.dumps(scene).count('data:image/png') == 1
