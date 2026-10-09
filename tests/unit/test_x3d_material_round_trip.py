"""A glTF material written as X3D and read back.

X3D's PhysicalMaterial has the core channels; the glTF extension factors and
textures travel as X_ITE's material extension nodes, the engine's own fields
in a `MetadataSet` named 'OpenGLContext', and a decoded image is written as an `ImageTexture` with a
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


def top_and_bottom():
    """Red over blue: which way up an image is written shows"""
    picture = Image.new('RGB', (8, 8), (0, 0, 255))
    picture.paste((255, 0, 0), (0, 0, 8, 4))
    return picture


def written_image(texture):
    url = str(written_and_read(Appearance(material=PhysicalMaterial(baseTexture=texture)),
                               'xml').material.baseTexture.url[0])
    kind, data = url.split(';base64,', 1)
    return kind, Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')


def test_an_image_is_written_with_x3ds_origin():
    """An ImageDataTexture's (0, 0) is its upper left; an X3D ImageTexture's is its
    lower left, so the image is written upside down and the coordinates name the
    same texels"""
    _kind, written = written_image(ImageDataTexture(image=top_and_bottom()))
    assert written.getpixel((0, 0)) == (0, 0, 255)
    assert written.getpixel((0, 7)) == (255, 0, 0)


def test_an_encoded_image_keeps_its_format_and_x3ds_origin():
    raw = io.BytesIO()
    top_and_bottom().save(raw, 'JPEG', quality=95)
    kind, written = written_image(EncodedImage(raw.getvalue(), mime_type='image/jpeg'))
    assert kind == 'data:image/jpeg'
    top, bottom = written.getpixel((4, 1)), written.getpixel((4, 6))
    assert top[2] > 200 and top[0] < 60, top
    assert bottom[0] > 200 and bottom[2] < 60, bottom


def test_a_shared_image_is_written_once():
    shared = ImageDataTexture(image=image((1, 2, 3)))
    look = Appearance(material=PhysicalMaterial(baseTexture=shared, emissiveTexture=shared))
    scene = X3DScene(children=[x3d.Shape(appearance=look, geometry=x3d.Box())])
    assert vrml_x3d.dumps(scene).count('data:image/png') == 1
