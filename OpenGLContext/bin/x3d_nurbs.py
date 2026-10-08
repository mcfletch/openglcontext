#! /usr/bin/env python
"""X3D NURBS: X3D's NURBS component read from a document and drawn by the PBR renderer.

    oglc-x3d-nurbs [--directory DIR]

    t      the NurbsSet's tessellation scale: a quarter, one, two

The document is ``x3d_nurbs.x3d``, shipped with this module: a marble shell
trimmed by a rational circle, a gold vase swung around a circle, a brass rail
swept along a curve, a brick banner with a bead a NurbsSurfaceInterpolator
moves over it, and a dart that NURBS interpolators fly along a dashed
NurbsCurve. :func:`prepare` writes the stone and brick maps it names beside a
copy of it. docs/nurbs.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'NurbsScene', 'SCALES', 'main', 'prepare']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_nurbs.x3d')
#: The tessellation scales the t key steps through.
SCALES = (1.0, 2.0, 0.25)


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    if name == 'brick':
        return surfaces.brick(256)
    return surfaces.sandstone(256)


def prepare(directory: str, force: bool = False) -> str:
    """The document, copied to `directory` with the texture maps it names

    Maps already there are kept unless `force`. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in ('marble', 'brick', 'sandstone'):
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    return target


class NurbsScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader; ``detail`` is its
    `NurbsSet`, whose scale the t key changes.
    """

    KEYS: ClassVar[dict[str, str]] = {
        't': "the NurbsSet's tessellation scale",
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        self.detail = self.scene.getDEF('Detail')

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 't':
            current = float(self.detail.tessellationScale)
            following = SCALES[(SCALES.index(current) + 1) % len(SCALES)
                               if current in SCALES else 0]
            self.detail.tessellationScale = following
            return 'tessellation scale %g' % following
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-nurbs', description=__doc__.split('\n')[0],
        epilog=NurbsScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its maps are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-nurbs')
    base: Any = testingcontext.getInteractive()

    class NurbsContext(base):                   # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.nurbs = NurbsScene(directory)
            self.sg = self.nurbs.scene
            for key in NurbsScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(NurbsScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.nurbs.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    NurbsContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D NURBS', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
