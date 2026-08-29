#! /usr/bin/env python
"""Animated shadow-mapping demo.

A sphere, a NURBS surface and a spinning box float above an IndexedFaceSet ground
plane and back wall. Three lights with subtly different colours show where the
light comes from: a warm spotlight (upper right), a cool point light (orbiting
overhead) and a green-tinted directional light. Each casts shadows, so a shadow
that blocks one light is tinted by the others.

Every frame the occluders and the lights move, so the cast shadows update live --
the high sphere's shadow sweeps across the box, the NURBS hill and the floor --
demonstrating that the shadow pass re-renders depth from the current scenegraph
state each frame.

Runs with shadow mapping on (core profile). Override via the environment:
    OPENGLCONTEXT_SHADOWS=0        no shadows
    OPENGLCONTEXT_SHADOWS_SOFT=1   soft (PCSS) shadows
"""
import os
from math import sin, cos, pi

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, Transform, Shape, Appearance, Material,
    Sphere, Box, IndexedFaceSet, Coordinate, NurbsSurface,
    PointLight, DirectionalLight, SpotLight,
)
from OpenGLContext.arrays import zeros
from OpenGLContext.events import systemtime


# Knot vector for an order-4 (cubic) 4x4 NURBS patch
NURBS_KNOTS = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


def _nurbs_control_points(amp=1.0):
    """A 4x4 grid of control points forming a gentle hill (z = height)."""
    pts = zeros((4, 4, 3), 'd')
    for u in range(4):
        for v in range(4):
            pts[u][v][0] = 1.5 * (u - 1.5)
            pts[u][v][1] = 1.5 * (v - 1.5)
            centre = (u in (1, 2)) and (v in (1, 2))
            pts[u][v][2] = (amp * 2.0) if centre else -amp * 0.5
    return pts


def _quad(corners, color, solid=False):
    """An IndexedFaceSet quad receiver from four CCW corners."""
    return Shape(
        appearance=Appearance(
            material=Material(diffuseColor=color, ambientIntensity=0.3),
        ),
        geometry=IndexedFaceSet(
            coord=Coordinate(point=corners),
            coordIndex=[0, 1, 2, 3, -1],
            solid=solid,
            normalPerVertex=1,
            creaseAngle=3.14,
        ),
    )


class TestContext(BaseContext):
    # Raised and back, looking down at the floor under the NURBS hill (0, 0, -3)
    # so the floor and its cast shadows fill the foreground, the objects sit on
    # it, and the wall rises behind. Negative X-rotation pitches the view down;
    # the angle aims at that point: atan(11 / (15 + 3)) ~= 0.55 rad below level.
    initialPosition = (0, 11, 15)
    initialOrientation = (1, 0, 0, -0.55)

    def OnInit(self):
        # --- receivers: ground (XZ plane) + back wall (XY plane) ---
        ground = Transform(children=[_quad(
            [(-14, 0, 14), (14, 0, 14), (14, 0, -14), (-14, 0, -14)],
            color=(0.72, 0.72, 0.72),
        )])
        wall = Transform(children=[_quad(
            [(-14, 0, 0), (14, 0, 0), (14, 10, 0), (-14, 10, 0)],
            color=(0.55, 0.6, 0.72),
        )], translation=(0, 0, -12))

        # --- animated occluders ---
        self.sphere = Transform(
            translation=(5, 6.0, 0),
            children=[Shape(
                appearance=Appearance(material=Material(
                    diffuseColor=(0.9, 0.2, 0.2), specularColor=(0.4, 0.4, 0.4),
                    shininess=0.4, ambientIntensity=0.3)),
                geometry=Sphere(radius=1.4),
            )],
        )
        self.box = Transform(
            translation=(-5, 1.5, 1),
            children=[Shape(
                appearance=Appearance(material=Material(
                    diffuseColor=(0.2, 0.5, 0.9), ambientIntensity=0.3)),
                geometry=Box(size=(2.2, 2.2, 2.2)),
            )],
        )
        self.nurbs = Transform(
            translation=(0, 3.5, -3), scale=(1.4, 1.4, 1.4),
            rotation=(1, 0, 0, -pi / 2),   # lay the patch so its hill faces up
            children=[Shape(
                appearance=Appearance(material=Material(
                    diffuseColor=(0.3, 0.8, 0.4), ambientIntensity=0.3)),
                geometry=NurbsSurface(
                    controlPoint=_nurbs_control_points(),
                    uDimension=4, vDimension=4,
                    uKnot=NURBS_KNOTS, vKnot=NURBS_KNOTS,
                ),
            )],
        )

        # --- three lights with subtly different colours so you can tell which
        #     light each shadow/highlight comes from ---
        # Warm spotlight from the upper right (cyan-ish shadows where it's blocked)
        self.spot = Transform(
            translation=(11, 13, 5),
            children=[SpotLight(
                color=(1.0, 0.85, 0.65), intensity=1.0, ambientIntensity=0.15,
                direction=(-11, -13, -5), cutOffAngle=0.7, beamWidth=0.5,
                attenuation=(1, 0, 0.0),
            )],
        )
        # Cool point light orbiting overhead (warm shadows where it's blocked)
        self.point = Transform(
            translation=(-8, 11, 6),
            children=[PointLight(
                color=(0.55, 0.7, 1.0), intensity=1.0, ambientIntensity=0.15,
                attenuation=(1, 0, 0.0),
            )],
        )
        # Steady green-tinted directional light showing a constant light direction
        directional = DirectionalLight(
            direction=(0.3, -0.7, -0.4), color=(0.6, 0.95, 0.7),
            intensity=0.8, ambientIntensity=0.15,
        )

        self.sg = sceneGraph(children=[
            ground, wall,
            self.sphere, self.box, self.nurbs,
            self.spot, self.point, directional,
        ])
        self._start = systemtime.systemTime()

    def OnIdle(self, *args):
        """Drive the animation; updating node fields re-renders the shadows."""
        t = systemtime.systemTime() - self._start
        # sphere orbits high overhead so its shadow falls onto the box, NURBS and floor
        self.sphere.translation = (5 * cos(t * 0.9), 6.0 + 1.2 * sin(t * 1.8), 5 * sin(t * 0.9))
        # box spins in place
        self.box.rotation = (0, 1, 0, t * 1.3)
        # nurbs patch breathes vertically (parent keeps it laid flat)
        self.nurbs.scale = (1.4, 1.4 + 0.2 * sin(t), 1.4)
        # point light orbits overhead so its (cool) shadows sweep across the ground
        self.point.translation = (8 * cos(t * 0.5), 11, 6 + 4 * sin(t * 0.5))
        # spotlight slowly sweeps its aim across the scene
        sx = 11 + 4 * sin(t * 0.3)
        self.spot.translation = (sx, 13, 5)
        self.spot.children[0].direction = (-sx, -13, -5)
        self.triggerRedraw(1)
        return 1


if __name__ == "__main__":
    TestContext.ContextMainLoop()
