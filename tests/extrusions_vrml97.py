#! /usr/bin/env python
'''=VRML97 Extrusion=

[extrusions_vrml97.py-screen-0001.png Screenshot]

VRML97's own `Extrusion` node, with the fields that specification gives it.
A cross-section is swept along a spine, and at every spine point a scale and
an orientation may be applied.

 * *the defaults* -- a unit square swept one unit up, which is what the node
   is when you write `Extrusion {}`.
 * *scale* -- the same box with the cross-section shrinking along the spine:
   a tapered plinth.
 * *orientation* -- the cross-section turned as it travels, a quarter turn
   over the length.
 * *a curved spine* -- the cross-section carried along a bend, oriented by
   the specification's Spine-aligned Cross-section Plane rather than by any
   reference direction.
 * *no caps* -- `beginCap FALSE endCap FALSE`, so the shape is a tube open
   at both ends and you can see through it.
 * *a closed spine* -- a spine whose last point repeats its first, which
   the specification says makes a loop: no ends, and no caps to put on them.

The cross-section is read in the x-z plane, as the specification writes it,
where the outward-facing order is *clockwise* -- so the circles here are
reversed before use.
'''
from math import pi

import numpy as np

from opengl_extrusions import circle

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Extrusion, Material, Shape, Transform,
    Viewpoint, sceneGraph,
)

#: A closed cross-section: VRML closes one by repeating its first point, and
#: reads it in the x-z plane -- where the outward-facing order is *clockwise*,
#: which is why the circle is reversed. (VRML97's own default cross-section is
#: clockwise there too.)
RING = np.vstack([circle(0.32, 16)[::-1], circle(0.32, 16)[::-1][:1]])

#: A spine that bends, so the SCP has something to orient against.
BEND = [(0, -0.8, 0), (0, -0.2, 0), (0.5, 0.35, 0.2), (0.15, 0.9, 0.4)]


def loop_spine(samples=28, radius=0.62):
    angles = np.linspace(0, 2 * np.pi, samples, endpoint=False)
    ring = np.column_stack([radius * np.cos(angles), np.zeros(samples),
                            radius * np.sin(angles)])
    return np.vstack([ring, ring[:1]])


def panels():
    tall = [(0, -0.75, 0), (0, 0.75, 0)]
    return [
        ((0.85, 0.55, 0.30), Extrusion(scale=[(0.4, 0.4)], spine=tall)),
        ((0.35, 0.70, 0.90), Extrusion(spine=[(0, -0.75, 0), (0, 0, 0), (0, 0.75, 0)],
                                       scale=[(0.5, 0.5), (0.3, 0.3),
                                              (0.08, 0.08)])),
        ((0.85, 0.75, 0.30), Extrusion(
            spine=[(0, -0.75, 0), (0, -0.25, 0), (0, 0.25, 0), (0, 0.75, 0)],
            scale=[(0.55, 0.18)],
            orientation=[(0, 1, 0, 0.0), (0, 1, 0, pi / 6),
                         (0, 1, 0, pi / 3), (0, 1, 0, pi / 2)])),
        ((0.50, 0.80, 0.50), Extrusion(crossSection=RING, spine=BEND,
                                       creaseAngle=1.2)),
        ((0.80, 0.50, 0.85), Extrusion(crossSection=RING, spine=tall,
                                       beginCap=False, endCap=False),
         # Tipped far enough to look down the open end, which is the whole
         # point of the panel.
         (1, 0, 0, -1.15)),
        ((0.55, 0.72, 0.95), Extrusion(crossSection=np.vstack([circle(0.16, 12)[::-1],
                                                               circle(0.16, 12)[::-1][:1]]),
                                       spine=loop_spine(), creaseAngle=1.2),
         # Seen at the others' angle a flat loop reads as an ellipse; tip it
         # further so it reads as the ring it is.
         (1, 0, 0, -1.15)),
    ]


class TestContext(BaseContext):
    """Six VRML97 extrusions, three across and two down."""

    def OnInit(self):
        children = []
        across, spacing = 3, 2.6
        for index, entry in enumerate(panels()):
            colour, geometry = entry[0], entry[1]
            tilt = entry[2] if len(entry) > 2 else (1, 0, 0, -0.4)
            column, row = index % across, index // across
            children.append(Transform(
                translation=((column - 1) * spacing, (0.5 - row) * spacing, 0),
                rotation=tilt,
                children=[Shape(
                    geometry=geometry,
                    appearance=Appearance(material=Material(
                        diffuseColor=colour, ambientIntensity=0.45,
                        # A low self-illumination floor: several of these face
                        # away from every light at once, and a figure whose
                        # subject is black shows nothing.
                        emissiveColor=tuple(c * 0.26 for c in colour),
                        shininess=0.5)))],
            ))
        children.append(Viewpoint(position=(0, 0, 8.6)))
        # A light down the view direction, so nothing facing the camera is
        # dark, plus a key from above for shape and a low fill so the
        # undersides are not black.
        children.append(DirectionalLight(direction=(0, 0, -1),
                                         color=(0.55, 0.55, 0.58)))
        children.append(DirectionalLight(direction=(-0.35, -0.6, -0.7),
                                         color=(0.5, 0.5, 0.52)))
        children.append(DirectionalLight(direction=(0.3, 0.7, -0.65),
                                         color=(0.28, 0.28, 0.32)))
        self.sg = sceneGraph(children=children)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
