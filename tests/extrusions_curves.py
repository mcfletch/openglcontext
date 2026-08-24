#! /usr/bin/env python
'''=Sweeping Along Curves=

[extrusions_curves.py-screen-0001.png Screenshot]

A path given as a list of points is a decision already made -- how many
points, and where. These are swept along *curves* instead, with the
sampling chosen from the shape rather than by hand.

 * *Catmull-Rom, coarse* and *Catmull-Rom, fine* -- the same four waypoints
   through which the curve must pass, sampled to a chord-error tolerance a
   hundred times apart. The coarse one shows its facets; the fine one does
   not, and the samples went where the curve bends rather than being spread
   evenly along it.
 * *Bezier* -- a control cage that pulls the curve about without being
   touched by it.
 * *B-spline* -- smoother again through the same cage.
 * *Rotation-minimizing frames* -- a loop that runs straight up through the
   vertical, where a frame kept aligned to a fixed "up" has nothing left to
   align to. The rotation-minimizing frame carries along the path instead
   and has no such direction.
 * *A closed loop* -- a path whose end joins its start, swept with no ends
   and therefore no caps: a torus knot that is one continuous surface.

Every curve here is sampled by `opengl_extrusions.curves`; the geometry is
`PolyCylinder` with the sampled points as its path.
'''
import numpy as np

from opengl_extrusions import bezier, bspline, catmull_rom

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Material, PointLight, PolyCylinder, Shape,
    Transform, Viewpoint, sceneGraph,
)

#: Waypoints a Catmull-Rom curve is made to pass through.
WAYPOINTS = [(-1.0, -0.8, 0.0), (-0.3, 0.9, 0.4), (0.4, -0.9, -0.4), (1.1, 0.8, 0.0)]

#: A cage for the Bezier and B-spline curves; neither touches the middle two.
CAGE = [(-1.1, -0.9, 0.0), (-0.4, 1.4, 0.5), (0.4, 1.4, -0.5), (1.1, -0.9, 0.0)]


def trefoil(samples=160, scale=0.55):
    """A trefoil knot: a closed path that is nowhere flat and nowhere straight."""
    t = np.linspace(0, 2 * np.pi, samples, endpoint=False)
    return scale * np.column_stack([
        np.sin(t) + 2 * np.sin(2 * t),
        np.cos(t) - 2 * np.cos(2 * t),
        -np.sin(3 * t),
    ])


def vertical_loop(samples=64):
    """A path that passes straight through vertical, which breaks an up vector."""
    t = np.linspace(0, 2 * np.pi, samples)
    return np.column_stack([0.9 * np.sin(t), 1.2 * np.cos(t), 0.3 * np.sin(2 * t)])


#: Each panel: the path to sweep, its radius, and its colour.
def panels():
    return [
        (catmull_rom(WAYPOINTS, tolerance=0.05), 0.10, (0.85, 0.45, 0.30)),
        (catmull_rom(WAYPOINTS, tolerance=0.0005), 0.10, (0.35, 0.70, 0.90)),
        (bezier(CAGE, tolerance=0.001), 0.10, (0.85, 0.75, 0.30)),
        (bspline(CAGE, degree=3, tolerance=0.001), 0.10, (0.50, 0.80, 0.50)),
        (vertical_loop(), 0.09, (0.80, 0.50, 0.85)),
        (trefoil(), 0.13, (0.55, 0.65, 0.85)),
    ]


class TestContext(BaseContext):
    """Six swept curves, three across and two down."""

    def OnInit(self):
        children = []
        across, spacing = 3, 2.9
        for index, (path, radius, colour) in enumerate(panels()):
            column, row = index % across, index // across
            closed = index == 5
            children.append(Transform(
                translation=((column - 1) * spacing, (0.5 - row) * spacing, 0),
                children=[Shape(
                    geometry=PolyCylinder(
                        path=path, radius=radius, sides=14, frames='rmf',
                        caps=not closed),
                    appearance=Appearance(material=Material(diffuseColor=colour,
                                                            shininess=0.6)))],
            ))
        children.append(Viewpoint(position=(0, 0, 9.4)))
        children.append(PointLight(location=(3, 5, 8)))
        children.append(DirectionalLight(direction=(-0.3, -0.5, -0.8),
                                         color=(0.45, 0.45, 0.5)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
