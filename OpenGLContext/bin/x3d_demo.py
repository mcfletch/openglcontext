#! /usr/bin/env python
"""X3D: a gallery read from an X3D 4 document and drawn by the PBR renderer.

    oglc-x3d [--directory DIR]

    l      the alcove's lamp on and off: it lights only the alcove
    m      the medallion on the back wall hidden and shown (its `visible`)
    w      the scene written back as X3D in each encoding, beside the document

The document is ``x3d_gallery.x3d``, shipped with this module. It names its
textures and an Inlined glTF vase by relative URL; :func:`prepare` writes
them beside a copy of it -- the surfaces' marble, brick and sandstone maps, and
a lathed vase in gold -- so the scene is the document as an author would ship
it. docs/x3d.rst describes what each node in it does.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'Gallery', 'main', 'prepare']

#: The X3D document the gallery is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_gallery.x3d')
#: The surfaces whose maps the document names, by file prefix.
SURFACES = ('marble', 'brick', 'sandstone')
#: The vase's profile, (radius, height) in metres, from the foot up.
VASE = ((0.0, 0.0), (0.22, 0.0), (0.26, 0.06), (0.18, 0.32), (0.13, 0.5),
        (0.2, 0.68), (0.19, 0.72))


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    if name == 'brick':
        return surfaces.brick(256)
    return surfaces.sandstone(256)


def _vase() -> bytes:
    """The gold vase, as GLB bytes"""
    from opengl_extrusions import lathe  # noqa: PLC0415 only when the vase is written
    from OpenGLContext.loaders.gltf.writer import write_glb  # noqa: PLC0415 only when written
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    from OpenGLContext.scenegraph.appearance import Appearance  # noqa: PLC0415 only when written
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive  # noqa: PLC0415 only when written
    from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial  # noqa: PLC0415 only when written
    swept = lathe(VASE, start_radius=0.0, sides=32, closed_contour=False).merged()
    gold = PhysicalMaterial(baseColor=surfaces.GOLD, metallic=1.0, roughness=0.25)
    return write_glb(mesh_from_primitive(swept.primitives[0], solid=False,
                                         appearance=Appearance(material=gold)))


def prepare(directory: str, force: bool = False) -> str:
    """The document, copied to `directory` with the textures and the vase it names

    Files already there are kept unless `force`. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file, write_bytes  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in SURFACES:
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    vase = os.path.join(directory, 'vase.glb')
    if force or not os.path.exists(vase):
        write_bytes(vase, _vase())
    return target


class Gallery:
    """The gallery scene with no window: what the demo, its tutorial and its tests share

    ``scene`` is the document read by the engine's loader; ``alcove_lamp``
    and ``medallion`` are its DEF-named nodes the keys change.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'l': "the alcove's lamp on and off",
        'm': 'the medallion hidden and shown',
        'w': 'the scene written back as X3D in each encoding',
    }

    def __init__(self, directory: str) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        self.alcove_lamp = self.scene.getDEF('AlcoveLamp')
        self.medallion = self.scene.getDEF('Medallion')

    def write(self) -> "dict[str, int]":
        """The scene written as X3D in each encoding beside the document; each file's size by name"""
        from vrml import x3d  # noqa: PLC0415 kept with its use
        sizes = {}
        for suffix in ('x3d', 'x3dv', 'x3dj'):
            path = os.path.join(self.directory, 'written.%s' % (suffix,))
            x3d.dump(self.scene, path)
            sizes[os.path.basename(path)] = os.path.getsize(path)
        return sizes

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'l':
            self.alcove_lamp.on = not self.alcove_lamp.on
            return 'alcove lamp %s' % ('on' if self.alcove_lamp.on else 'off')
        if key == 'm':
            self.medallion.visible = not self.medallion.visible
            return 'medallion %s' % ('shown' if self.medallion.visible else 'hidden')
        if key == 'w':
            return 'wrote ' + ', '.join('%s (%d bytes)' % item for item in self.write().items())
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the gallery in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d', description=__doc__.split('\n')[0],
        epilog=Gallery.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its files are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-gallery')
    base: Any = testingcontext.getInteractive()

    class GalleryContext(base):                 # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.gallery = Gallery(directory)
            self.sg = self.gallery.scene
            for key in Gallery.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(Gallery.help())

        def OnKey(self, event: Any) -> None:
            said = self.gallery.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(1)

    GalleryContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D gallery', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
