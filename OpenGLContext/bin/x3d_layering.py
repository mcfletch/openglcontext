#! /usr/bin/env python
"""X3D layers: X3D's Layering and Layout components read from a document and drawn.

    oglc-x3d-layering [--directory DIR]

    i      the inset and its frame shown or hidden
    p      the panel shown or hidden

The document is ``x3d_layering.x3d``, shipped with this module: a courtyard
of sandstone, brick, marble, copper, steel, brass and wood, navigated in
layer 0; the same courtyard seen from above in an inset viewport at the top
right, through a viewpoint of its own (layer 1); a brass frame around the
inset (layer 2); and a wooden panel placed 16 pixels in from the bottom left
(layer 3), with text in a ScreenFontStyle and a button that shows and hides
the inset. :func:`prepare` writes the maps it names beside a copy of it.
docs/x3d.rst describes the components.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'LayeringScene', 'MATERIALS', 'main', 'prepare']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_layering.x3d')
#: The surfaces the document names, each written as ``<name>_base.png``,
#: ``<name>_mr.png`` and ``<name>_normal.png``.
MATERIALS = ('sandstone', 'brick', 'marble', 'wood', 'copper', 'steel', 'brass')


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'sandstone':
        return surfaces.sandstone(256)
    if name == 'brick':
        return surfaces.brick(256)
    if name == 'marble':
        return surfaces.marble(256, base=(0.16, 0.30, 0.23), vein=(0.78, 0.80, 0.74))
    if name == 'wood':
        return surfaces.wood(256)
    metal = {'copper': surfaces.COPPER, 'steel': surfaces.STEEL, 'brass': (0.62, 0.42, 0.16)}
    return surfaces.brushed_metal(256, metal[name])


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
    for name in MATERIALS:
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    return target


class LayeringScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'i': 'the inset and its frame shown or hidden',
        'p': 'the panel shown or hidden',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'i':
            shown = self.scene.getDEF('Shown')
            shown.set_boolean = True
            return 'inset %s' % ('shown' if shown.toggle else 'hidden')
        if key == 'p':
            panel = self.scene.getDEF('Panel')
            panel.visible = not panel.visible
            return 'panel %s' % ('shown' if panel.visible else 'hidden')
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-layering', description=__doc__.split('\n')[0],
        epilog=LayeringScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its images are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-layering')
    base: Any = testingcontext.getInteractive()

    class LayeringContext(base):                # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.layering = LayeringScene(directory)
            self.sg = self.layering.scene
            for key in LayeringScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(LayeringScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.layering.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    LayeringContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D layers', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
