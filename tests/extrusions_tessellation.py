#! /usr/bin/env python
'''=Polygon Tessellation=

[extrusions_tessellation.py-screen-0001.png Screenshot]

What the tessellator does, drawn as the triangles it produces. Every face
here was a 2D outline a moment ago; the white lines are the edges of the
triangles it became, so the effect of each feature can be seen rather than
described.

Top row -- *what it can take in*:

 * A letter-O: two rings, the inner one a hole. Holes need no special
   handling; they are what the winding rule says they are.
 * A pentagram drawn as one self-crossing outline, filled by the *odd*
   rule: the middle, wound twice, comes out empty.
 * The same pentagram by the *nonzero* rule: the middle is wound, so it
   fills.

Bottom row -- *how fine it can go*:

 * A rounded square, plain. The triangles are as few as the outline
   allows, and as close to equilateral as a Delaunay triangulation makes
   them.
 * The same shape refined to a maximum triangle area: evenly subdivided
   throughout.
 * A star refined to a minimum angle instead: dense only where the outline
   forces thin triangles, and left alone where it does not. Notice how much
   of the shape it leaves alone compared with the area target beside it.

Every triangulation is constrained Delaunay, so no vertex lies inside any
triangle's circumcircle and the smallest angle in the mesh is as large as
the outline permits. That is what keeps the triangles shading well and
subdividing well.
'''
import numpy as np

from opengl_extrusions import circle, rounded_rectangle, star, tessellate

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, Coordinate, DirectionalLight, IndexedLineSet, Material,
    PointLight, Shape, Transform, Viewpoint, sceneGraph,
)
from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
from opengl_extrusions.mesh import Mesh, Primitive


def pentagram(radius=1.0):
    """A five-pointed star drawn as a single outline that crosses itself."""
    angles = np.linspace(0, 4 * np.pi, 5, endpoint=False) + np.pi / 2
    return np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])


def letter_o(outer=1.0, inner=0.55, sides=48):
    """An outer ring and a hole, the way a font describes a counter."""
    return [circle(outer, sides), circle(inner, sides)[::-1]]


def flat_mesh(result):
    """A tessellation as a flat, upward-facing mesh in the z=0 plane."""
    positions = np.column_stack([result.points,
                                 np.zeros(len(result.points))]).astype('f')
    normals = np.tile(np.array([0, 0, 1], 'f'), (len(positions), 1))
    return Mesh([Primitive({'POSITION': positions, 'NORMAL': normals},
                           result.triangles.ravel())])


def wireframe(result, lift=0.01):
    """The triangle edges, as a line set floating just above the face."""
    points = np.column_stack([result.points,
                              np.full(len(result.points), lift)]).astype('f')
    index = []
    for a, b, c in result.triangles:
        index.extend([int(a), int(b), int(c), int(a), -1])
    return Shape(
        geometry=IndexedLineSet(coord=Coordinate(point=points),
                                coordIndex=index),
        appearance=Appearance(material=Material(emissiveColor=(1, 1, 1))),
    )


#: Each panel: a label for the reader, the outline(s), and how to tessellate.
PANELS = [
    ('letter O', letter_o(), {}, (0.85, 0.55, 0.30)),
    ('pentagram, odd', [pentagram()], {'winding': 'odd'}, (0.40, 0.70, 0.90)),
    ('pentagram, nonzero', [pentagram()], {'winding': 'nonzero'}, (0.40, 0.70, 0.90)),
    ('rounded square', [rounded_rectangle(1.9, 1.9, 0.5, 10)], {}, (0.85, 0.75, 0.35)),
    ('max area 0.02', [rounded_rectangle(1.9, 1.9, 0.5, 10)],
     {'max_area': 0.02}, (0.50, 0.80, 0.50)),
    ('min angle 25', [star(6, 1.0, 0.32)], {'min_angle': 25.0}, (0.80, 0.50, 0.80)),
]


class TestContext(BaseContext):
    """Six tessellations, each with its own triangles drawn over it."""

    def OnInit(self):
        children = []
        across, spacing = 3, 2.6
        for index, (_label, contours, options, colour) in enumerate(PANELS):
            result = tessellate(contours, **options)
            column, row = index % across, index // across
            face = mesh_from_primitive(flat_mesh(result).primitives[0])
            children.append(Transform(
                translation=((column - 1) * spacing, (0.5 - row) * spacing, 0),
                children=[
                    Shape(geometry=face,
                          appearance=Appearance(
                              material=Material(diffuseColor=colour,
                                                shininess=0.2))),
                    wireframe(result),
                ],
            ))
        children.append(Viewpoint(position=(0, 0, 7.4)))
        children.append(PointLight(location=(2, 3, 8)))
        children.append(DirectionalLight(direction=(-0.2, -0.3, -0.9),
                                         color=(0.5, 0.5, 0.5)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
