#! /usr/bin/env python
'''=Water: three styles, a river, and being under it=

[water_demo.py-screen-0001.png Screenshot]

Three pools cut in a sand flat, one for each of the named `WaterStyle`
settings in `OpenGLContext.scenegraph.water`, so what each one does to a
surface can be read off against the other two:

 * *left, `STILL`* -- a pond. No displacement at all; the ripple is in
   the normals, which is what puts a glitter on it without moving it.
 * *middle, `FLOWING`* -- a river. `amplitude` 0.09 m, crests 4.5 m apart
   travelling at 1.6 m/s, with the surface drifting the same way. Over
   one pool the field spans 0.34 m trough to crest.
 * *right, `CHOPPY`* -- weather. `amplitude` 0.42 m, and the three
   crossing trains sum to a surface spanning 1.58 m over one pool --
   enough shape to move a shoreline.

Each pool carries a grid of floats sitting **on** the surface, put there
by `wave_height(style, x, z, when)` once a frame: the left grid is dead
flat, the middle one gently uneven, the right one thrown well about. That
is the same call a boat's waterline or a buoyancy solver makes, and it
gives the wave field a scale the eye can measure.

Beyond the pools a `water_ribbon` sweeps a river along a bending course
that loses height from end to end -- the thing a flat sheet at one `level`
cannot do.

Behind the river is a `LAKE`: 180 m of open water, which is where how
finely a sheet is meshed stops being a detail. It is meshed by
`mesh_across`, from its own wavelength. Press `d` to mesh it the way a
sheet used to be, at nine vertices whatever its size, and the two are
printed as they are measured against the wave field itself:

    lake 180 m across, meshed from its wavelength: 33 vertices, 1.6 samples
        per wave, keeps 98% of its swell
    lake 180 m across, meshed the old way:          9 vertices, 0.4 samples
        per wave, keeps 47% of its swell

Nine vertices across 180 m is a vertex every 22 m against a 9 m wave --
less than one sample per wave, under the Nyquist limit, where a wave does
not merely flatten but comes back as a longer one that was never in the
water.

Every sheet is built with `on_gpu=True`: uploaded once, then moved by the
four `wave_time` writes in `OnIdle`. Nothing is re-meshed and nothing is
re-uploaded to make the water move.

Each pool is also a `Volume`, and the camera position goes to `submerge`
every frame. Press `v` to drop the camera into the middle pool and back:
the fog closes the view in to water's 9 m visibility, whatever audio engine
the context has is muffled, and the medium found is printed as it changes:

    medium under the camera: water
    medium under the camera: air

Press `h` to print the surface height at each pool's centre at this
moment, and the usual keys to walk around.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
# What this demo is about is the shape of a surface, and a shadow map costs a
# whole depth pass over a scene that has nothing to cast one onto.
os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '0')

import time

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, DirectionalLight, Shape, Sphere, Transform, sceneGraph,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.water import (
    CHOPPY, FLOWING, LAKE, STILL, Volume, Volumes, medium_fog, submerge,
    mesh_across, water_ribbon, water_surface, wave_height,
)
from OpenGLContext.viewer.environment import sky_background

BaseContext = testingcontext.getInteractive('glfw')

#: Which style goes where along X, as (label, style, x0, x1). Equal footprints
#: and equal gaps, so a difference between two of them is the water rather than
#: the pool it is in.
SHEETS = [
    ('STILL', STILL, -20.0, -8.0),
    ('FLOWING', FLOWING, -6.0, 6.0),
    ('CHOPPY', CHOPPY, 8.0, 20.0),
]

#: How far each pool runs in Z, the level the water sits at, and where the bed
#: under it is.
Z0, Z1, LEVEL, BED = -26.0, 6.0, 0.0, -1.2

#: Vertices along each side of a sheet. A pool is 12 m by 32 m, so the coarser
#: axis is meshed every half metre and CHOPPY's 7 m crests get fourteen vertices
#: apiece -- well clear of the point where a sheet is too coarse for its wave.
RESOLUTION = 65

#: The lake beyond the river: 180 m of open water, which is the size at which
#: how finely a sheet is meshed stops being a detail. Its wave is 9 m long, so
#: the nine-vertices-across a sheet used to get puts one vertex every 22 m --
#: less than one sample per wave, which is under the Nyquist limit, and a wave
#: sampled under Nyquist does not merely flatten: it comes back as a different,
#: longer wave that was never in the water.
LAKE_X0, LAKE_X1, LAKE_Z0, LAKE_Z1 = -90.0, 90.0, -104.0, -48.0

#: What a sheet used to be meshed at, whatever its size. Kept so `d` can put it
#: back and the difference can be seen rather than described.
FIXED_RESOLUTION = 9

#: How far down the volumes go. A body that has gone through the bed is still
#: in the water as far as the view is concerned.
DEPTH = 8.0

#: Which way the sunlight travels: over the viewer's shoulder and across, so
#: the near face of every wave is lit and the far face is not, which is what
#: makes a crest read as a crest.
SUN = (0.35, -0.45, -0.82)

#: The dry ground, and the bed laid in each pool: sand where a body of water
#: is shallow enough to see the bottom of, silt where it is not.
SAND = PBRMaterial(baseColor=(0.42, 0.36, 0.25), metallic=0.0, roughness=0.9)
BOTTOM = PBRMaterial(baseColor=(0.09, 0.21, 0.23), metallic=0.0, roughness=0.9)

#: What a float is made of: matt, so where it sits is read off its position
#: rather than off a highlight that moves with the camera.
CORK = PBRMaterial(baseColor=(0.86, 0.33, 0.12), metallic=0.0, roughness=0.8)

#: How the floats are laid out in each pool, across and along, and how big one
#: is. A grid rather than a line, so the surface is sampled as a field.
ACROSS, ALONG, FLOAT_RADIUS = 3, 8, 0.35

#: Where the sand lies, as (x0, x1, z0, z1) footprints on top of the ground:
#: the banks between and outside the pools, the near shore, and the two either
#: side of the river. What is left bare is where water goes.
SHORE = [
    (-90.0, -20.0, Z0, Z1), (-8.0, -6.0, Z0, Z1),
    (6.0, 8.0, Z0, Z1), (20.0, 90.0, Z0, Z1),
    (-90.0, 90.0, -32.0, Z0),
    # Beyond the river, with the lake's footprint left out of it.
    (-90.0, 90.0, -48.0, -44.0),
    (-90.0, LAKE_X0, LAKE_Z0, LAKE_Z1), (LAKE_X1, 90.0, LAKE_Z0, LAKE_Z1),
    (-90.0, 90.0, -140.0, LAKE_Z0),
    (-90.0, 90.0, Z1, 140.0),
]

#: A narrower lens than the default 60 degrees, in radians: the three pools and
#: the river are 40 m of scene, and a wide angle spends most of the frame on the
#: sand around them.
FIELD_OF_VIEW = 0.60

#: Where the camera watches from, and where `v` puts it: in the middle pool,
#: under the surface and clear of the bed.
OVERLOOK = (0.0, 8.0, 22.0)
UNDERWATER = (2.0, -0.55, -2.0)


def _river_course():
    """A bending course that loses height from left to right.

    Points in world metres, which is what `water_ribbon` sweeps a surface
    along: the bend is in plan and the fall is in Y.
    """
    x = np.linspace(-70.0, 70.0, 90)
    z = -38.0 + 2.5 * np.sin(x / 16.0)
    y = np.linspace(0.0, -0.7, len(x))
    return np.stack([x, y, z], axis=-1)


def _slab(x0, x1, z0, z1, top, thickness, material):
    """A box filling a footprint, with its upper face at ``top``."""
    return Transform(
        translation=((x0 + x1) / 2.0, top - thickness / 2.0, (z0 + z1) / 2.0),
        children=[Shape(geometry=Box(size=(x1 - x0, thickness, z1 - z0)),
                        appearance=Appearance(material=material))])


class TestContext(BaseContext):
    """Three pools, a river, and a camera that can go under one of them."""

    initialPosition = OVERLOOK
    initialOrientation = (1, 0, 0, -0.26)

    def OnInit(self):
        BaseContext.OnInit(self)
        #: The water meshes, whose wave_time is written once a frame.
        self.meshes = []
        #: (style, x, z, transform) for each float, so OnIdle can put it back
        #: on the surface wherever the surface has got to.
        self.floats = []
        children = [
            sky_background(),
            DirectionalLight(direction=SUN, intensity=2.2,
                             color=(1.0, 0.95, 0.86)),
            # A dim fill from the other side, so the dry ground is not two
            # values -- lit and black -- where the sun grazes it.
            DirectionalLight(direction=(-0.5, -0.55, 0.6), intensity=0.45,
                             color=(0.62, 0.74, 0.95)),
            # The ground, under everything, with the dry sand laid on top of
            # it: the pools and the river's channel are the gaps left in it.
            _slab(-90.0, 90.0, -90.0, 90.0, BED, 6.0, SAND),
        ]
        children.extend(_slab(x0, x1, z0, z1, LEVEL + 0.3, 6.0, SAND)
                        for x0, x1, z0, z1 in SHORE)

        ball = Sphere(radius=FLOAT_RADIUS)
        for label, style, x0, x1 in SHEETS:
            sheet = water_surface(x0, x1, Z0, Z1, level=LEVEL,
                                  resolution=RESOLUTION, style=style,
                                  on_gpu=True)
            self.meshes.append(sheet)
            # The bed of this pool, silt rather than the sand around it.
            children.append(_slab(x0, x1, Z0, Z1, BED, 0.3, BOTTOM))
            children.append(Shape(geometry=sheet, appearance=Appearance(
                material=sheet.material)))
            children.extend(self._floats(style, x0, x1, ball))
            print('%-8s amplitude %.2f m  wavelength %.1f m  speed %.1f m/s'
                  % (label, style.amplitude, style.wavelength, style.speed))

        # The lake, meshed from its own wavelength. Its Shape is kept so `d`
        # can swap the geometry for one meshed the old fixed way.
        self._lakeShape = Shape(geometry=None, appearance=None)
        self._lakeFine = True
        children.append(_slab(LAKE_X0, LAKE_X1, LAKE_Z0, LAKE_Z1, BED,
                              0.3, BOTTOM))
        children.append(self._lakeShape)
        self._buildLake()

        ribbon = water_ribbon(_river_course(), 9.0, style=FLOWING, on_gpu=True)
        self.meshes.append(ribbon)
        children.append(Shape(geometry=ribbon, appearance=Appearance(
            material=ribbon.material)))

        # One fog node, bound into the scene once; submerge writes its fields
        # as the camera goes in and out of the water.
        self.fog = medium_fog()
        children.append(self.fog)
        self.volumes = Volumes([
            Volume.below(minimum=(x0, Z0), maximum=(x1, Z1),
                         level=LEVEL, depth=DEPTH)
            for _label, _style, x0, x1 in SHEETS
        ])
        self.sg = sceneGraph(children=children)

        self.getViewPlatform().setFrustum(fieldOfView=FIELD_OF_VIEW)
        self._start = time.time()
        #: The last medium printed, so an unchanged frame stays quiet.
        self._medium = None
        self._under = False
        self.addEventHandler('keypress', name='d', function=self.OnDensity)
        self.addEventHandler('keypress', name='v', function=self.OnDive)
        self.addEventHandler('keypress', name='h', function=self.OnHeights)
        print(__doc__)

    def _floats(self, style, x0, x1, ball):
        """A grid of floats over one pool, riding its surface.

        One geometry node shared by every float, so the whole grid collapses
        into a single instanced draw.
        """
        nodes = []
        for x in np.linspace(x0 + 2.0, x1 - 2.0, ACROSS):
            for z in np.linspace(Z0 + 3.0, Z1 - 3.0, ALONG):
                transform = Transform(children=[Shape(
                    geometry=ball, appearance=Appearance(material=CORK))])
                self.floats.append((style, float(x), float(z), transform))
                nodes.append(transform)
        return nodes

    def _buildLake(self):
        """Mesh the lake, and say what that meshing keeps of its wave.

        The carried fraction is measured rather than claimed: the lake's own
        wave field is sampled finely enough to be the answer, then again at the
        density the sheet is actually meshed at.
        """
        side = LAKE_X1 - LAKE_X0
        across = (mesh_across(side, LAKE) if self._lakeFine
                  else FIXED_RESOLUTION)
        sheet = water_surface(LAKE_X0, LAKE_X1, LAKE_Z0, LAKE_Z1, level=LEVEL,
                              resolution=across, style=LAKE, on_gpu=True)
        # Swap it in under the Shape already in the scene, and take the sheet
        # it replaces out of the list OnIdle writes wave_time to.
        old = self._lakeShape.geometry
        self.meshes = [m for m in self.meshes if m is not old]
        self._lakeShape.geometry = sheet
        self._lakeShape.appearance = Appearance(material=sheet.material)
        self.meshes.append(sheet)
        self.triggerRedraw(1)

        spacing = side / max(across - 1, 1)
        fine = np.linspace(LAKE_X0, LAKE_X1, 400)
        true = wave_height(LAKE, *np.meshgrid(fine, fine), 0.0)
        coarse = np.linspace(LAKE_X0, LAKE_X1, across)
        got = wave_height(LAKE, *np.meshgrid(coarse, coarse), 0.0)
        span = float(true.max() - true.min())
        print('lake %.0f m across, meshed %-20s %2d vertices, %.1f samples per '
              'wave, keeps %.0f%% of its swell'
              % (side, 'from its wavelength:' if self._lakeFine else 'the old way:',
                 across, LAKE.wavelength / spacing,
                 100.0 * float(got.max() - got.min()) / max(span, 1e-9)))

    def OnDensity(self, event=None):
        """Mesh the lake the other way, so the difference is on the screen."""
        self._lakeFine = not self._lakeFine
        self._buildLake()

    def OnDive(self, event):
        """Put the camera into the middle pool, or back on the bank."""
        self._under = not self._under
        platform = self.getViewPlatform()
        platform.setPosition(UNDERWATER if self._under else OVERLOOK)
        platform.setOrientation(self.initialOrientation)
        self.triggerRedraw(1)

    def OnHeights(self, event=None):
        """What the surface is doing, at this moment, at each pool's centre."""
        when = time.time() - self._start
        for label, style, x0, x1 in SHEETS:
            height = wave_height(style, (x0 + x1) / 2.0, 0.0, when)
            print('  %-8s surface at %+.3f m (t=%.2fs)'
                  % (label, float(height), when))

    def OnIdle(self, event=None):
        when = time.time() - self._start
        # The whole per-frame cost of moving four bodies of water: one uniform
        # each. The meshes were uploaded in OnInit and are not touched again.
        for mesh in self.meshes:
            mesh.wave_time = when
        for style, x, z, transform in self.floats:
            transform.translation = (x, float(wave_height(style, x, z, when)), z)
        self._report(submerge(self, self.volumes,
                              self.getViewPlatform().position))
        self.triggerRedraw(1)
        return 1

    def _report(self, name):
        if name != self._medium:
            self._medium = name
            print('medium under the camera: %s' % (name or 'air',))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
