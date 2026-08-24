#! /usr/bin/env python
'''=Extrusion Join Styles=

[extrusions_joins.py-screen-0001.png Screenshot]

The same square tube round the same right-angled corner, four ways. What a
join style decides is what happens where two straight runs meet, and the
difference is only visible at the corner itself.

 * *raw* (top left) -- each segment swept on its own, ending square. The
   tube comes apart at the corner. What you want for a chain of separate
   objects; never what you want for a pipe.
 * *angle* (top right) -- a mitre: one ring in the plane bisecting the
   corner, the outside of the turn stretched to reach it. Continuous, and
   the default.
 * *cut* (bottom left) -- a bevel: each run ends square and one flat band
   joins the two ends. It does not reach as far past the corner as a mitre
   does, and the band is shaded as the facet it is rather than as part of
   the tube.
 * *round* (bottom right) -- an elbow: the ring is turned through the bend
   in steps, so the corner is the tube itself rotated and the contour keeps
   the size it has everywhere else.

The fifth shape, in the middle, is a mitre at a *shallow* corner with the
miter limit doing its job: without a limit the outside of a nearly-reversed
corner stretches away to a spike, and past the limit the join bevels
instead.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Material, PointLight, PolyCylinder, Shape,
    Transform, Viewpoint, sceneGraph,
)

#: A right angle, which is where a join style shows itself.
CORNER = [(-1.0, -0.75, 0.0), (0.0, -0.75, 0.0), (0.0, 0.75, 0.0)]

#: The four styles, and where each sits in the frame.
LAYOUT = [
    ('raw', (-2.0, 1.7), (0.85, 0.35, 0.30)),
    ('angle', (2.0, 1.7), (0.35, 0.65, 0.85)),
    ('cut', (-2.0, -2.4), (0.85, 0.70, 0.25)),
    ('round', (2.0, -2.4), (0.45, 0.80, 0.45)),
]


def look(colour):
    return Appearance(material=Material(diffuseColor=colour, shininess=0.5))


class TestContext(BaseContext):
    """Four join styles, plus a mitre limit at work."""

    def OnInit(self):
        children = []
        for style, (x, y), colour in LAYOUT:
            children.append(Transform(
                translation=(x, y, 0),
                children=[Shape(
                    geometry=PolyCylinder(path=CORNER, radius=0.42, sides=16,
                                          join=style, roundSegments=6,
                                          normals='edge'),
                    appearance=look(colour))],
            ))
        # A hairpin, where an unlimited mitre would shoot off to a point.
        hairpin = [(-0.55, -0.9, 0.0), (0.0, 0.9, 0.0), (0.55, -0.85, 0.0)]
        children.append(Transform(
            translation=(0, -0.6, 0),
            children=[Shape(
                geometry=PolyCylinder(path=hairpin, radius=0.20, sides=12,
                                      join='angle'),
                appearance=look((0.75, 0.55, 0.85)))],
        ))
        children.append(Viewpoint(position=(0, -0.2, 8.6)))
        children.append(PointLight(location=(4, 6, 9)))
        children.append(DirectionalLight(direction=(-0.3, -0.6, -0.7),
                                         color=(0.4, 0.4, 0.45)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
