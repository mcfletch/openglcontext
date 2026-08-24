#! /usr/bin/env python
'''=Extrusion Parameter Gallery=

[extrusions_gallery.py-screen-0001.png Screenshot]

One figure per parameter, each showing what that parameter does across a
sweep of its values. These are what the documentation's figures are
captured from -- the point being that you can *see* what a setting does
rather than having to try it. Each figure's panels are named in
``FIGURES``, in the order they appear: left to right, top to bottom.

Run it with a figure name to see one::

    python tests/extrusions_gallery.py lathe
    python tests/extrusions_gallery.py --list

With no name it shows the whole set of shapes, which is the same scene as
`extrusions_shapes.py`.
'''
import sys
from math import pi

import numpy as np

from opengl_extrusions import (
    catmull_rom, circle, rectangle, rounded_rectangle, star,
)

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import (
    Appearance, DirectionalLight, Material, PixelTexture, PointLight, PolyCone,
    PolyCylinder, Shape, Transform, Viewpoint, sceneGraph,
)
from OpenGLContext.scenegraph.extrusions import Extrusion, Lathe, Screw, Spiral

#: A square section for the rotational sweeps: (out from the axis, up).
SECTION = [(0.0, -0.11), (0.22, -0.11), (0.22, 0.11), (0.0, 0.11)]

#: A right angle, for anything about corners.
CORNER = [(-0.85, -0.85, 0.0), (0.0, -0.85, 0.0), (0.0, 0.85, 0.0)]

GOLD = (0.85, 0.62, 0.28)
BLUE = (0.38, 0.68, 0.88)
GREEN = (0.45, 0.78, 0.48)
PLUM = (0.78, 0.52, 0.85)


def panel(label, geometry, colour=GOLD, tilt=None, scale=1.0, texture=None):
    """One labelled cell of a figure."""
    return {'label': label, 'geometry': geometry, 'colour': colour,
            'tilt': tilt, 'scale': scale, 'texture': texture}


def checker(squares=8, size=64):
    """A black-and-white checkerboard, so a texture mapping can be seen.

    Built here rather than loaded, so the figures need no asset beside them.
    VRML's SFImage is width, height, components, then one packed integer per
    pixel, top row first.
    """
    pixels = []
    for row in range(size):
        for column in range(size):
            dark = ((row * squares // size) + (column * squares // size)) % 2
            value = 0x202830 if dark else 0xF0F0E8
            pixels.append(value)
    return PixelTexture(image=[size, size, 3] + pixels)


# -- the figures ----------------------------------------------------------

def figure_texture_modes():
    """Every generated texture mode, on one tube, under a checkerboard."""
    from opengl_extrusions.texcoords import GENERATED_MODES
    path = [(0.0, -0.85, 0.0), (0.0, 0.85, 0.0)]
    tilt = (1, 0, 0, -0.32)
    board = checker()
    return [panel(mode.replace('_', ' '),
                  PolyCylinder(path=path, radius=0.42, sides=24, texture=mode,
                               caps=True, up=(0, 0, 1)),
                  GOLD, tilt, texture=board)
            for mode in GENERATED_MODES]


def figure_texture_parameter():
    """The two parameter modes, and what they do on each kind of sweep.

    Every panel is the same checkerboard, so where the squares stretch is where
    the mapping stretches.
    """
    board = checker()
    straight = [(0.0, -0.85, 0.0), (0.0, 0.85, 0.0)]
    bend = [(-0.7, -0.7, 0.0), (0.0, -0.7, 0.0), (0.0, 0.7, 0.0)]
    tilt = (1, 0, 0, -0.32)
    return [
        panel('tube, normalized',
              PolyCylinder(path=straight, radius=0.42, sides=24,
                           texture='normalized', up=(0, 0, 1)), GOLD, tilt, texture=board),
        panel('tube, arc_length',
              PolyCylinder(path=straight, radius=0.42, sides=24,
                           texture='arc_length', up=(0, 0, 1)), GOLD, tilt, texture=board),
        panel('elbow, normalized',
              PolyCylinder(path=bend, radius=0.34, sides=24,
                           texture='normalized'), GOLD, None, texture=board),
        panel('lathe, normalized',
              Lathe(contour=SECTION, startRadius=0.6, sides=40,
                    texture='normalized'), BLUE, (1, 0, 0, -1.05), texture=board),
        panel('screw, arc_length',
              Screw(contour=rectangle(0.36, 0.36), startZ=-0.85, endZ=0.85,
                    totalAngle=2 * pi, texture='arc_length'), BLUE,
              (1, 0, 0, -1.35), texture=board),
        panel('VRML97 Extrusion',
              Extrusion(crossSection=[(0.4, 0.4), (0.4, -0.4), (-0.4, -0.4),
                                      (-0.4, 0.4), (0.4, 0.4)],
                        spine=[(0, -0.8, 0), (0, 0.8, 0)]), BLUE, tilt,
              texture=board),
    ]


def figure_texture_caps():
    """How an end cap is mapped, and what refining it does to that mapping."""
    board = checker()
    short = [(0.0, -0.3, 0.0), (0.0, 0.3, 0.0)]
    flat = (1, 0, 0, -1.35)          # looking down onto the cap
    return [
        panel('round cap',
              PolyCylinder(path=short, radius=0.6, sides=32, up=(0, 0, 1)),
              GOLD, flat, texture=board),
        panel('square cap',
              _capped(rectangle(1.0, 1.0), short), GOLD, flat, texture=board),
        panel('star cap',
              _capped(star(6, 0.6, 0.26), short), GOLD, flat, texture=board),
        panel('cap with a hole',
              _capped([circle(0.6, 32), circle(0.3, 32)[::-1]], short), BLUE,
              flat, texture=board),
        panel('cap refined, area 0.01',
              _capped(star(6, 0.6, 0.26), short, cap_max_area=0.01), BLUE, flat,
              texture=board),
        panel('cap refined, angle 25',
              _capped(star(6, 0.6, 0.26), short, cap_min_angle=25.0), BLUE, flat,
              texture=board),
    ]


def _capped(contour, path, **named):
    """A short capped extrusion, for looking at its end face."""
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    mesh = extrude(contour, path, caps=True, up=(0, 0, 1), **named)
    return mesh_from_primitive(mesh.merged().primitives[0])


def figure_curve_sampling():
    """What the sampling parameter does, on each kind of geometry.

    Top: one spline swept at three chord-error tolerances -- the facets are the
    samples. Bottom: the same question for the parameters that stand in for a
    tolerance elsewhere -- a lathe's facets per turn, a screw's rings, and a
    circle's sides.
    """
    waypoints = [(-0.8, -0.8, 0.0), (-0.2, 0.7, 0.3), (0.4, -0.7, -0.3),
                 (0.9, 0.7, 0.0)]
    return [
        panel('tolerance 0.08',
              PolyCylinder(path=catmull_rom(waypoints, tolerance=0.08),
                           radius=0.13, sides=16, frames='rmf'), GOLD),
        panel('tolerance 0.01',
              PolyCylinder(path=catmull_rom(waypoints, tolerance=0.01),
                           radius=0.13, sides=16, frames='rmf'), GOLD),
        panel('tolerance 0.0005',
              PolyCylinder(path=catmull_rom(waypoints, tolerance=0.0005),
                           radius=0.13, sides=16, frames='rmf'), GOLD),
        panel('lathe sides 8 / 40',
              Lathe(contour=SECTION, startRadius=0.6, sides=8, normals='facet'),
              BLUE, (1, 0, 0, -1.05)),
        panel('screw steps 4 / 40',
              Screw(contour=rectangle(0.34, 0.34), startZ=-0.8, endZ=0.8,
                    totalAngle=2 * pi, steps=4), BLUE, (1, 0, 0, -1.35)),
        panel('contour sides 5 / 32',
              PolyCylinder(path=[(0.0, -0.8, 0.0), (0.0, 0.8, 0.0)], radius=0.42,
                           sides=5, up=(0, 0, 1), normals='facet'), BLUE,
              (1, 0, 0, -0.35)),
    ]


def figure_lathe():
    """What each of a lathe's parameters does."""
    tilt = (1, 0, 0, -1.05)
    return [
        panel('totalAngle pi', Lathe(contour=SECTION, startRadius=0.62,
                                     totalAngle=pi, sides=32), GOLD, tilt),
        panel('totalAngle 2pi', Lathe(contour=SECTION, startRadius=0.62,
                                      totalAngle=2 * pi, sides=32), GOLD, tilt),
        panel('deltaZ 0.6', Lathe(contour=SECTION, startRadius=0.62, deltaZ=0.6,
                                  totalAngle=4 * pi, sides=32), GOLD, tilt),
        panel('deltaRadius 0.4', Lathe(contour=SECTION, startRadius=0.35,
                                       deltaRadius=0.4, totalAngle=4 * pi,
                                       sides=32), BLUE, tilt),
        panel('sides 6', Lathe(contour=SECTION, startRadius=0.62, sides=6,
                               normals='facet'), BLUE, tilt),
        panel('sides 48', Lathe(contour=SECTION, startRadius=0.62, sides=48),
              BLUE, tilt),
    ]


def figure_spiral():
    """A lathe and a spiral of identical parameters, as the climb steepens."""
    tilt = (1, 0, 0, -1.05)
    out = []
    for rise, name in ((0.0, 'deltaZ 0'), (0.5, 'deltaZ 0.5'), (1.4, 'deltaZ 1.4')):
        out.append(panel('lathe, ' + name,
                         Lathe(contour=SECTION, startRadius=0.6, deltaZ=rise,
                               totalAngle=2 * pi, sides=32), GOLD, tilt))
    for rise, name in ((0.0, 'deltaZ 0'), (0.5, 'deltaZ 0.5'), (1.4, 'deltaZ 1.4')):
        out.append(panel('spiral, ' + name,
                         Spiral(contour=SECTION, startRadius=0.6, deltaZ=rise,
                                totalAngle=2 * pi, sides=32), GREEN, tilt))
    return out


def figure_screw():
    """Twist and length, the two things a screw has."""
    section = rectangle(0.34, 0.34)
    tilt = (1, 0, 0, -1.35)
    return [
        panel('totalAngle 0', Screw(contour=section, startZ=-0.8, endZ=0.8,
                                    totalAngle=0.0), GOLD, tilt),
        panel('totalAngle pi', Screw(contour=section, startZ=-0.8, endZ=0.8,
                                     totalAngle=pi), GOLD, tilt),
        panel('totalAngle 6pi', Screw(contour=section, startZ=-0.8, endZ=0.8,
                                      totalAngle=6 * pi), GOLD, tilt),
        panel('startZ/endZ -0.4..0.4', Screw(contour=section, startZ=-0.4,
                                             endZ=0.4, totalAngle=2 * pi), BLUE,
              tilt),
        panel('startZ/endZ -1.2..1.2', Screw(contour=section, startZ=-1.2,
                                             endZ=1.2, totalAngle=2 * pi), BLUE,
              tilt),
        panel('a 5-point star', Screw(contour=star(5, 0.42, 0.18), startZ=-0.9,
                                      endZ=0.9, totalAngle=2 * pi), BLUE, tilt),
    ]


def figure_polycone():
    """A radius given at every path point, and what profiles that allows."""
    straight = [(0.0, -0.9, 0.0), (0.0, -0.3, 0.0), (0.0, 0.3, 0.0), (0.0, 0.9, 0.0)]
    return [
        panel('constant (PolyCylinder)',
              PolyCylinder(path=straight, radius=0.3, sides=24), GOLD),
        panel('taper to nothing',
              PolyCone(path=straight, radii=[0.42, 0.28, 0.14, 0.0], sides=24), GOLD),
        panel('barrel',
              PolyCone(path=straight, radii=[0.16, 0.4, 0.4, 0.16], sides=24), GOLD),
        panel('waist',
              PolyCone(path=straight, radii=[0.4, 0.14, 0.14, 0.4], sides=24), BLUE),
        panel('stepped',
              PolyCone(path=straight, radii=[0.16, 0.16, 0.42, 0.42], sides=24), BLUE),
        panel('along a curve', _tapered_curve(), BLUE),
    ]


def figure_caps():
    """Which ends are closed, and what a contour with a hole does to a cap."""
    straight = [(0.0, -0.75, 0.0), (0.0, 0.75, 0.0)]
    tilt = (1, 0, 0, -0.55)
    ring = [circle(0.45, 28), circle(0.26, 28)[::-1]]
    return [
        panel('caps TRUE', PolyCylinder(path=straight, radius=0.42, sides=28,
                                        caps=True), GOLD, tilt),
        panel('caps FALSE', PolyCylinder(path=straight, radius=0.42, sides=28,
                                         caps=False), GOLD, tilt),
        panel('a hollow section', _hollow(ring, straight), BLUE, tilt),
        panel('closed_contour FALSE', _sheet(), GREEN, tilt),
        panel('cap_max_area 0.004', _refined_cap(straight, 0.004), PLUM, tilt),
        panel('cap_max_area 0.05', _refined_cap(straight, 0.05), PLUM, tilt),
    ]


def figure_contours():
    """The contour builders, swept the same way so only the outline differs."""
    straight = [(0.0, -0.7, 0.0), (0.0, 0.7, 0.0)]
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    shapes = [
        ('circle(sides=6)', circle(0.42, 6)),
        ('circle(sides=24)', circle(0.42, 24)),
        ('rectangle(0.7, 0.45)', rectangle(0.7, 0.45)),
        ('rounded_rectangle', rounded_rectangle(0.75, 0.5, 0.18, 8)),
        ('star(5)', star(5, 0.45, 0.19)),
        ('star(8, thin)', star(8, 0.45, 0.30)),
    ]
    out = []
    for index, (label, contour) in enumerate(shapes):
        mesh = extrude(contour, straight, normals='edge', up=(0, 0, 1))
        out.append(panel(label, mesh_from_primitive(mesh.merged().primitives[0]),
                         GOLD if index < 3 else BLUE, (1, 0, 0, -0.5)))
    return out


def figure_scale_twist():
    """Per-point scale and twist, which reshape a sweep without moving its path."""
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    straight = [(0.0, -0.8, 0.0), (0.0, -0.27, 0.0), (0.0, 0.27, 0.0),
                (0.0, 0.8, 0.0)]
    section = rectangle(0.5, 0.5)
    variants = [
        ('plain', {}),
        ('scale 1..0.3', {'scale': [1.0, 0.77, 0.53, 0.3]}),
        ('scale (x, y) apart', {'scale': [(1.0, 1.0), (1.4, 0.6), (0.6, 1.4),
                                          (1.0, 1.0)]}),
        ('twist to pi/2', {'twist': [0.0, pi / 6, pi / 3, pi / 2]}),
        ('twist and taper', {'scale': [1.0, 0.8, 0.6, 0.4],
                             'twist': [0.0, pi / 4, pi / 2, 3 * pi / 4]}),
        ('colour per point', {'color': [(1, 0.2, 0.2), (1, 0.9, 0.2),
                                        (0.2, 0.9, 0.4), (0.3, 0.5, 1.0)]}),
    ]
    out = []
    for index, (label, options) in enumerate(variants):
        mesh = extrude(section, straight, up=(0, 0, 1), **options)
        out.append(panel(label, mesh_from_primitive(mesh.merged().primitives[0]),
                         GOLD if index < 3 else BLUE, (1, 0, 0, -0.35)))
    return out


def _tapered_curve():
    """A polycone whose path bends and whose radius changes along it."""
    path = catmull_rom([(-0.55, -0.9, 0.0), (0.35, -0.1, 0.25), (-0.25, 0.9, 0.0)],
                       tolerance=2e-3)
    radii = np.linspace(0.34, 0.10, len(path))
    return PolyCone(path=path, radii=radii, sides=20)


def _hollow(rings, path):
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    mesh = extrude(rings, path, caps=True, up=(0, 0, 1))
    return mesh_from_primitive(mesh.merged().primitives[0])


def _sheet():
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    wave = np.column_stack([np.linspace(-0.5, 0.5, 9),
                            0.12 * np.sin(np.linspace(0, 3 * np.pi, 9))])
    mesh = extrude(wave, [(0.0, -0.75, 0.0), (0.0, 0.75, 0.0)],
                   closed_contour=False, caps=False, up=(0, 0, 1))
    return mesh_from_primitive(mesh.merged().primitives[0])


def _refined_cap(path, max_area):
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from opengl_extrusions import extrude
    mesh = extrude(star(6, 0.45, 0.2), path, caps=True, up=(0, 0, 1),
                   cap_max_area=max_area)
    return mesh_from_primitive(mesh.merged().primitives[0])


#: Every figure this gallery can draw.
FIGURES = {
    'texture_modes': figure_texture_modes,
    'texture_parameter': figure_texture_parameter,
    'texture_caps': figure_texture_caps,
    'curve_sampling': figure_curve_sampling,
    'lathe': figure_lathe,
    'spiral': figure_spiral,
    'screw': figure_screw,
    'polycone': figure_polycone,
    'caps': figure_caps,
    'contours': figure_contours,
    'scale_twist': figure_scale_twist,
}


def build_scene(panels, across=3, spacing=2.15, distance=7.4):
    """A labelled grid of panels, lit and pointed at the camera."""
    children = []
    rows = (len(panels) + across - 1) // across
    for index, cell in enumerate(panels):
        if cell['geometry'] is None:
            continue
        column, row = index % across, index // across
        x = (column - (across - 1) / 2.0) * spacing
        y = ((rows - 1) / 2.0 - row) * spacing
        look = Appearance(material=Material(
            diffuseColor=cell['colour'], ambientIntensity=0.35,
            # A low self-illumination floor, so a panel that happens to face
            # away from every light still shows its shape.
            emissiveColor=tuple(c * 0.24 for c in cell['colour']),
            shininess=0.55))
        if cell.get('texture') is not None:
            look.texture = cell['texture']
            look.material.diffuseColor = (1.0, 1.0, 1.0)
            look.material.emissiveColor = (0.12, 0.12, 0.12)
        shape = Shape(geometry=cell['geometry'], appearance=look)
        inner = [shape]
        if cell['tilt']:
            inner = [Transform(rotation=cell['tilt'], children=inner)]
        if cell['scale'] != 1.0:
            inner = [Transform(scale=(cell['scale'],) * 3, children=inner)]
        children.append(Transform(translation=(x, y, 0), children=inner))
    children.append(Viewpoint(position=(0, 0, distance)))
    children.append(PointLight(location=(3, 4, 8)))
    children.append(DirectionalLight(direction=(0, 0, -1), color=(0.42, 0.42, 0.45)))
    children.append(DirectionalLight(direction=(-0.4, -0.5, -0.75),
                                     color=(0.35, 0.35, 0.4)))
    return sceneGraph(children=children)


def describe(name):
    """The panel labels of a figure, in the order they are drawn."""
    return [cell['label'] for cell in FIGURES[name]()]


def chosen_figure():
    names = [a for a in sys.argv[1:] if not a.startswith('-')]
    if '--list' in sys.argv:
        for name in sorted(FIGURES):
            print('%-12s %s' % (name, ', '.join(describe(name))))
        raise SystemExit(0)
    if names and names[0] in FIGURES:
        return FIGURES[names[0]]()
    if names:
        raise SystemExit('unknown figure %r; try --list' % names[0])
    return figure_lathe()


#: Figures that need a wider grid than three across.
WIDE = {'texture_modes': (4, 2.0, 8.4)}


class TestContext(BaseContext):
    """One figure from the gallery, chosen on the command line."""

    def OnInit(self):
        names = [a for a in sys.argv[1:] if not a.startswith('-')]
        across, spacing, distance = WIDE.get(names[0] if names else '',
                                             (3, 2.15, 7.4))
        self.sg = build_scene(chosen_figure(), across, spacing, distance)


if __name__ == '__main__':
    TestContext.ContextMainLoop()
