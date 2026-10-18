#! /usr/bin/env python
"""CoordinateDeformer: NURBS surfaces moved through NURBS volumes, read from an X3D document.

    oglc-deformer [--directory DIR]

    g      show or hide the lattices

The document is written by :func:`prepare` as ``deformer.x3dv``, X3D in the
ClassicVRML encoding, with the marble, brass and sandstone maps its
`PhysicalMaterial` nodes name. `CoordinateDeformer` is the engine's own node,
in its `OpenGLContext` component. The document holds two:

- a marble column, a `NurbsPatchSurface` whose control points are the
  deformer's output, and whose lattice a `CoordinateInterpolator` moves, so
  the column bends, twists and swells;
- a brass capsule, another `NurbsPatchSurface`, which a `PositionInterpolator`
  carries, by the deformer's `inputTransform`, through a lattice with a
  narrow neck.

Each lattice is drawn as lines. docs/nurbs.rst describes the node.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['DOCUMENT', 'DeformerScene', 'lattice', 'main', 'prepare', 'world']

#: The name of the document :func:`prepare` writes.
DOCUMENT = 'deformer.x3dv'
#: The surfaces it names, each written as a base, a metallic-roughness and a normal map.
SURFACES = ('marble', 'brass', 'sandstone')

#: The column: its control net's radius, its height, and its lattice's half-width.
COLUMN_CONTROL_RADIUS, COLUMN_HEIGHT, COLUMN_REACH = 0.44, 3.0, 0.6
#: The column's control net: points around (the last on the first) and rows up.
COLUMN_NET = (9, 9)
#: The capsule: half its length and its radius, and its control net.
CAPSULE = (0.42, 0.62)
CAPSULE_NET = (9, 7)
#: The nozzle's lattice: half its length, its height, half its depth.
NOZZLE = (1.5, 2.0, 1.0)
#: The capsule's metal.
BRASS = (0.89, 0.72, 0.36)
#: How far along the nozzle the capsule is carried each way.
TRAVEL = 1.1


def knots(low: float, high: float, dimension: int, order: int) -> np.ndarray:
    """A knot vector over ``low`` to ``high`` whose curve starts and ends on its end points"""
    inner = np.linspace(low, high, dimension - order + 2)[1:-1]
    return np.concatenate([[low] * order, inner, [high] * order])


def lattice(
    low: Sequence[float], high: Sequence[float], dimensions: Sequence[int], order: int = 3,
) -> "tuple[np.ndarray, list[np.ndarray]]":
    """A lattice that leaves every point of its box where it is

    Returns the control points, ``(w, v, u, 3)``, and the u, v and w knot
    vectors. Each control point is at the mean of the ``order - 1`` knots
    after its own, which is where a NURBS reproduces a straight line.
    """
    vectors = [knots(a, b, n, order) for a, b, n in zip(low, high, dimensions, strict=True)]
    places = [np.asarray([vector[i + 1:i + order].mean() for i in range(n)])
              for vector, n in zip(vectors, dimensions, strict=True)]
    w, v, u = np.meshgrid(places[2], places[1], places[0], indexing='ij')
    return np.stack([u, v, w], axis=-1), vectors


def lattice_lines(dimensions: Sequence[int]) -> "list[int]":
    """An `IndexedLineSet` index joining each control point to its neighbours"""
    u, v, w = dimensions
    at = np.arange(u * v * w).reshape(w, v, u)
    index: "list[int]" = []
    for rows in (at.reshape(-1, u), at.transpose(0, 2, 1).reshape(-1, v),
                 at.transpose(1, 2, 0).reshape(-1, w)):
        for row in rows:
            index.extend(int(entry) for entry in row)
            index.append(-1)
    return index


def column() -> np.ndarray:
    """The column's control net, ``(rows, around, 3)``: rings up a cylinder

    Each ring's last point is its first, which closes the surface around.
    """
    angle = np.linspace(0.0, 2.0 * np.pi, COLUMN_NET[0])
    ring = np.stack([COLUMN_CONTROL_RADIUS * np.sin(angle), np.zeros(len(angle)),
                     COLUMN_CONTROL_RADIUS * np.cos(angle)], axis=1)
    ring[-1] = ring[0]
    net = np.repeat(ring[None], COLUMN_NET[1], axis=0)
    net[..., 1] = np.linspace(0.0, COLUMN_HEIGHT, COLUMN_NET[1])[:, None]
    return net


def capsule() -> np.ndarray:
    """The capsule's control net, ``(rows, around, 3)``: rings from one end to the other

    It lies along x with its centre a unit above the origin. The first and
    the last ring are single points.
    """
    half_length, radius = CAPSULE
    angle = np.linspace(0.0, 2.0 * np.pi, CAPSULE_NET[0])
    along = np.linspace(0.0, np.pi, CAPSULE_NET[1])
    net = np.zeros((CAPSULE_NET[1], CAPSULE_NET[0], 3))
    net[..., 0] = -half_length * np.cos(along)[:, None]
    net[..., 1] = 1.0 + radius * np.sin(along)[:, None] * np.cos(angle)[None, :]
    net[..., 2] = radius * np.sin(along)[:, None] * np.sin(angle)[None, :]
    net[:, -1] = net[:, 0]
    return net


def column_keys() -> np.ndarray:
    """The column's lattice at each key: straight, bent, twisted, swollen, straight"""
    reach, dimensions = COLUMN_REACH, (3, 5, 3)
    rest, _ = lattice((-reach, 0.0, -reach), (reach, COLUMN_HEIGHT, reach), dimensions)
    height = rest[..., 1] / COLUMN_HEIGHT
    bent = rest.copy()
    bent[..., 0] += 0.9 * height ** 2
    bent[..., 1] -= 0.25 * height ** 2
    twisted = rest.copy()
    angle = 1.2 * height
    twisted[..., 0] = rest[..., 0] * np.cos(angle) + rest[..., 2] * np.sin(angle)
    twisted[..., 2] = rest[..., 2] * np.cos(angle) - rest[..., 0] * np.sin(angle)
    swollen = rest.copy()
    swell = 1.0 + 0.9 * np.sin(np.pi * height)
    swollen[..., 0] *= swell
    swollen[..., 2] *= swell
    return np.stack([rest, bent, twisted, swollen, rest]).reshape(5, -1, 3)


def nozzle() -> "tuple[np.ndarray, list[np.ndarray]]":
    """The nozzle's lattice: its middle drawn in to a fifth, about its own axis"""
    length, height, depth = NOZZLE
    control, vectors = lattice((-length, 0.0, -depth), (length, height, depth), (5, 3, 3))
    control[:, :, 2, 1] = height / 2.0 + 0.2 * (control[:, :, 2, 1] - height / 2.0)
    control[:, :, 2, 2] *= 0.2
    return control, vectors


def _numbers(values: Any, per_line: int = 12) -> str:
    flat = ['%.5g' % value for value in np.asarray(values, dtype=np.float64).ravel()]
    return '\n'.join(' '.join(flat[start:start + per_line])
                     for start in range(0, len(flat), per_line))


def _material(surface: str) -> str:
    return '''material PhysicalMaterial {
      metallic %(metallic)d roughness 1
      baseTexture ImageTexture { url "%(name)s_base.png" }
      metallicRoughnessTexture ImageTexture { url "%(name)s_mr.png" }
      normalTexture ImageTexture { url "%(name)s_normal.png" }
    }''' % {'name': surface, 'metallic': surface == 'brass'}


def _surface(points: str, net: np.ndarray, texture: str, segments: "tuple[int, int]") -> str:
    rows, around = net.shape[:2]
    return '''Shape {
  appearance Appearance {
    %s
  }
  geometry NurbsPatchSurface {
    uDimension %d vDimension %d uOrder 4 vOrder 4 uClosed TRUE solid FALSE
    uTessellation %d vTessellation %d
    controlPoint USE %s
  }
}''' % (_material(texture), around, rows, segments[0], segments[1], points)


def _lines(name: str, points: Any, dimensions: Sequence[int]) -> str:
    return '''Shape {
  appearance Appearance { material Material { emissiveColor 1 0.8 0.2 } }
  geometry IndexedLineSet {
    coord DEF %s Coordinate { point [ %s ] }
    coordIndex [ %s ]
  }
}''' % (name, _numbers(points), ' '.join(str(entry) for entry in lattice_lines(dimensions)))


def _deformer(name: str, control: np.ndarray, vectors: "list[np.ndarray]",
              net: np.ndarray, output: str, texture: str, segments: "tuple[int, int]",
              carrier: str = '') -> str:
    w, v, u = control.shape[:3]
    return '''DEF %s CoordinateDeformer {
  uDimension %d vDimension %d wDimension %d
  uOrder 3 vOrder 3 wOrder 3
  uKnot [ %s ]
  vKnot [ %s ]
  wKnot [ %s ]
  controlPoint [ %s ]
  inputCoord [ Coordinate { point [ %s ] } ]
  %s
  outputCoord [ DEF %s Coordinate { } ]
  children [ %s ]
}''' % (name, u, v, w, _numbers(vectors[0]), _numbers(vectors[1]), _numbers(vectors[2]),
        _numbers(control), _numbers(net), carrier, output,
        _surface(output, net, texture, segments))


def world() -> str:
    """The X3D document, as ClassicVRML text"""
    keys = column_keys()
    reach = COLUMN_REACH
    _rest, column_vectors = lattice((-reach, 0.0, -reach), (reach, COLUMN_HEIGHT, reach),
                                    (3, 5, 3))
    neck, nozzle_vectors = nozzle()
    return '''#X3D V4.0 utf8
PROFILE Immersive
COMPONENT NURBS:1
COMPONENT OpenGLContext:1
WorldInfo {
  title "CoordinateDeformer"
  info [ "The world oglc-deformer opens: a column deformed by an animated lattice, and a capsule carried through a lattice with a narrow neck." ]
}
NavigationInfo { type [ "EXAMINE" "ANY" ] }
Background { skyColor [ 0.38 0.52 0.72, 0.72 0.80 0.90 ] skyAngle [ 1.4 ] groundColor [ 0.30 0.27 0.22 ] }
Viewpoint { description "The deformers" position 0.3 2.0 8.5 orientation 1 0 0 -0.08 }
DirectionalLight { global TRUE shadows TRUE shadowIntensity 0.8
                   direction -0.5 -0.8 -0.6 intensity 2.2 color 1 0.96 0.9 }

Shape {
  appearance Appearance {
    %(floor)s
  }
  geometry IndexedFaceSet {
    coord Coordinate { point [ -6 0 4, 6 0 4, 6 0 -4, -6 0 -4 ] }
    texCoord TextureCoordinate { point [ 0 0, 6 0, 6 4, 0 4 ] }
    coordIndex [ 0 1 2 3 -1 ]
  }
}

Transform { translation -2.2 0 0 children [
%(column)s
] }

Transform { translation 1.6 0 0 children [
%(nozzle)s
] }

DEF Lattices Switch { whichChoice 0 children [ Group { children [
  Transform { translation -2.2 0 0 children [
%(column_lines)s
  ] }
  Transform { translation 1.6 0 0 children [
%(nozzle_lines)s
  ] }
] } ] }

DEF Clock TimeSensor { cycleInterval 10 loop TRUE }
DEF Bend CoordinateInterpolator {
  key [ 0 0.25 0.5 0.75 1 ]
  keyValue [ %(keys)s ]
}
DEF Carry PositionInterpolator {
  key [ 0 0.25 0.5 0.75 1 ]
  keyValue [ %(left)g 0 0, 0 0 0, %(right)g 0 0, 0 0 0, %(left)g 0 0 ]
}
ROUTE Clock.fraction_changed TO Bend.set_fraction
ROUTE Clock.fraction_changed TO Carry.set_fraction
ROUTE Bend.value_changed TO Column.controlPoint
ROUTE Bend.value_changed TO ColumnGrid.point
ROUTE Carry.value_changed TO Carrier.translation
''' % {
        'column': _deformer('Column', keys[0].reshape(3, 5, 3, 3), column_vectors, column(),
                            'ColumnPoints', 'marble', (48, 40)),
        'nozzle': _deformer(
            'Nozzle', neck, nozzle_vectors, capsule(), 'CapsulePoints', 'brass', (40, 32),
            'inputTransform [ DEF Carrier Transform { translation %g 0 0 } ]' % -TRAVEL),
        'column_lines': _lines('ColumnGrid', keys[0], (3, 5, 3)),
        'nozzle_lines': _lines('NozzleGrid', neck, (5, 3, 3)),
        'keys': _numbers(keys),
        'floor': _material('sandstone'),
        'left': -TRAVEL, 'right': TRAVEL,
    }


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    if name == 'brass':
        return surfaces.brushed_metal(256, BRASS)
    return surfaces.sandstone(256)


def prepare(directory: str, force: bool = False) -> str:
    """The document, written to `directory` with the texture maps it names

    Maps already there are kept unless `force`. Returns the document's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import staged_file, write_text  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, DOCUMENT)
    write_text(target, world())
    for name in SURFACES:
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    return target


class DeformerScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'g': 'show or hide the lattices',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        for name in ('Column', 'Nozzle'):
            self.scene.getDEF(name).deform()

    def advance(self, fraction: float) -> None:
        """Stop the document's clock and put both animations at `fraction` of their cycle"""
        self.scene.getDEF('Clock').enabled = False
        for name in ('Bend', 'Carry'):
            self.scene.getDEF(name).set_fraction = fraction

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'g':
            lattices = self.scene.getDEF('Lattices')
            lattices.whichChoice = -1 if lattices.whichChoice == 0 else 0
            return 'lattices shown' if lattices.whichChoice == 0 else 'lattices hidden'
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-deformer', description=__doc__.split('\n')[0],
        epilog=DeformerScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its maps are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'deformer')
    base: Any = testingcontext.getInteractive()

    class DeformerContext(base):                # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.deformers = DeformerScene(directory)
            self.sg = self.deformers.scene
            for key in DeformerScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(DeformerScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.deformers.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    DeformerContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext CoordinateDeformer', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
