#! /usr/bin/env python
"""X3D GaussianSplats: a brass vase and a clipped hedge made of splats, on a marble terrace.

    oglc-x3d-splats [--directory DIR]

    d      the vase's harmonics above degree 0 off and on
    s      the splats' shadows off and on (their castShadow)
    g      the vase written as a KHR_gaussian_splatting glTF, beside the document
    w      the scene written back as X3D in each encoding, beside the document

:func:`prepare` writes ``x3d_splats.x3d`` and the files it names. The vase is
a ``GaussianSplats`` node in the document: flat splats laid over a lathed
surface, each coloured by spherical harmonics to degree 3 fitted to how
polished brass under this sky looks from every side (:func:`brass`), so its
sheen moves as the viewer does. The hedge is a ``KHR_gaussian_splatting``
glTF the document ``Inline``s: leaves scattered through a rounded block,
shaded darker inside. Both cast shadows on the terrace, a marble floor with
a sandstone plinth and a steel ball, drawn as meshes. docs/x3d.rst
describes the node.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['HARMONIC_DEGREE', 'SUN', 'Showcase', 'brass', 'document', 'hedge',
           'main', 'prepare', 'splats_element', 'vase']

#: Where the sun shines from: the unit direction its light travels.
SUN = tuple(float(value) for value in np.array((-0.55, -0.75, -0.4))
            / np.linalg.norm((-0.55, -0.75, -0.4)))
#: The vase's profile, (radius, height) in metres, from the foot up.
PROFILE = ((0.0, 0.0), (0.17, 0.0), (0.2, 0.04), (0.27, 0.2), (0.29, 0.34),
           (0.24, 0.54), (0.14, 0.72), (0.11, 0.82), (0.14, 0.92), (0.16, 0.96))
#: The spacing of the vase's splats, metres.
SPACING = 0.02
#: The degree of the vase's harmonics.
HARMONIC_DEGREE = 3
#: Brass's reflectance at normal incidence, linear.
BRASS = np.array((0.88, 0.60, 0.26))
#: The sky the vase reflects: below the horizon, at it, and overhead, linear.
GROUND, HORIZON, ZENITH = (np.array((0.08, 0.07, 0.06)), np.array((0.62, 0.62, 0.6)),
                           np.array((0.22, 0.34, 0.66)))
#: The hedge's size (x, y, z), metres, and its leaf count.
HEDGE_SIZE, LEAVES = (1.4, 0.8, 0.5), 9000


def _display(linear: np.ndarray) -> np.ndarray:
    """Linear light, tone mapped and encoded as sRGB display values in [0, 1]"""
    mapped = 1.25 * linear / (1.0 + linear)
    return np.asarray(np.clip(mapped, 0.0, 1.0) ** (1.0 / 2.2))


def brass(directions: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """(N, M, 3) display colours of polished brass with (N, 3) `normals`, seen along (M, 3) `directions`

    Each direction is from the camera to the surface. The colour is the
    sky's colour along the reflected ray times brass's reflectance, with the
    sun's glint, both by Schlick's approximation of the Fresnel term.
    """
    view = np.asarray(directions, np.float64)[None, :, :]
    normal = np.asarray(normals, np.float64)[:, None, :]
    facing = np.sum(view * normal, axis=-1, keepdims=True)
    reflected = view - 2.0 * facing * normal
    up = reflected[..., 1:2]
    sky = np.where(up >= 0.0, HORIZON + (ZENITH - HORIZON) * np.sqrt(np.clip(up, 0.0, 1.0)),
                   HORIZON + (GROUND - HORIZON) * np.clip(-up * 4.0, 0.0, 1.0))
    glint = 6.0 * np.clip(np.sum(reflected * -np.asarray(SUN), axis=-1, keepdims=True),
                          0.0, 1.0) ** 40
    fresnel = BRASS + (1.0 - BRASS) * (1.0 - np.abs(facing)) ** 5
    return _display(fresnel * (sky + glint))


def _profile_points(spacing: float) -> tuple[np.ndarray, np.ndarray]:
    """(rows, 2) (radius, height) points along the profile `spacing` apart, and their outward normals"""
    points = np.asarray(PROFILE, np.float64)
    steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(steps)])
    stations = np.arange(spacing / 2, along[-1], spacing)
    found = np.stack([np.interp(stations, along, points[:, 0]),
                      np.interp(stations, along, points[:, 1])], -1)
    segment = np.clip(np.searchsorted(along, stations) - 1, 0, len(steps) - 1)
    tangent = np.diff(points, axis=0)[segment] / steps[segment, None]
    return found, np.stack([tangent[:, 1], -tangent[:, 0]], -1)


def vase(spacing: float = SPACING, degree: int = HARMONIC_DEGREE) -> dict[str, Any]:
    """The vase's splats: from_arrays' arguments, flat splats `spacing` apart over its surface"""
    from OpenGLContext.scenegraph import splatmath  # noqa: PLC0415 NumPy work only when written
    rows, row_normals = _profile_points(spacing)
    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    for (radius, height), (outward, upward) in zip(rows, row_normals):
        count = max(int(round(2.0 * math.pi * radius / spacing)), 1)
        turn = (np.arange(count) + 0.5 * (len(positions) % 2)) * 2.0 * math.pi / count
        positions.append(np.stack([radius * np.cos(turn), np.full(count, height),
                                   radius * np.sin(turn)], -1))
        normals.append(np.stack([outward * np.cos(turn), np.full(count, upward),
                                 outward * np.sin(turn)], -1))
    centres, facing = np.concatenate(positions), np.concatenate(normals)
    directions = splatmath.sphere_directions(4 * (degree + 1) ** 2 + 64)
    coefficients = splatmath.fit_harmonics(directions, brass(directions, facing), degree)
    return dict(positions=centres, rotations=splatmath.facing(facing),
                scales=np.tile((0.8 * spacing, 0.8 * spacing, 0.08 * spacing), (len(centres), 1)),
                opacities=np.full(len(centres), 0.97),
                harmonics=[coefficients[:, index] for index in range(coefficients.shape[1])])


def hedge(count: int = LEAVES, seed: int = 7) -> dict[str, Any]:
    """The hedge's splats: from_arrays' arguments, `count` leaves through a rounded block"""
    from OpenGLContext.scenegraph import splatmath  # noqa: PLC0415 NumPy work only when written
    rng = np.random.default_rng(seed)
    half = np.asarray(HEDGE_SIZE) / 2.0
    # Points through a superellipsoid, most of them near its skin.
    direction = rng.normal(size=(count, 3))
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    skin = np.sum(np.abs(direction / half) ** 4, axis=1) ** -0.25
    depth = 1.0 - 0.35 * rng.random(count) ** 2.5
    positions = direction * (skin * depth)[:, None] + (0.0, half[1], 0.0)
    rotations = rng.normal(size=(count, 4))
    size = rng.uniform(0.7, 1.3, count)[:, None]
    scales = np.array((0.035, 0.02, 0.004)) * size
    green = np.array((0.07, 0.2, 0.04)) + rng.normal(scale=0.02, size=(count, 3))
    lit = 0.55 + 0.45 * np.clip(direction @ -np.asarray(SUN), 0.0, 1.0)
    shade = (lit * (depth - 0.6) / 0.4)[:, None]
    colour = _display(np.clip(green * shade * 1.6, 0.0, None))
    dc = (colour - 0.5) / splatmath.SH_C0
    return dict(positions=positions, rotations=rotations, scales=scales,
                opacities=rng.uniform(0.75, 0.95, count), harmonics=[dc])


def _numbers(values: Any, width: int) -> str:
    rows = np.asarray(values, np.float64).reshape(-1, width)
    return ', '.join(' '.join('%.5g' % value for value in row) for row in rows)


def splats_element(splats: dict[str, Any], **attributes: str) -> str:
    """An X3D GaussianSplats element of from_arrays' arguments `splats`, with `attributes` added"""
    from OpenGLContext.scenegraph.gaussiansplats import HARMONIC_FIELDS  # noqa: PLC0415 kept with its use
    named = dict(attributes)
    named.update(positions=_numbers(splats['positions'], 3),
                 orientations=_numbers(splats['rotations'], 4),
                 scales=_numbers(splats['scales'], 3),
                 opacities=_numbers(splats['opacities'], 1).replace(',', ''))
    for name, values in zip(HARMONIC_FIELDS, splats['harmonics']):
        named[name] = _numbers(values, 3)
    return '<GaussianSplats %s/>' % ' '.join('%s="%s"' % item for item in named.items())


def document() -> str:
    """The showcase's X3D document, the vase written into it"""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Immersive" version="4.1">
<head><component name="GaussianSplats" level="1"/>
<meta name="title" content="X3D GaussianSplats: a brass vase and a hedge"/>
<meta name="creator" content="OpenGLContext"/>
<meta name="license" content="BSD-3-Clause"/></head>
<Scene>
<WorldInfo title="X3D GaussianSplats"/>
<NavigationInfo headlight="false" type='"EXAMINE" "ANY"'/>
<Background skyColor="0.32 0.48 0.85 0.85 0.85 0.82" skyAngle="1.45"
  groundColor="0.85 0.85 0.82 0.4 0.36 0.3" groundAngle="1.5"/>
<Viewpoint description="The terrace" position="0.3 1.55 3.6" orientation="1 0 0 -0.2"/>
<Viewpoint description="The vase" position="0.1 1.25 1.9" orientation="1 0 0 -0.12"/>
<DirectionalLight DEF="Sun" global="true" shadows="true" shadowIntensity="0.8"
  direction="{sun}" intensity="2.6" color="1 0.96 0.9"/>
<DirectionalLight global="true" direction="0.5 -0.4 0.6" intensity="0.5" color="0.6 0.7 0.95"/>
<Shape>
  <Appearance>
    <PhysicalMaterial metallic="0" roughness="1">
      <ImageTexture containerField="baseTexture" url='"marble_base.png"'/>
      <ImageTexture containerField="metallicRoughnessTexture" url='"marble_mr.png"'/>
      <ImageTexture containerField="normalTexture" url='"marble_normal.png"'/>
    </PhysicalMaterial>
    <TextureTransform scale="4 4"/>
  </Appearance>
  <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
    <Coordinate point="-4 0 -3, -4 0 3, 4 0 3, 4 0 -3"/>
    <Normal vector="0 1 0, 0 1 0, 0 1 0, 0 1 0"/>
    <TextureCoordinate point="0 1, 0 0, 1 0, 1 1"/>
  </IndexedTriangleSet>
</Shape>
<Transform translation="0 0.3 0">
  <Shape>
    <Appearance>
      <PhysicalMaterial metallic="0" roughness="0.9">
        <ImageTexture containerField="baseTexture" url='"sandstone_base.png"'/>
        <ImageTexture containerField="normalTexture" url='"sandstone_normal.png"'/>
      </PhysicalMaterial>
    </Appearance>
    <Box size="0.8 0.6 0.8"/>
  </Shape>
</Transform>
<Transform translation="0 0.6 0">
{vase}
</Transform>
<Transform translation="1.1 0.22 0.5">
  <Shape>
    <Appearance><PhysicalMaterial baseColor="0.56 0.57 0.58" metallic="1" roughness="0.4"/>
    </Appearance>
    <Sphere radius="0.22"/>
  </Shape>
</Transform>
<Transform translation="-1.7 0 -0.6" rotation="0 1 0 0.35">
  <Inline url='"hedge.glb"'/>
</Transform>
</Scene>
</X3D>
'''.format(sun=' '.join('%.6g' % value for value in SUN),
           vase=splats_element(vase(), DEF='Vase'))


def prepare(directory: str) -> str:
    """The document and the files it names, written to `directory`; the document's path"""
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import staged_file, write_bytes  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.gltf.writer import write_glb  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    from OpenGLContext.scenegraph.gaussiansplats import from_arrays  # noqa: PLC0415 kept with its use
    os.makedirs(directory, exist_ok=True)
    for name, maps in (('marble', surfaces.marble_tiles(256, tiles=2)),
                       ('sandstone', surfaces.sandstone(256))):
        for part, pixels in zip(('base', 'mr', 'normal'), surfaces.images(maps), strict=True):
            with staged_file(os.path.join(directory, '%s_%s.png' % (name, part))) as handle:
                Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    write_bytes(os.path.join(directory, 'hedge.glb'), write_glb(from_arrays(**hedge())))
    target = os.path.join(directory, 'x3d_splats.x3d')
    with staged_file(target) as handle:
        handle.write(document().encode('utf-8'))
    return target


class Showcase:
    """The splats showcase with no window: what the command, its tutorial and its tests share

    ``scene`` is the document read by the engine's loader and ``vase`` its
    GaussianSplats node.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'd': "the vase's harmonics above degree 0 off and on",
        's': "the splats' shadows off and on",
        'g': 'the vase written as a KHR_gaussian_splatting glTF',
        'w': 'the scene written back as X3D in each encoding',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.gaussiansplats import HARMONIC_FIELDS  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        self.vase = self.scene.getDEF('Vase')
        self._higher = {name: getattr(self.vase, name) for name in HARMONIC_FIELDS[1:]}

    def splat_sets(self) -> list[Any]:
        """Every GaussianSplats node the scene draws, the Inlined hedge's among them"""
        from OpenGLContext.scenegraph.gaussiansplats import GaussianSplats  # noqa: PLC0415 kept with its use
        found, pending = [], [self.scene]
        while pending:
            node = pending.pop()
            if isinstance(node, GaussianSplats):
                found.append(node)
            walk = getattr(node, 'renderedChildren', None)
            pending.extend(walk() if walk is not None else getattr(node, 'children', None) or ())
        return found

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'd':
            shown = len(self.vase.sphericalHarmonicsDegree1Coef0) > 0
            for name, values in self._higher.items():
                setattr(self.vase, name, [] if shown else values)
            return "the vase's harmonics to degree %d" % (0 if shown else HARMONIC_DEGREE)
        if key == 's':
            sets = self.splat_sets()
            casting = not all(node.castShadow for node in sets)
            for node in sets:
                node.castShadow = casting
            return 'the splats %s shadows' % ('cast' if casting else 'cast no')
        if key == 'g':
            from OpenGLContext.loaders.gltf.writer import write_glb  # noqa: PLC0415 kept with its use
            path = os.path.join(self.directory, 'written-vase.glb')
            data = write_glb(self.vase, path=path)
            return 'wrote %s (%d bytes)' % (os.path.basename(path), len(data))
        if key == 'w':
            from vrml import x3d  # noqa: PLC0415 kept with its use
            written = []
            for suffix in ('x3d', 'x3dv', 'x3dj'):
                path = os.path.join(self.directory, 'written.%s' % (suffix,))
                x3d.dump(self.scene, path)
                written.append('%s (%d bytes)' % (os.path.basename(path), os.path.getsize(path)))
            return 'wrote ' + ', '.join(written)
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the showcase in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-splats', description=(__doc__ or '').split('\n')[0],
        epilog=Showcase.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its files are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-splats')
    base: Any = testingcontext.getInteractive()

    class ShowcaseContext(base):                 # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.showcase = Showcase(directory)
            self.sg = self.showcase.scene
            for key in Showcase.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(Showcase.help())

        def OnKey(self, event: Any) -> None:
            said = self.showcase.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

    ShowcaseContext.ContextMainLoop(definition=ContextDefinition(
        title='X3D GaussianSplats', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':  # pragma: no cover - the command line
    sys.exit(main())
