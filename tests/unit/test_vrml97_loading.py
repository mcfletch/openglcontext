"""VRML97 worlds read into the engine's nodes.

`OpenGLContext.loaders.vrml97` reads `.wrl`, `.wrz` and `.vrml` through
`vrml.x3d`'s ClassicVRML reader, with the VRML97 dialect, and builds each node
from the engine's class for it: the X3D nodes it implements, and its own nodes
that X3D does not have (the VRML97 NURBS extension, `SimpleBackground`,
`IndexedPolygons`, `FontStyle3D`, and any registered with
`standardPrototype`).
"""
import gzip

from OpenGLContext.loaders import vrml97
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.scenegraph import SceneGraph

HEADER = b'#VRML V2.0 utf8\n'

EXTENSIONS = HEADER + b'''
SimpleBackground { color 0 0 1 }
Shape { geometry IndexedPolygons { polygonSides 3 index [ 0 1 2 ] } }
Shape { geometry Text { string "A" fontStyle FontStyle3D { size 0.5 } } }
Shape { geometry NurbsCurve { knot [ 0 0 1 1 ] controlPoint [ 0 0 0, 1 1 0 ] } }
'''


def reported(scene):
    return [str(problem) for problem in scene.problems if problem.severity != 'info']


def test_the_engines_own_nodes():
    scene = Loader.loads(EXTENSIONS, 'world.wrl')
    assert isinstance(scene, SceneGraph)
    background, polygons, text, curve = scene.children
    assert type(background) is basenodes.SimpleBackground
    assert type(polygons.geometry) is basenodes.IndexedPolygons
    assert type(text.geometry.fontStyle) is basenodes.FontStyle3D
    assert type(curve.geometry) is basenodes.NurbsCurve
    assert curve.geometry.controlPoint.tolist() == [[0, 0, 0], [1, 1, 0]]
    assert reported(scene) == []


def test_standard_nodes_are_the_engines():
    scene = Loader.loads(HEADER + b'Transform { children Shape { geometry Box {} } }', 'w.wrl')
    assert type(scene.children[0]) is basenodes.Transform
    assert type(scene.children[0].children[0].geometry) is basenodes.Box


def test_a_prototype_instance_holds_its_own_children():
    scene = Loader.loads(HEADER + b'''
PROTO X [ exposedField MFNode children [] ] {
    Transform { children IS children }
}
X { children [ DEF S Shape { geometry Sphere {} } ] }
''', 'proto.wrl')
    assert [type(child) for child in scene.children[0].children] == [basenodes.Shape]
    assert reported(scene) == []


def test_a_registered_standard_prototype():
    class Marker(basenodes.Group):
        PROTO = 'Marker'

    vrml97.standardPrototype(Marker, 'Marker')
    try:
        scene = Loader.loads(HEADER + b'Marker { }', 'marker.wrl')
    finally:
        del vrml97.STANDARD_PROTOTYPES['Marker']
    assert type(scene.children[0]) is Marker
    assert reported(scene) == []


def test_a_registration_replaces_a_built_in_node():
    class Plain(basenodes.Box):
        PROTO = 'Box'

    vrml97.standardPrototype(Plain, 'Box')
    try:
        scene = Loader.loads(HEADER + b'Shape { geometry Box { } }', 'box.wrl')
    finally:
        vrml97.STANDARD_PROTOTYPES['Box'] = basenodes.Box
    assert type(scene.children[0].geometry) is Plain


def test_the_nurbs_extensions_trimming_curve():
    assert vrml97.vrml97_prototypes()['Polyline2D'] is basenodes.PROTOTYPES['Polyline2D']


def test_compressed():
    scene = Loader.loads(gzip.compress(EXTENSIONS), 'world.wrz')
    assert type(scene.children[0]) is basenodes.SimpleBackground


def test_a_broken_world_reports_where():
    scene = Loader.loads(HEADER + b'Transform { children [ Shape { ', 'broken.wrl')
    assert any('line' in problem for problem in reported(scene))
