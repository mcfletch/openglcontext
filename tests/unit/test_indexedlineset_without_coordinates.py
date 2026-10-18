"""An IndexedLineSet with no Coordinate node has no lines to expand or draw.

X3D allows the node to be left out of a line set; the polylines it indexes
then name no points.
"""
import logging

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.indexedlineset import IndexedLineSet
from OpenGLContext.testing.scenes import drawn_image, scene_context


def test_a_line_set_without_coordinates_expands_to_no_vertices():
    positions, colours = IndexedLineSet(coordIndex=[0, 1, -1])._expand_line_vertices()
    assert positions.shape == (0, 3) and colours.shape == (0, 3)


def test_shared_line_sets_without_coordinates_draw_nothing(gl_context, caplog):
    shape = ('<Shape><Appearance><Material/></Appearance>'
             '<IndexedLineSet coordIndex="0 1 -1"/></Shape>')
    document = ('<X3D version="4.0"><Scene><Viewpoint position="0 0 4"/>%s</Scene></X3D>'
                % (shape * 8)).encode()
    scene = Loader.loads(document, 'scene.x3d')
    with caplog.at_level(logging.ERROR), scene_context(list(scene.children)) as context:
        drawn_image(context)
        drawn_image(context)
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
