#! /usr/bin/env python
'''=Tessellation Preprocessing=

[extrusions_preprocessing.py-screen-0001.png Screenshot]

A constrained triangulation needs its input *planar*: distinct vertices,
edges meeting only at shared endpoints, and no vertex sitting in the middle
of somebody else's edge. Almost nothing real arrives that way, so the
tessellator makes it so first. Each panel is an outline that would defeat a
triangulator taken literally, and what the preprocessing turns it into.

 * *self-crossing* -- one outline that crosses itself. Split at the
   crossing, which becomes a new vertex; the odd rule then leaves the
   doubly-wound middle empty.
 * *two rings crossing* -- both split at both crossings, so neither edge
   passes through the other.
 * *a T-junction* -- one shape's corner lands in the middle of another's
   edge. That edge is split there, because a triangulation cannot leave a
   vertex floating on an edge it does not share.
 * *a shared edge* -- two shapes butted together and wound the same way.
   The shared stretch is traversed once each way, carries no winding
   change, and is not a boundary: the two become one region with no wall
   between them.
 * *near-duplicate points* -- vertices closer than the tolerance are one
   vertex, rather than a sliver whose normal is noise.
 * *a repeated first point* -- the convention most file formats use to
   close a ring, dropped rather than left as a zero-length edge.

The white lines are the triangle edges, so what the preprocessing decided
can be read off the result.
'''
import numpy as np

from opengl_extrusions import circle, tessellate

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Material, PointLight, Shape, Transform,
    Viewpoint, sceneGraph,
)
from OpenGLContext.scenegraph.frommesh import mesh_from_primitive

from extrusions_tessellation import flat_mesh, wireframe

#: Each panel: what makes it awkward, and the outlines that show it.
PANELS = [
    ('self-crossing', [[(-1, -1), (1, 1), (1, -1), (-1, 1)]], (0.85, 0.55, 0.30)),
    ('two rings crossing', [[(-1.1, -1.1), (0.3, -1.1), (0.3, 0.3), (-1.1, 0.3)],
                            [(-0.3, -0.3), (1.1, -0.3), (1.1, 1.1), (-0.3, 1.1)]],
     (0.40, 0.70, 0.90)),
    ('a T-junction', [[(-1, -1), (1, -1), (1, 1), (-1, 1)],
                      [(0, 1), (0.6, 1.7), (-0.6, 1.7)]], (0.85, 0.75, 0.35)),
    ('a shared edge', [[(-1.2, -0.8), (0, -0.8), (0, 0.8), (-1.2, 0.8)],
                       [(0, -0.8), (1.2, -0.8), (1.2, 0.8), (0, 0.8)]],
     (0.50, 0.80, 0.50)),
    ('near-duplicate points', [[(-1, -1), (1, -1), (1, 1), (1 + 1e-9, 1 + 1e-9),
                                (-1, 1)]], (0.80, 0.50, 0.80)),
    ('a repeated first point', [list(circle(1.0, 12)) + [tuple(circle(1.0, 12)[0])]],
     (0.55, 0.72, 0.95)),
]


class TestContext(BaseContext):
    """Six awkward inputs, and what the preprocessing makes of them."""

    def OnInit(self):
        children = []
        across, spacing = 3, 2.7
        for index, (_label, contours, colour) in enumerate(PANELS):
            result = tessellate([np.asarray(c, dtype=float) for c in contours])
            column, row = index % across, index // across
            children.append(Transform(
                translation=((column - 1) * spacing, (0.5 - row) * spacing, 0),
                children=[
                    Shape(geometry=mesh_from_primitive(
                              flat_mesh(result).primitives[0]),
                          appearance=Appearance(material=Material(
                              diffuseColor=colour, shininess=0.2))),
                    wireframe(result),
                ],
            ))
        children.append(Viewpoint(position=(0, 0, 7.8)))
        children.append(PointLight(location=(2, 3, 8)))
        children.append(DirectionalLight(direction=(-0.2, -0.3, -0.9),
                                         color=(0.5, 0.5, 0.5)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
