#! /usr/bin/env python
"""X3D rigid bodies: X3D's RigidBodyPhysics component read from a document and simulated.

    oglc-x3d-rigidbody [--directory DIR]

    p      pause and resume the simulation
    r      start again

The document is ``x3d_rigidbody.x3d``, shipped with this module: brick crates
falling into a heap, a marble ball bounced by a CollisionSensor's contacts, a
brass door swinging against its stop, a steel chain on ball joints, a wheel
driven by a double-axis hinge, a cardan shaft turned by a motor joint through
a universal joint, a piston pushed along a slider, and a dumbbell of two
weights held off its middle. :func:`prepare` writes the stone, brick and
marble maps it names beside a copy of it. docs/x3d.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'RigidBodyScene', 'main', 'prepare']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_rigidbody.x3d')


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


class RigidBodyScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader; ``workshop`` is its
    `RigidBodyCollection`, which the p key pauses.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'p': 'pause and resume the simulation',
        'r': 'start again',
    }

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.path = prepare(directory)
        self.load()

    def load(self) -> None:
        """Read the document afresh"""
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.scene = Loader.load(self.path)
        self.workshop = self.scene.getDEF('WORKSHOP')

    def press(self, key: str) -> str:
        """Answer a key; what it did, for the console"""
        if key == 'p':
            self.workshop.enabled = not self.workshop.enabled
            return 'running' if self.workshop.enabled else 'paused'
        if key == 'r':
            self.load()
            return 'started again'
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-rigidbody', description=__doc__.split('\n')[0],
        epilog=RigidBodyScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document and its maps are written '
                        '(default: the user cache directory)')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-rigidbody')
    base: Any = testingcontext.getInteractive()

    class RigidBodyContext(base):               # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.demo = RigidBodyScene(directory)
            self.sg = self.demo.scene
            for key in RigidBodyScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(RigidBodyScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.demo.press(event.name)
            if said:
                print(said)
                self.sg = self.demo.scene
                self.triggerRedraw(1)

    RigidBodyContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D rigid bodies', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
