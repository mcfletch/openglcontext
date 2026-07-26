#! /usr/bin/env python
"""Overlay UI demonstration: the settings screen, the console and a skin.

Run it and press the keys it prints:

    oglc-ui                 # the default flat skin
    oglc-ui --skin          # the same screens, painted with nine-slice artwork

    F10   the settings screen -- every rendering feature the pass reads
    F9    the console, with the engine's own log going into it
    F8    a licence notice, to show a wall of text scrolling
    F7    a yes/no question
    F5    save a screenshot

The artwork the ``--skin`` mode uses is drawn at start-up rather than shipped,
so the demo shows what a nine-slice does -- corners that stay square while the
frame stretches -- without a binary in the repository.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, List, Optional

from OpenGLContext import testingcontext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import modes as movemodes
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.box import Box
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph.light import DirectionalLight
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.quadrics import Sphere
from OpenGLContext.scenegraph.scenegraph import SceneGraph
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.ui import bindings, console, dialogs, settings
from OpenGLContext.ui.overlay import OverlayMixin

log = logging.getLogger(__name__)
BaseContext: Any = testingcontext.getInteractive()

#: A short licence-shaped wall of text, so the notice screen has to scroll.
NOTICE = '\n\n'.join([
    'OpenGLContext is distributed under a BSD-style licence.',
    'Redistribution and use in source and binary forms, with or without '
    'modification, are permitted provided that the following conditions are '
    'met: redistributions of source code must retain the above copyright '
    'notice, this list of conditions and the following disclaimer; '
    'redistributions in binary form must reproduce the above copyright notice, '
    'this list of conditions and the following disclaimer in the documentation '
    'and/or other materials provided with the distribution.',
    'THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS '
    'IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, '
    'THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR '
    'PURPOSE ARE DISCLAIMED.',
] + ['Paragraph %d of a notice nobody can style away.' % (index,)
     for index in range(1, 40)])


def build_skin(directory: str) -> Any:
    """Draw a nine-slice set into ``directory`` and return a Skin using it.

    Generated rather than shipped: what this demonstrates is that one image
    serves every widget size, and an image drawn here is as good a proof of
    that as one drawn in an editor -- with nothing binary to keep in step.
    """
    from PIL import Image, ImageDraw
    from OpenGLContext.ui.skin import NineSlice, Skin

    def frame(name: str, fill: Any, edge: Any, size: int = 24,
              border: int = 8) -> str:
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=border - 1,
                               fill=fill, outline=edge, width=2)
        path = os.path.join(directory, '%s.png' % (name,))
        image.save(path)
        return path

    def slice(name: str, fill: Any, edge: Any) -> NineSlice:
        return NineSlice(url=[frame(name, fill, edge)], border=(8, 8, 8, 8))

    return Skin(
        panelImage=slice('panel', (18, 22, 32, 230), (90, 110, 150, 255)),
        buttonImage=slice('button', (38, 46, 62, 245), (110, 130, 170, 255)),
        buttonHoverImage=slice('button_hover', (64, 88, 130, 250),
                               (150, 190, 250, 255)),
        buttonDownImage=slice('button_down', (24, 30, 42, 255),
                              (90, 110, 150, 255)),
        buttonDisabledImage=slice('button_off', (28, 30, 34, 180),
                                  (60, 66, 76, 255)),
        fieldImage=slice('field', (12, 14, 20, 250), (80, 96, 130, 255)),
        switchOffImage=slice('switch_off', (12, 14, 20, 250), (110, 130, 170, 255)),
        switchOnImage=slice('switch_on', (60, 120, 80, 250), (140, 220, 160, 255)),
        trackImage=slice('track', (12, 14, 20, 250), (70, 84, 112, 255)),
        thumbImage=slice('thumb', (120, 150, 200, 255), (200, 220, 255, 255)),
        panelPadding=20.0,
    )


def movement_modes() -> List[Any]:
    """The ways of moving this demo offers, so the settings screen has some."""
    return [
        movemodes.WalkMode(name='walk'),
        movemodes.FlyMode(name='fly'),
        movemodes.FPSMode(name='fps'),
    ]


class UIDemoContext(OverlayMixin, BaseContext):
    """A scene with the overlay screens bound to function keys.

    The mix-in comes first so its event routing runs before the navigation
    mix-in's: while a modal panel is up the movement sampler is not fed at all.
    """

    skinned: bool = False
    skinDirectory: str = ''
    console: Optional[console.ConsolePanel] = None
    skin: Any = None

    # Supplied by the interactive context this is built on.
    addEventHandler: Any
    frameCounter: Any
    triggerRedraw: Any

    def OnInit(self) -> None:                   # pragma: no cover - needs a window
        self.skin = build_skin(self.skinDirectory) if self.skinned else None
        self.sg = SceneGraph(children=[
            DirectionalLight(direction=(-0.4, -1, -0.6), intensity=1.0),
            Transform(translation=(-2, 0, 0), children=[Shape(
                geometry=Sphere(radius=1.0),
                appearance=Appearance(material=Material(
                    diffuseColor=(0.7, 0.3, 0.25))))]),
            Transform(translation=(2, 0, 0), children=[Shape(
                geometry=Box(size=(1.6, 1.6, 1.6)),
                appearance=Appearance(material=Material(
                    diffuseColor=(0.25, 0.45, 0.7))))]),
        ])
        # ``keyboard`` key-downs, not ``keypress``: a function key produces no
        # character, so GLFW raises no keypress for one and a keypress binding
        # would be accepted and then never fire.
        for key, handler in (('<F10>', self.openSettings),
                             ('<F9>', self.openConsole),
                             ('<F8>', self.openNotice),
                             ('<F7>', self.askSomething),
                             ('<F6>', self.openBindings)):
            self.addEventHandler('keyboard', name=key, state=1,
                                 function=handler)
        sys.stdout.write(__doc__.split('Run it and press')[1])
        sys.stdout.flush()

    # -- the screens ------------------------------------------------------
    def _skinned(self, panel: Any) -> Any:
        if self.skin is not None:
            panel.skin = self.skin
        return panel

    def openSettings(self, event: Any) -> None:  # pragma: no cover - needs a window
        panel = settings.settings_panel(self)
        self.pushOverlay(self._skinned(panel))

    def openBindings(self, event: Any) -> None:  # pragma: no cover - needs a window
        panel = bindings.open_bindings(self)
        if panel is not None:
            self._skinned(panel)

    def openConsole(self, event: Any) -> None:   # pragma: no cover - needs a window
        registry = console.CommandRegistry()
        registry.add('shadows', self._shadowsCommand,
                     'turn shadows on or off: shadows on|off')
        registry.add('fps', lambda panel: '%.1f' % (
            self.frameCounter.recentFps(),), 'the recent frame rate')
        panel = self._skinned(console.console_panel(registry=registry))
        panel.write('Type "help" for the commands.')
        # Engine warnings go where a player can read them.
        logging.getLogger('OpenGLContext').addHandler(
            console.ConsoleLogHandler(panel))
        self.console = panel
        self.pushOverlay(panel)

    def _shadowsCommand(self, panel: Any, state: str = '') -> str:
        if state:
            self.contextDefinition.shadows = state.lower() in ('on', '1', 'true')
            self.triggerRedraw(1)
        return 'shadows are %s' % (
            'on' if self.contextDefinition.shadows else 'off',)

    def openNotice(self, event: Any) -> None:    # pragma: no cover - needs a window
        self.pushOverlay(self._skinned(
            dialogs.notice('Licence', NOTICE)))

    def askSomething(self, event: Any) -> None:  # pragma: no cover - needs a window
        self.pushOverlay(self._skinned(dialogs.confirm(
            'Download the high-resolution texture pack?',
            detail='About 40MB, cached for next time.',
            yes='Download', no='Not now',
            on_answer=lambda yes: log.warning('answered %s', yes))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--skin', action='store_true',
                        help='paint the screens with generated nine-slice artwork')
    parser.add_argument('--skin-dir', default='',
                        help='where to write that artwork (default: a temp dir)')
    options = parser.parse_args()
    directory = options.skin_dir
    if options.skin and not directory:
        import tempfile
        directory = tempfile.mkdtemp(prefix='oglc-ui-skin-')
    UIDemoContext.skinned = bool(options.skin)
    UIDemoContext.skinDirectory = directory
    UIDemoContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext overlay UI',
        size=(1024, 720),
        movementModes=movement_modes(),
    ))
    return 0


if __name__ == '__main__':
    sys.exit(main())
