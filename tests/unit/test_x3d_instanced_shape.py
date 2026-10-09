"""X_ITE's InstancedShape: one shape drawn at many places in one instanced draw.

Instance i is placed as a Transform with the i-th of each of translations,
rotations, scales, scaleOrientations and centers; a shorter list gives its
last entry to the instances past it, an empty one its default.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.instancedshape import InstancedShape, transform_placements
from OpenGLContext.scenegraph.transform import Transform


def transform_matrix(**fields):
    return np.asarray(Transform(**fields).localMatrices().data[0], 'f')


def test_each_placement_is_its_transform():
    fields = dict(translation=(1, 2, 3), rotation=(0, 1, 0, 0.5), scale=(2, 1, 0.5),
                  scaleOrientation=(1, 0, 0, 0.3), center=(0.5, 0, -1))
    found = transform_placements([(1, 2, 3)], [(0, 1, 0, 0.5)], [(2, 1, 0.5)],
                                 [(1, 0, 0, 0.3)], [(0.5, 0, -1)])
    assert found.shape == (1, 4, 4)
    assert np.allclose(found[0], transform_matrix(**fields), atol=1e-5)


def test_a_short_list_gives_its_last_entry_and_an_empty_one_its_default():
    found = transform_placements([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [], [(2, 2, 2)], [], [])
    assert len(found) == 3
    assert np.allclose(found[:, 3, :3], [(0, 0, 0), (1, 0, 0), (2, 0, 0)])
    assert np.allclose(found[:, 0, 0], 2.0)


def test_no_lists_is_no_placements():
    assert transform_placements([], [], [], [], []).shape == (0, 4, 4)


def test_the_x3d_fields_place_the_shape():
    shape = InstancedShape(translations=[(-1, 0, 0), (1, 0, 0)], geometry=x3d.Box())
    placements = shape.instancePlacements()
    assert placements is not None and len(placements) == 2
    assert not shape.drawsNothing()
    assert InstancedShape(geometry=x3d.Box()).drawsNothing()
    shape.translations = [(5, 0, 0)]
    assert np.allclose(shape.instancePlacements()[:, 3, :3], [(5, 0, 0)])


ROW = b'''<X3D version="4.0"><head><component name="X_ITE" level="1"/></head><Scene>
  <Background skyColor="0 0 0"/><Viewpoint position="0 0 6"/>
  <InstancedShape translations="-1.5 0 0 1.5 0 0" scales="0.5 0.5 0.5">
    <Appearance><UnlitMaterial emissiveColor="1 0 0"/></Appearance><Box/></InstancedShape>
</Scene></X3D>'''


def test_an_instanced_shape_is_drawn_at_each_place(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(ROW, 'row.x3d')
    assert isinstance(scene.children[2], InstancedShape)
    with scene_context(scene, size=(64, 32)) as context:
        image = drawn_image(context).astype(int)
    row = image[16]
    assert row[32].sum() < 30                        # nothing between them
    assert row[22][0] > 200 and row[42][0] > 200     # a box at each place


@pytest.mark.parametrize('encoding', ['xml', 'classic'])
def test_it_is_written_as_x_ite_s_node(encoding):
    from vrml import x3d as vrml_x3d  # noqa: PLC0415 kept with its use
    from vrml.x3d.scene import X3DScene  # noqa: PLC0415 kept with its use

    from OpenGLContext.loaders.x3d import prototypes  # noqa: PLC0415 kept with its use
    shape = InstancedShape(translations=[(1, 0, 0), (2, 0, 0)], geometry=x3d.Box())
    text = vrml_x3d.dumps(X3DScene(children=[shape]), encoding=encoding)
    assert 'InstancedShape' in text
    read = vrml_x3d.loads(text, prototypes=prototypes()).children[0]
    assert isinstance(read, InstancedShape)
    assert len(read.translations) == 2
