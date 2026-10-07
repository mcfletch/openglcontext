"""X3D's grouping nodes beyond Group and Transform, drawn as groups.

CADAssembly, CADLayer and PickableGroup draw their children; CADPart draws
them transformed, as a Transform does.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import Box, Shape, sceneGraph


@pytest.mark.parametrize('name', ['CADAssembly', 'CADLayer', 'CADPart', 'PickableGroup'])
def test_each_draws_its_children(name):
    shape = Shape(geometry=Box())
    group = prototypes()[name](children=[shape])
    assert group.renderedChildren() == [shape]


def test_a_cad_part_places_its_children():
    shape = Shape(geometry=Box())
    part = prototypes()['CADPart'](translation=(1, 2, 3), children=[shape])
    graph = sceneGraph(children=[part])
    path = nodepath.NodePath([]) + graph + part + shape
    assert np.allclose(np.asarray(path.transformMatrix())[3, :3], (1, 2, 3))


def test_a_document_of_cad_nodes_draws(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="0 0 6"/>
      <CADLayer><CADAssembly><CADPart translation="0 0 0">
        <Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance><Box/></Shape>
      </CADPart></CADAssembly></CADLayer>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(48, 48)) as context:
        image = drawn_image(context)
    assert image[24, 24].max() > 128
