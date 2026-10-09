"""X3D's DIS EspduTransform, drawn as the Transform it is in standAlone mode.

Its `translation`, `rotation`, `scale`, `scaleOrientation` and `center` place
its children as a Transform's do; the DIS network is neither read nor written.
"""
import types

import numpy as np
from vrml.cache import Cache

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import Box, Shape, sceneGraph


def test_an_espdu_transform_draws_its_children():
    shape = Shape(geometry=Box())
    entity = prototypes()['EspduTransform'](children=[shape])
    assert entity.renderedChildren() == [shape]


def test_it_places_its_children():
    shape = Shape(geometry=Box())
    entity = prototypes()['EspduTransform'](translation=(1, 2, 3), scale=(2, 2, 2),
                                            children=[shape])
    graph = sceneGraph(children=[entity])
    matrix = np.asarray((nodepath.NodePath([]) + graph + entity + shape).transformMatrix())
    assert np.allclose(matrix[3, :3], (1, 2, 3))
    assert np.allclose(np.diag(matrix)[:3], 2)


def test_it_is_bounded_by_its_placed_children():
    entity = prototypes()['EspduTransform'](translation=(5, 0, 0),
                                            children=[Shape(geometry=Box(size=(2, 2, 2)))])
    mode = types.SimpleNamespace(cache=Cache())
    points = entity.boundingVolume(mode).getPoints()[:, :3]
    assert np.allclose(points.min(axis=0), (4, -1, -1))


def test_a_document_of_one_draws(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="0 0 6"/>
      <EspduTransform translation="0 0 0" networkMode="standAlone">
        <Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance><Box/></Shape>
      </EspduTransform>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(48, 48)) as context:
        image = drawn_image(context)
    assert image[24, 24].max() > 128


def test_a_texture_coordinate_generator_is_an_implemented_node():
    assert 'TextureCoordinateGenerator' in prototypes()
