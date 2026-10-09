#! /usr/bin/env python
"""X3D particles: X3D's ParticleSystems component read from a document and drawn.

    oglc-x3d-particles [--directory DIR]

    f      the firework set off again
    w      the wind over the snow off and on

The document is ``x3d_particles.x3d``, shipped with this module: a brazier of
sprites rising from a PointEmitter, a fountain of streaks from a ConeEmitter
under gravity, a firework from an ExplosionEmitter, snow falling from a
PolylineEmitter in gusting wind, a gold sphere a SurfaceEmitter sheds
two-frame sparks from, and a glass case of gold beads a VolumeEmitter makes
and a BoundedPhysicsModel keeps inside. :func:`prepare` writes the stone maps
and the spark sheet it names beside a copy of it. docs/particles.rst describes
the nodes.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['DOCUMENT', 'ParticleScene', 'main', 'prepare', 'spark_sheet']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_particles.x3d')
#: The side of one frame of the spark sheet, in pixels.
FRAME = 64


def spark_sheet(size: int = FRAME) -> np.ndarray:
    """Two RGBA frames side by side: a soft dot, then a four-pointed star"""
    centre = (size - 1) / 2.0
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    dx, dy = (x - centre) / centre, (y - centre) / centre
    dot = np.clip(1.0 - np.hypot(dx, dy), 0.0, 1.0) ** 2
    star = np.clip(1.0 - np.minimum(np.abs(dx), np.abs(dy)) * 6.0 - np.hypot(dx, dy) * 0.6,
                   0.0, 1.0)
    alpha = np.concatenate([dot, star], axis=1)
    pixels = np.empty((size, size * 2, 4), np.uint8)
    pixels[..., :3] = 255
    pixels[..., 3] = (alpha * 255).astype(np.uint8)
    return pixels


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    return surfaces.sandstone(256)


def prepare(directory: str, force: bool = False) -> str:
    """The document, copied to `directory` with the images it names

    Images already there are kept unless `force`. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in ('marble', 'sandstone'):
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    sheet = os.path.join(directory, 'particle_sheet.png')
    if force or not os.path.exists(sheet):
        with staged_file(sheet) as handle:
            Image.fromarray(spark_sheet(), 'RGBA').save(handle, 'PNG')
    return target


class ParticleScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'f': 'the firework set off again',
        'w': 'the wind over the snow off and on',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'f':
            firework = self.scene.getDEF('Firework')
            firework.createParticles = False
            firework.createParticles = True
            return 'firework'
        if key == 'w':
            wind = self.scene.getDEF('Wind')
            wind.enabled = not wind.enabled
            return 'wind %s' % ('on' if wind.enabled else 'off')
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-particles', description=__doc__.split('\n')[0],
        epilog=ParticleScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its images are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-particles')
    base: Any = testingcontext.getInteractive()

    class ParticleContext(base):                # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.particles = ParticleScene(directory)
            self.sg = self.particles.scene
            for key in ParticleScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(ParticleScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.particles.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    ParticleContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D particles', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
