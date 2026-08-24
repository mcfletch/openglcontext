#! /usr/bin/env python
'''=Extrusion Normal Modes=

[extrusions_normals.py-screen-0001.png Screenshot]

The same geometry three ways. A normal mode changes no vertex position -- it
decides only which way the surface is said to face, and therefore what it
looks like under a light.

Top row, a *hexagonal* tube: this is what `edge` is for.

 * *facet* -- one normal per face. Six flat faces, six hard edges. Correct
   for a hex bolt or a crystal, where the facets are the point.
 * *edge* -- normals follow the contour's own, so the six faces blend into
   each other and a six-sided tube shades like a cylinder. The silhouette
   is still a hexagon; only the shading is round.
 * *path_edge* -- the same across the contour, and smooth along the path
   as well. On a straight tube there is nothing along the path to smooth,
   so this matches `edge`.

Bottom row, a round tube round a *corner*: this is what `path_edge` is for.

 * *facet* -- every quad flat, so the tube reads as a stack of rings.
 * *edge* -- smooth around the tube, creased at the corner. The corner
   stays a corner, which is what a mitred pipe joint should look like.
 * *path_edge* -- smooth along the path too, so the corner rounds off
   visually. What you want for something bending smoothly, like a hose.

Pick `edge` unless you know you want one of the others: it keeps the
outline's curves smooth and the path's corners sharp, which is what most
swept shapes mean.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Material, PointLight, PolyCylinder, Shape,
    Transform, Viewpoint, sceneGraph,
)

#: A straight run, where the contour's own shading is all there is to see.
STRAIGHT = [(0.0, -1.0, 0.0), (0.0, 1.0, 0.0)]

#: A right angle, where the shading *along* the path becomes visible.
CORNER = [(-0.8, -0.9, 0.0), (0.0, -0.9, 0.0), (0.0, 0.9, 0.0)]

MODES = ('facet', 'edge', 'path_edge')


def look(colour):
    return Appearance(material=Material(diffuseColor=colour, shininess=0.75))


class TestContext(BaseContext):
    """Three normal modes, on two shapes that show different things."""

    def OnInit(self):
        children = []
        spacing = 2.5
        for column, mode in enumerate(MODES):
            # A hexagon: 'facet' and 'edge' differ as much as they ever do.
            children.append(Transform(
                translation=((column - 1) * spacing, 1.3, 0),
                children=[Shape(
                    geometry=PolyCylinder(path=STRAIGHT, radius=0.55, sides=6,
                                          normals=mode, caps=True),
                    appearance=look((0.85, 0.62, 0.28)))],
            ))
            # A corner: 'edge' and 'path_edge' differ as much as they ever do.
            children.append(Transform(
                translation=((column - 1) * spacing, -1.5, 0),
                children=[Shape(
                    geometry=PolyCylinder(path=CORNER, radius=0.4, sides=20,
                                          normals=mode, join='angle', caps=True),
                    appearance=look((0.38, 0.68, 0.88)))],
            ))
        children.append(Viewpoint(position=(0, 0, 7.6)))
        children.append(PointLight(location=(3, 4, 7)))
        children.append(DirectionalLight(direction=(-0.4, -0.3, -0.85),
                                         color=(0.45, 0.45, 0.5)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
