"""The two level-of-detail nodes a VRML97 file can name.

``LOD`` is the standard distance-based node and ``ScreenCoverageLOD`` is the
engine's own, so a world written to the VRML97 specification has to get the
first from the word ``LOD``. Pure Python -- no GL.
"""
from vrml import protofunctions

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.lod import LOD, ScreenCoverageLOD

WORLD = b"""#VRML V2.0 utf8
%s {
  %s
  level [ Group { } Group { } ]
}
"""


def _first_node(keyword, fields):
    return Loader.loads(WORLD % (keyword, fields), "world.wrl").children[0]


def test_the_word_lod_makes_the_distance_based_node():
    node = _first_node(b"LOD", b"range [ 10 ]")
    assert type(node) is LOD
    assert list(node.range) == [10]


def test_screen_coverage_lod_is_named_by_its_own_name():
    node = _first_node(b"ScreenCoverageLOD", b"screenCoverage [ 0.5 0 ]")
    assert type(node) is ScreenCoverageLOD


def test_each_node_carries_the_name_it_is_registered_under():
    assert protofunctions.name(LOD) == "LOD"
    assert protofunctions.name(ScreenCoverageLOD) == "ScreenCoverageLOD"
