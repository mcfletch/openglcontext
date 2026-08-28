#! /usr/bin/env python
"""=Distance Level-of-Detail demo=

Shows the distance-LOD system (``OpenGLContext.scenegraph.tessellationlod``) in
action across every geometry type that uses it: the Utah Teapot, the three
quadrics (Sphere, Cone, Cylinder) and a NURBS surface.

The camera slowly dollies from close up to far away and back.  As each object's
camera distance (measured in object-radii) crosses a threshold, its mesh is
re-tessellated -- and cached -- at a coarser resolution.  The geometry is drawn
as **wireframe** so the triangle density visibly drops as objects recede, and
each object's current LOD level is printed to the console whenever it changes:

    Sphere       LOD 0 -> 1   (12.3 radii)

Distance LOD only runs in the shader/core pipeline (the NURBS legacy path has no
LOD), so this demo forces the core profile + GLFW backend.  Set
``OPENGLCONTEXT_LOD=off`` before running to freeze every object at full detail
for comparison.

Run:  python tests/lod_demo.py
"""
import math
import os

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGL.GL import (
    glPolygonMode, GL_FRONT_AND_BACK, GL_LINE, GL_FILL,
)
from OpenGLContext import testingcontext
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph import tessellationlod
from OpenGLContext.events import systemtime

BaseContext = testingcontext.getInteractive('glfw')


def _nurbs_control_points():
    """A gently bumpy 4x4 control grid centred on the origin (~3 units wide)."""
    pts = []
    for j in range(4):
        for i in range(4):
            x = (i - 1.5) * 1.0
            z = (j - 1.5) * 1.0
            y = 0.6 * math.sin(i * 1.1) * math.cos(j * 1.1)
            pts.append((x, y, z))
    return pts


_KNOT = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


def _shape(geometry, x, diffuse):
    return basenodes.Transform(
        translation=(x, 0, 0),
        children=[basenodes.Shape(
            geometry=geometry,
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=diffuse, specularColor=(1, 1, 1), shininess=0.6,
            )),
        )],
    )


class TestContext(BaseContext):
    def OnInit(self):
        # (label, geometry, x-position, local bounding radius, colour). The radius
        # is what the LOD metric normalizes distance by (see each node's
        # _lod_bounding_radius / _lod_bounding_sphere).
        self.objects = [
            ('Teapot', basenodes.Teapot(size=1.4), -8.0, 1.9 * 1.4, (0.80, 0.35, 0.25)),
            ('Sphere', basenodes.Sphere(radius=1.6), -4.0, 1.6, (0.30, 0.60, 0.35)),
            ('Cone', basenodes.Cone(bottomRadius=1.4, height=3.0), 0.0,
             max(1.4, 1.5), (0.30, 0.45, 0.75)),
            ('Cylinder', basenodes.Cylinder(radius=1.3, height=3.0), 4.0,
             max(1.3, 1.5), (0.70, 0.65, 0.30)),
            ('NURBS', basenodes.NurbsSurface(
                controlPoint=_nurbs_control_points(), uDimension=4, vDimension=4,
                uKnot=_KNOT, vKnot=_KNOT), 8.0, 2.1, (0.60, 0.35, 0.65)),
        ]
        self.sg = basenodes.sceneGraph(children=[
            basenodes.DirectionalLight(
                direction=(0.3, -0.6, -1), color=(1, 1, 1), intensity=1.0),
            basenodes.Background(skyColor=[(0.05, 0.05, 0.08)]),
            *[_shape(geom, x, col) for (_, geom, x, _r, col) in self.objects],
        ])
        self._levels = {}
        # Camera dolly range along +Z, in world units. Near end keeps the closest
        # object at full detail; far end drives everything to the coarsest level.
        self._near, self._far = 16.0, 190.0
        self._period = 16.0     # seconds for a full out-and-back sweep
        self._start = systemtime.systemTime()
        self.getViewPlatform().setPosition((0, 1.5, self._near))
        self._print_legend()

    def _print_legend(self):
        print("\nDistance-LOD demo -- wireframe density drops as objects recede.",
              flush=True)
        print("LOD thresholds (object-radii):", tessellationlod.DEFAULT_THRESHOLDS,
              "  (level 0 = finest)")
        if not tessellationlod.lod_enabled():
            print("OPENGLCONTEXT_LOD is OFF -- everything stays at full detail.")
        print("Objects (left to right):",
              ", ".join(label for label, *_ in self.objects), "\n", flush=True)

    def OnIdle(self, *args):
        # Smooth cosine dolly between near and far; report level changes.
        phase = ((systemtime.systemTime() - self._start) % self._period) / self._period
        cam_z = self._near + (self._far - self._near) * 0.5 * (1 - math.cos(2 * math.pi * phase))
        self.getViewPlatform().setPosition((0, 1.5, cam_z))
        self._report_levels(cam_z)
        self.triggerRedraw(1)
        return 1

    def _report_levels(self, cam_z):
        for label, _geom, x, radius, _col in self.objects:
            # Straight-line camera distance to the object centre, in radii.
            dist = math.sqrt((cam_z - 0.0) ** 2 + 1.5 ** 2 + x ** 2)
            level = tessellationlod.level_from_distance(dist / radius)
            if self._levels.get(label) != level:
                prev = self._levels.get(label)
                arrow = f"{prev} -> {level}" if prev is not None else f"{level}"
                print(f"  {label:<10} LOD {arrow:<8} ({dist / radius:.1f} radii)",
                      flush=True)
                self._levels[label] = level

    def Render(self, mode):
        # Wireframe so the tessellation -- and its LOD changes -- are visible.
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        try:
            BaseContext.Render(self, mode)
        finally:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
