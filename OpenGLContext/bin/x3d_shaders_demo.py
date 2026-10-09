#! /usr/bin/env python
"""X3D shaders: a document whose shapes are drawn by their own GLSL.

    oglc-x3d-shaders [--directory DIR]

    b      the copper sphere's bands: 2, 3, 4, 6, 8
    a      `activate`: every shader linked again from its sources
    w      the scene written back as X3D in each encoding, beside the document

The document is ``x3d_shaders.x3d``, shipped with this module, and the
packaged shader ``x3d_shaders_stripes.glsl`` it names. :func:`prepare` writes
them and the marble map the column reads beside each other. The shapes are a
toon-shaded copper sphere (`ComposedShader`, lights and material through
`x3d_LightSource` and `x3d_Material`), a marble column written in GLSL 1.20
(`ProgramShader`, translated), a gold sphere coming apart in a geometry stage
by the clock's fraction, a block striped by a `PackagedShader`, a heat bar
coloured by a `FloatVertexAttribute`, and a pool rippling from a routed
field. docs/x3d.rst describes the bindings each uses.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'PACKAGED', 'Showcase', 'main', 'prepare']

_HERE = os.path.dirname(os.path.abspath(__file__))
#: The X3D document the showcase is read from.
DOCUMENT = os.path.join(_HERE, 'x3d_shaders.x3d')
#: The packaged shader the document's striped block reads.
PACKAGED = os.path.join(_HERE, 'x3d_shaders_stripes.glsl')
#: The band counts `b` steps through.
BANDS = (2, 3, 4, 6, 8)


def prepare(directory: str, force: bool = False) -> str:
    """The document, copied to `directory` with the marble map and packaged shader it names

    The map is kept where it is already written, unless `force`. Returns the
    document's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    copy_file(PACKAGED, os.path.join(directory, os.path.basename(PACKAGED)))
    marble = os.path.join(directory, 'marble_base.png')
    if force or not os.path.exists(marble):
        base = surfaces.images(surfaces.checkered_marble(256, tiles=2))[0]
        with staged_file(marble) as handle:
            Image.fromarray(base, 'RGB').save(handle, 'PNG')
    return target


class Showcase:
    """The shader showcase with no window: what the command, its tutorial and its tests share

    ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'b': "the copper sphere's bands",
        'a': 'every shader linked again (activate)',
        'w': 'the scene written back as X3D in each encoding',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)

    def shaders(self) -> "list[Any]":
        """The document's shader nodes, by their DEF names' order in it"""
        names = ('Toon', 'Marble', 'Apart', 'Stripes', 'Heat', 'Ripple')
        return [self.scene.getDEF(name) for name in names]

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'b':
            toon = self.scene.getDEF('Toon')
            current = int(toon.bands)
            following = BANDS[(BANDS.index(current) + 1) % len(BANDS)] if current in BANDS else 4
            toon.bands = following
            return '%d bands' % (following,)
        if key == 'a':
            for shader in self.shaders():
                shader.activate = True
            return 'linked again'
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
        prog='oglc-x3d-shaders', description=(__doc__ or '').split('\n')[0],
        epilog=Showcase.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its files are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-shaders')
    base: Any = testingcontext.getInteractive()

    class ShowcaseContext(base):                 # pragma: no cover - needs a window
        contextDefinition = ContextDefinition(title='X3D shaders', size=(1024, 640))

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

    ShowcaseContext.ContextMainLoop()
    return 0


if __name__ == '__main__':  # pragma: no cover - the command line
    sys.exit(main())
