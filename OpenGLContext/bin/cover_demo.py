#! /usr/bin/env python
"""Ground cover: grass, ferns and flowers over a hillside, and a well cut into it.

Walk around with the arrow keys and press the keys it prints:

    oglc-cover

    o      the well's opening: the ground cut open over it, or closed
    d      how dense the cover is: all of it, half, none

Three kinds of plant grow on the meadow the splat control map paints, and none
on the rock of the steeper slopes. Grass is real geometry near the camera, in
two levels of detail, and cards beyond; ferns gather in beds and flowers in
smaller clumps, as their ``patchiness`` asks. The well is an opening in the
ground (``holes``): the terrain's mesh is cut round it and nothing grows over
it, and the stone shaft below shows through. docs/vegetation.rst and
docs/terrain.rst describe each setting, and this file is the working code for
them. The art -- the plants' cards and the grass's clump -- is drawn by this
module and written to the per-user cache the first time it runs.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw

from OpenGLContext.scenegraph import basenodes, surfaces

__all__ = ['Meadow', 'main']

#: The world's square, in metres, and its height grid's resolution.
EXTENT = 320.0
RESOLUTION = 129
#: The well: where its centre is on the ground (x, z), its radius and depth.
WELL = (18.0, -26.0)
WELL_RADIUS = 5.0
WELL_DEPTH = 9.0
#: The cover's density settings, in the order ``d`` steps through them.
DENSITIES = (1.0, 0.5, 0.0)
#: The splat layers, in the control map's channel order.
LAYERS = ['meadow', 'earth', 'rock']


def hills(x: Any, z: Any) -> Any:
    """The land: long low swells, and a ridge to the north steep enough for rock."""
    x = np.asarray(x, 'd')
    z = np.asarray(z, 'd')
    swell = 2.5 * np.sin(x / 37.0) * np.cos(z / 29.0) + 1.5 * np.sin((x + z) / 53.0)
    ridge = 22.0 / (1.0 + np.exp((z + 95.0) / 9.0))
    return swell + ridge


def _png(pixels: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, 'PNG')
    return buffer.getvalue()


class Grounds:
    """The terrain's layers, drawn from :mod:`~OpenGLContext.scenegraph.surfaces`.

    Called as a terrain's ``material_fn``: ``grounds(name, resolution)`` is a
    dict of a colour and a normal map, as images to open.
    """

    def __init__(self) -> None:
        self._maps = {
            'meadow': surfaces.plaster(256, colour=(0.07, 0.14, 0.035), seed=11),
            'earth': surfaces.sandstone(256, colour=(0.20, 0.13, 0.07), seed=12),
            'rock': surfaces.sandstone(256, colour=(0.30, 0.29, 0.27), seed=13),
        }
        self._images: dict[str, tuple[bytes, bytes]] = {}

    def __call__(self, name: str, resolution: str) -> dict[str, Any]:
        if name not in self._images:
            base, _packed, bumps = surfaces.images(self._maps[name], relief=3.0)
            self._images[name] = (_png(base), _png(bumps))
        colour, normal = self._images[name]
        return {'color': io.BytesIO(colour), 'normal': io.BytesIO(normal)}


class Art:
    """The plants' cards and the grass's clump, drawn and written to ``where``.

    Each file is written the first time it is asked for and read from there
    after, since a species names its art by path.
    """

    def __init__(self, where: str) -> None:
        self.where = where

    def path(self, name: str, make: Callable[[], bytes]) -> str:
        """Where ``name`` is, written from ``make()`` if it is not there yet."""
        from OpenGLContext import atomicfiles
        found = os.path.join(self.where, name)
        if not os.path.exists(found):
            atomicfiles.write_bytes(found, make())
        return found

    def card(self, kind: str) -> str:
        """A plant's billboard: grass, fern or flowers."""
        return self.path('%s-card.png' % (kind,),
                         lambda: _png(np.asarray(_CARDS[kind]())))

    def clump(self) -> str:
        """The grass's clump: a fuller mesh named ``near`` and a coarser ``far``."""
        return self.path('grass-clump.glb', _clump_glb)


def _grass_card(seed: int = 21) -> Image.Image:
    """Tapered blades leaning every way, in greens, on a clear ground."""
    rng = np.random.default_rng(seed)
    card = Image.new('RGBA', (128, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    for _blade in range(18):
        root = rng.uniform(24, 104)
        tip = (root + rng.uniform(-30, 30), rng.uniform(20, 120))
        width = rng.uniform(2.5, 5.0)
        colour = tuple(int(v) for v in (rng.uniform(55, 95), rng.uniform(110, 160),
                                        rng.uniform(25, 55))) + (255,)
        draw.polygon([(root - width, 256), (root + width, 256), tip], fill=colour)
    return card


def _fern_card(seed: int = 22) -> Image.Image:
    """Fronds arching from one crown, each a stem with leaflets down both sides."""
    rng = np.random.default_rng(seed)
    card = Image.new('RGBA', (128, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    for frond in range(7):
        lean = (frond - 3) * 0.28 + rng.uniform(-0.08, 0.08)
        length = rng.uniform(150, 220)
        green = (int(rng.uniform(40, 70)), int(rng.uniform(95, 130)),
                 int(rng.uniform(30, 50)), 255)
        points = [(64 + math.sin(lean * t) * length * t,
                   256 - math.cos(lean * t) * length * t)
                  for t in np.linspace(0.0, 1.0, 12)]
        draw.line(points, fill=green, width=2)
        for index, (x, y) in enumerate(points[2:], 2):
            size = 14.0 * (1.0 - index / 12.0) + 3.0
            for side in (-1, 1):
                draw.polygon([(x, y), (x + side * size, y - size * 0.4),
                              (x + side * size * 0.3, y - size * 0.9)], fill=green)
    return card


def _flower_card(seed: int = 23) -> Image.Image:
    """Thin stems with round heads of yellow, white and violet."""
    rng = np.random.default_rng(seed)
    card = Image.new('RGBA', (128, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    heads = [(235, 200, 60), (240, 238, 225), (150, 90, 190)]
    for stem in range(9):
        root = rng.uniform(20, 108)
        top = (root + rng.uniform(-14, 14), rng.uniform(40, 150))
        draw.line([(root, 256), top], fill=(70, 120, 45, 255), width=2)
        radius = rng.uniform(6, 10)
        head = heads[stem % len(heads)]
        draw.ellipse([top[0] - radius, top[1] - radius, top[0] + radius,
                      top[1] + radius], fill=head + (255,))
    return card


_CARDS: dict[str, Callable[[], Image.Image]] = {
    'grass': _grass_card, 'fern': _fern_card, 'flowers': _flower_card,
}


def _blade_texture() -> Image.Image:
    """One blade, root to tip, darker at the root, for the clump's geometry."""
    rows = np.linspace(0.0, 1.0, 128)[:, None]
    across = np.abs(np.linspace(-1.0, 1.0, 32))[None, :]
    inside = across < (1.0 - rows)                 # tapers to a point at the top
    shade = 0.55 + 0.45 * (1.0 - rows)
    pixels = np.zeros((128, 32, 4), 'u1')
    pixels[..., 0] = (70 * shade).astype('u1')
    pixels[..., 1] = (150 * shade).astype('u1')
    pixels[..., 2] = (40 * shade).astype('u1')
    pixels[..., 3] = np.where(inside, 255, 0).astype('u1')
    return Image.fromarray(pixels[::-1].copy(), 'RGBA')


def _blades(count: int, rings: int, seed: int = 31) -> Any:
    """A clump of ``count`` blade ribbons, each ``rings`` cross-sections tall."""
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    rng = np.random.default_rng(seed)
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    texcoords: list[tuple[float, float]] = []
    indices: list[int] = []
    for _blade in range(count):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        spot = rng.uniform(-0.12, 0.12, 2)
        lean = rng.uniform(0.1, 0.45)
        height = rng.uniform(0.7, 1.0)
        across = np.array([math.cos(angle), 0.0, math.sin(angle)])
        facing = np.array([-math.sin(angle), 0.0, math.cos(angle)])
        base = len(positions)
        for ring in range(rings):
            t = ring / float(rings - 1)
            centre = (np.array([spot[0], 0.0, spot[1]])
                      + facing * lean * t * t + np.array([0.0, height * t, 0.0]))
            half = 0.03 * (1.0 - t) + 0.002
            for side, u in ((-1.0, 0.0), (1.0, 1.0)):
                positions.append(tuple(centre + across * half * side))
                normals.append(tuple(facing))
                texcoords.append((u, 1.0 - t))
        for ring in range(rings - 1):
            a = base + 2 * ring
            indices.extend((a, a + 1, a + 3, a, a + 3, a + 2))
    material = PBRMaterial(textures={'baseColor': PBRTexture(_blade_texture(),
                                                             srgb=True)})
    return PBRMesh(positions=np.asarray(positions, 'f'),
                   normals=np.asarray(normals, 'f'),
                   texcoords=np.asarray(texcoords, 'f'),
                   indices=np.asarray(indices, np.uint32), material=material)


def _clump_glb() -> bytes:
    from OpenGLContext.loaders.gltf.writer import GLTFWriter
    writer = GLTFWriter()
    writer.add_mesh(_blades(24, 6), name='near')
    writer.add_mesh(_blades(24, 3), name='far')
    return writer.to_glb()


def _default_art() -> str:
    from OpenGLContext.loaders.resolver import default_cache_dir
    return os.path.join(default_cache_dir(), 'oglc-cover')


class Meadow:
    """The scene, its terrain and its cover, with no window.

    ``children`` is the scene; ``terrain`` the ``SplatTerrain`` and ``cover``
    the ``GroundCover`` on it. :meth:`update` is called once a frame with the
    camera's position, and :meth:`press` answers a key. ``art`` is the
    directory the plants' files are written to (the per-user cache by
    default); ``background`` scatters the cover on a worker thread.
    """

    KEYS = {
        'o': 'the well\'s opening cut in the ground, or closed',
        'd': 'the cover at full density, half, or none',
    }

    def __init__(self, art: Optional[str] = None, background: bool = True) -> None:
        from OpenGLContext.scenegraph.terrain import (
            HeightField, LayerRule, SplatTerrain, control_map,
        )
        from OpenGLContext.scenegraph.vegetation import (
            CoverSpecies, GroundCover, control_weight,
        )
        self.art = Art(art if art is not None else _default_art())
        self.field = HeightField.from_function(hills, RESOLUTION, EXTENT)
        self.control = control_map(self.field, [
            LayerRule(),                                  # meadow, where nothing else is
            LayerRule(slope=(0.2, 0.4), weight=0.8),      # earth where it steepens
            LayerRule(slope=(0.35, 20.0)),                # rock on the ridge
        ], size=256)
        self.terrain = SplatTerrain(self.field, LAYERS, self.control,
                                    material_fn=Grounds())
        self.species = [
            CoverSpecies(name='grass', card=self.art.card('grass'),
                         clump=self.art.clump(), clumpMesh='near',
                         clumpFarMesh='far', density=6.0, height=0.45,
                         patchiness=0.2),
            CoverSpecies(name='fern', card=self.art.card('fern'), density=0.7,
                         height=0.75, cardWidth=1.0, patchiness=0.85,
                         patchMetres=18.0),
            CoverSpecies(name='flowers', card=self.art.card('flowers'),
                         density=0.9, height=0.35, patchiness=0.6,
                         patchMetres=9.0),
        ]
        self.cover = GroundCover(
            self.field, self.species,
            mask=control_weight(self.control, ['meadow'], LAYERS, EXTENT),
            shade=self.terrain.shade, background=background)
        self.density = 0
        self.children: list[Any] = [
            basenodes.SimpleBackground(color=(0.58, 0.70, 0.84)),
            basenodes.DirectionalLight(direction=(-0.5, -0.72, -0.48),
                                       color=(1.0, 0.95, 0.86), intensity=2.2),
            basenodes.Shape(geometry=self.terrain,
                            appearance=basenodes.Appearance(
                                material=basenodes.Material())),
            self.cover,
            self._well(),
        ]
        self.open(True)

    # -- the well ------------------------------------------------------------
    def opening(self, x: Any, z: Any) -> Any:
        """``holes(x, z)``: true over the well's mouth."""
        return np.hypot(np.asarray(x, 'd') - WELL[0],
                        np.asarray(z, 'd') - WELL[1]) < WELL_RADIUS

    def _well(self) -> Any:
        """The stone shaft under the opening, its lining facing in."""
        around = np.linspace(0.0, 2.0 * math.pi, 64)
        rim = np.asarray(self.field.sample(WELL[0] + WELL_RADIUS * np.cos(around),
                                           WELL[1] + WELL_RADIUS * np.sin(around)))
        # The lining stands a hand's breadth proud of the highest ground round
        # the mouth, so the cut edge of the terrain meets stone all round.
        top = float(rim.max()) + 0.15
        lining = surfaces.cylinder(WELL_RADIUS, WELL_DEPTH, sides=32, repeat=1.5)
        inward = lining._replace(
            normals=-lining.normals,
            indices=lining.indices.reshape(-1, 3)[:, ::-1].ravel().copy())
        stone = surfaces.pbr_material(surfaces.sandstone(256, colour=(0.16, 0.14, 0.12)))
        floor = surfaces.pbr_material(surfaces.brick(256))
        return basenodes.Transform(
            translation=(WELL[0], top - WELL_DEPTH / 2.0, WELL[1]),
            children=[
                surfaces.shape(inward, stone),
                surfaces.shape(surfaces.block((2 * WELL_RADIUS, 0.2,
                                               2 * WELL_RADIUS), repeat=1.0),
                               floor, translation=(0.0, -WELL_DEPTH / 2.0, 0.0)),
            ])

    def open(self, cut: bool) -> None:
        """Cut the well's opening in the ground and the cover, or close it."""
        holes = self.opening if cut else None
        self.terrain.holes = holes
        self.cover.holes = holes

    # -- each frame, and the keys ----------------------------------------------
    def update(self, position: Sequence[float]) -> bool:
        """Bring the cover up to date for a camera at ``position``; whether it
        has more to stage from a scatter still running."""
        self.cover.update(position)
        return not self.cover.wait(0.0)

    def press(self, key: str) -> str:
        """Answer a key; what changed, for the console, or ''."""
        if key == 'o':
            cut = self.terrain.holes is None
            self.open(cut)
            return 'the well %s' % ('open' if cut else 'closed over')
        if key == 'd':
            self.density = (self.density + 1) % len(DENSITIES)
            self.cover.density_scale = DENSITIES[self.density]
            return 'cover at %d%%' % (round(100 * DENSITIES[self.density]),)
        return ''

    def shutdown(self) -> None:
        """Stop the cover's scatter thread."""
        self.cover.shutdown()

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line."""
        return '\n'.join('  %s -- %s' % item for item in cls.KEYS.items())

    def standing(self, x: float, z: float, eye: float = 1.7) -> tuple[float, float, float]:
        """Where an eye ``eye`` metres over the ground at ``(x, z)`` is."""
        ground = float(self.field.sample(np.array([x]), np.array([z]))[0])
        return (x, ground + eye, z)

    def viewpoint(self) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
        """Where the demo starts: a position, and an orientation looking at the well."""
        x, z = WELL[0] - 7.0, WELL[1] + 13.0
        turn = -math.atan2(WELL[0] - x, z - WELL[1])
        return self.standing(x, z, eye=4.0), (0.0, 1.0, 0.0, turn)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the meadow in a window; ``--help`` prints the keys and exits."""
    argparse.ArgumentParser(
        prog='oglc-cover',
        description=(__doc__ or '').split('\n\n')[0],
        epilog='keys:\n' + Meadow.help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    from OpenGLContext import testingcontext
    from OpenGLContext.contextdefinition import ContextDefinition

    base: Any = testingcontext.getInteractive()

    class CoverContext(base):                   # pragma: no cover - needs a window
        #: The meadow's plants and ground are metallic/roughness materials.
        renderer = 'pbr'

        def OnInit(self) -> None:
            self.meadow = Meadow()
            position, orientation = self.meadow.viewpoint()
            self.getViewPlatform().setPosition(position)
            self.getViewPlatform().setOrientation(orientation)
            self.sg = basenodes.sceneGraph(children=self.meadow.children)
            for key in Meadow.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print('oglc-cover\n' + Meadow.help())

        def OnDraw(self, *args: Any, **named: Any) -> Any:
            busy = self.meadow.update(self.getViewPlatform().position)
            drawn = super().OnDraw(*args, **named)
            if busy:
                self.triggerRedraw(True)
            return drawn

        def OnKey(self, event: Any) -> None:
            said = self.meadow.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

        def OnQuit(self, event: Any = None) -> Any:
            self.meadow.shutdown()
            return super().OnQuit(event)

    CoverContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext ground cover', size=(1280, 720)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
