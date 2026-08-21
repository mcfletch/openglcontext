#! /usr/bin/env python
'''=Roads (a centreline swept through a cross-section)=

[roads_demo.py-screen-0001.png Screenshot]

452 metres of two-lane road from `OpenGLContext.scenegraph.road`, built by
sweeping a `RoadProfile` -- the shape of a cut across the road -- along a
centreline that bends left, bends right, and rides the land down into a hollow
and up over a rise.

The cut is what the picture is of. Measured out from the crown: 7.4 m of
carriageway carrying its edge lines and its dashed centre line, a 1.5 m gravel
shoulder 0.10 m below the carriageway's edge, and a 3 m grass verge falling a
further 1.2 m to meet the ground. One image spans all three bands, so no seam
falls between them and the markings arrive with the surface rather than as
decals on top of it.

The land is a height function. The centreline is an alignment -- straights and
radii, walked out over the land and lifted by the depth of the verge, so the
verge lands on the ground instead of in it. `road_mesh` sweeps the profile
along it and reports what it made:

    452.3 m of road at 4 m spacing: 115 points, 805 vertices, 1368 triangles

Press `d` to re-sample the centreline at 30 m instead of 4 m: the same road
comes to 119 vertices, and re-sampling is the whole of a road's level of
detail. Press `w` to wet the tarmac to 0.85, which darkens the surface to 62%
of its dry tint and drops its roughness from 0.72 to 0.21. A surface that
smooth takes its reflection from an environment probe, and this scene carries
none, so what shows here is the darkening. The usual keys walk around.
'''
import math
import os

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
os.environ.setdefault('OPENGLCONTEXT_IBL', 'off')

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, DirectionalLight, Fog, Shape, Transform,
    sceneGraph,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.road import (
    RoadProfile, estimate_normals, resample_polyline, road_mesh,
    tarmac_material,
)

BaseContext = testingcontext.getInteractive('glfw')

#: The cut across the road: the stock two-lane section, 7.4 m of carriageway
#: between a 1.5 m shoulder and a 3 m verge each side.
PROFILE = RoadProfile()

#: The alignment, as (length, radius) in metres. A straight has radius zero, a
#: positive radius turns left and a negative one right.
ALIGNMENT = ((45.0, 0.0), (150.0, 210.0), (185.0, -160.0), (70.0, 0.0))

#: Where the centreline starts, on the +Z side of the camera, so the road runs
#: out from under the viewer rather than beginning in front of them.
START = 55.0

#: How far the crown of the road rides above the land it crosses, in metres:
#: the whole depth of the section, less a little, so the foot of the verge is
#: bedded into the ground rather than meeting it along a coplanar seam.
RIDE = -float(PROFILE.section()[0, 1]) - 0.05

#: The ground, as a square of this half-extent in metres and this many cells.
GROUND, GROUND_CELLS = 1500.0, 300

#: Centreline spacing in metres at full detail and at the coarsest level a
#: distant tile would carry.
FINE, COARSE = 4.0, 30.0

#: How wet the `w` key makes the road, on the 0-to-1 scale
#: :func:`~OpenGLContext.scenegraph.road.tarmac_material` takes.
WET = 0.85


def ground_height(x, z):
    """The land the road crosses, in metres: a hollow, a rise beyond it, and a
    slow swell running across both."""
    return (-8.0 * np.exp(-((z + 95.0) / 55.0) ** 2)
            + 15.0 * np.exp(-((z + 265.0) / 75.0) ** 2)
            + 2.0 * np.sin(x * 0.017) + 0.04 * x)


def route(step=2.5):
    """The alignment walked out and dropped onto the land.

    Heading zero runs along -Z, and each element bends it by its own length
    over its own radius, which is how a road is set out on the ground.
    """
    x, z, heading = 0.0, START, 0.0
    across, along = [x], [z]
    for length, radius in ALIGNMENT:
        for _ in range(int(round(length / step))):
            if radius:
                heading += step / radius
            x -= step * math.sin(heading)
            z -= step * math.cos(heading)
            across.append(x)
            along.append(z)
    across, along = np.array(across), np.array(along)
    return np.stack([across, ground_height(across, along) + RIDE, along],
                    axis=-1)


def ground_mesh():
    """The land itself, as a grid of the same height function."""
    axis = np.linspace(-GROUND, GROUND, GROUND_CELLS + 1)
    x, z = np.meshgrid(axis, axis - GROUND * 0.6, indexing='ij')
    positions = np.stack([x, ground_height(x, z), z],
                         axis=-1).reshape(-1, 3).astype('f')
    row = np.arange(GROUND_CELLS)[:, None] * (GROUND_CELLS + 1)
    column = np.arange(GROUND_CELLS)[None, :]
    a = (row + column).ravel()
    b, c, d = a + 1, a + GROUND_CELLS + 1, a + GROUND_CELLS + 2
    indices = np.stack([a, b, c, b, d, c], axis=-1).ravel().astype(np.uint32)
    # Vertex colours mottle the grass, so a slope is a change in the land
    # rather than one flat sheet of green.
    patch = (0.82 + 0.18 * np.sin(x * 0.13) * np.cos(z * 0.11)
             + 0.10 * np.sin(x * 0.031 + z * 0.027)).reshape(-1)
    colors = np.ones((len(positions), 4), dtype='f')
    colors[:, :3] = patch[:, None]
    return PBRMesh(positions=positions,
                   normals=estimate_normals(positions, indices),
                   indices=indices, colors=colors,
                   material=PBRMaterial(baseColor=(0.20, 0.24, 0.11),
                                        metallic=0.0, roughness=0.95))


def shape(mesh):
    """A mesh under a Shape, wearing the material it was built with."""
    return Shape(geometry=mesh, appearance=Appearance(material=mesh.material))


#: Over the start of the road and high enough to see it dip and rise again.
VIEWPOINT = (3.0, float(ground_height(0.0, START)) + RIDE + 16.0, START - 6.0)


class TestContext(BaseContext):
    """One road, one piece of ground, and a sun over both."""

    initialPosition = VIEWPOINT
    initialOrientation = (-1, 0, 0, 0.26)   # pitch down onto the road

    def OnInit(self):
        self.line = route()
        self.spacing = FINE
        self.wetness = 0.0
        self.road = shape(self.build())
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.24, 0.42, 0.78), (0.44, 0.62, 0.88),
                                 (0.68, 0.79, 0.92), (0.82, 0.87, 0.92)],
                       skyAngle=[0.85, 1.25, 1.5708]),
            # Haze, so the ground fades into the sky at its far edge rather
            # than ending against it. The colour is the sky's own horizon
            # band in linear light, which is what the shader mixes towards.
            Fog(color=(0.625, 0.724, 0.824), visibilityRange=1200.0,
                fogType='LINEAR'),
            DirectionalLight(direction=(-0.45, -0.80, -0.40), intensity=1.15,
                             color=(1.0, 0.97, 0.90)),
            Transform(children=[shape(ground_mesh()), self.road]),
        ])
        # PBR ambient is image-based, and this scene carries no probe, so the
        # fill is kept low and the sun does the lighting.
        self.gltf_scene_ambient = 0.16
        self.addEventHandler('keypress', name='w', function=self.OnWetness)
        self.addEventHandler('keypress', name='d', function=self.OnDetail)
        print(__doc__)
        self.report()

    def build(self):
        """The road at the current spacing and wetness."""
        return road_mesh(self.line, PROFILE, spacing=self.spacing,
                         material=tarmac_material(wetness=self.wetness))

    def rebuild(self):
        """Swap in a road built to the settings as they now stand."""
        mesh = self.build()
        self.road.geometry = mesh
        self.road.appearance.material = mesh.material
        self.triggerRedraw(1)

    def OnWetness(self, event):
        self.wetness = 0.0 if self.wetness else WET
        self.rebuild()
        print('wetness %.2f' % (self.wetness,))

    def OnDetail(self, event):
        self.spacing = COARSE if self.spacing == FINE else FINE
        self.rebuild()
        self.report()

    def report(self):
        """What the sweep produced, at the spacing it was swept at."""
        written = resample_polyline(self.line, self.spacing)
        run = float(np.linalg.norm(np.diff(written, axis=0), axis=1).sum())
        mesh = self.road.geometry
        print('%.1f m of road at %.0f m spacing: %d points, %d vertices, '
              '%d triangles'
              % (run, self.spacing, len(written), len(mesh.positions),
                 len(mesh.indices) // 3))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
